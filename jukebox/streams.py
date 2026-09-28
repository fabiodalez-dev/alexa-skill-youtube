"""Estrazione audio da YouTube Music e cache locale in formato che Alexa accetta.

Alexa non riproduce Opus/WebM: usiamo l'itag 140 (AAC ~128 kbps in MP4), che
YouTube serve anche senza account. Il file DASH viene rimuxato (senza
ricodifica) in un MP4 normale con il moov in testa, così l'Echo può iniziare a
suonare e fare seek con richieste Range servite direttamente da nginx.

Gli episodi dei podcast (1-3 ore, 60-170 MB) non possono aspettare il download
completo: vengono serviti mentre si scaricano (vedi `Download`). Il file DASH di
YouTube ha già l'indice in testa, quindi è riproducibile e navigabile da subito.
"""
import hashlib
import hmac
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
import yt_dlp
from requests.adapters import HTTPAdapter

log = logging.getLogger("jukebox.streams")

CACHE_DIR = Path(os.environ.get("JUKEBOX_CACHE", "/var/cache/jukebox"))
CACHE_MAX_BYTES = int(os.environ.get("JUKEBOX_CACHE_MB", "8000")) * 1024 * 1024
DENO = os.environ.get("JUKEBOX_DENO", "/opt/jukebox/bin/deno")
FORMAT = "140/bestaudio[ext=m4a]"
URL_TTL = 24 * 3600

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_prefetcher = ThreadPoolExecutor(max_workers=2)


def _lock_for(video_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(video_id, threading.Lock())


def cache_path(video_id: str) -> Path:
    return CACHE_DIR / f"{video_id}.m4a"


def _ydl_opts(**extra) -> dict:
    return {
        "format": FORMAT,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "js_runtimes": {"deno": {"path": DENO}},
        # Su alcune reti domestiche l'IPv6 si blocca sui trasferimenti lunghi (in una
        # prova: IPv4 2,3 s, IPv6 oltre 3 minuti): si forza IPv4 verso googlevideo.
        "source_address": "0.0.0.0",
        **extra,
    }


def ensure(video_id: str) -> Path:
    """Restituisce il file in cache, scaricandolo e rimuxandolo se manca."""
    final = cache_path(video_id)
    with _lock_for(video_id):
        if final.exists():
            os.utime(final)
            return final
        started = time.monotonic()
        raw = CACHE_DIR / f".{video_id}.raw"
        tmp = CACHE_DIR / f".{video_id}.tmp.m4a"
        opts = _ydl_opts(outtmpl=str(raw), fixup="never", http_chunk_size=10 * 1024 * 1024)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://music.youtube.com/watch?v={video_id}"])
            subprocess.run(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(raw),
                 "-map", "0:a:0", "-c", "copy", "-movflags", "+faststart", str(tmp)],
                check=True, timeout=60,
            )
            tmp.replace(final)
        finally:
            raw.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)
        log.info("pronto %s in %.1fs (%d KB)", video_id, time.monotonic() - started,
                 final.stat().st_size // 1024)
    _trim_cache()
    return final


def prefetch(video_id: str | None) -> None:
    """Prepara in background il prossimo brano, così parte senza attesa."""
    if not video_id or cache_path(video_id).exists():
        return

    def job():
        try:
            ensure(video_id)
        except Exception:
            log.exception("prefetch fallito per %s", video_id)

    _prefetcher.submit(job)


# --- episodi: download progressivo ------------------------------------------

class _IPv4Adapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs["source_address"] = ("0.0.0.0", 0)
        return super().init_poolmanager(*args, **kwargs)


_http = requests.Session()
_http.mount("https://", _IPv4Adapter())
CHUNK = 8 * 1024 * 1024  # a pezzi: YouTube rallenta le richieste uniche e lunghe


class Download:
    """Un episodio che si sta scaricando: `written` byte sono già leggibili."""

    def __init__(self, video_id: str, total: int):
        self.video_id = video_id
        self.total = total
        self.written = 0
        self.part = CACHE_DIR / f".{video_id}.ep.part"
        self.final = episode_path(video_id)
        self.done = threading.Event()
        self.error: Exception | None = None

    def open(self):
        """Il file giusto da leggere: il parziale finché esiste, poi quello finale."""
        try:
            return open(self.part, "rb")
        except FileNotFoundError:
            return open(self.final, "rb")

    def wait_for(self, position: int, timeout: float = 60) -> bool:
        deadline = time.monotonic() + timeout
        while self.written <= position and not self.done.is_set():
            if time.monotonic() > deadline:
                return False
            self.done.wait(0.1)
        return self.written > position


_downloads: dict[str, Download] = {}


def episode_path(video_id: str) -> Path:
    return CACHE_DIR / f"{video_id}.ep.m4a"


def start_episode(video_id: str) -> Path | Download:
    """File completo se già in cache, altrimenti il download in corso (avviato se serve)."""
    final = episode_path(video_id)
    with _lock_for(f"ep:{video_id}"):
        if final.exists():
            os.utime(final)
            return final
        current = _downloads.get(video_id)
        if current and not current.error:
            return current
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            info = ydl.extract_info(f"https://music.youtube.com/watch?v={video_id}", download=False)
        url, headers = info["url"], dict(info.get("http_headers") or {})
        total = info.get("filesize")
        if not total:
            head = _http.head(url, headers=headers, timeout=15, allow_redirects=True)
            total = int(head.headers["Content-Length"])
        dl = Download(video_id, int(total))
        _downloads[video_id] = dl
        threading.Thread(target=_fetch, args=(dl, url, headers), daemon=True).start()
        log.info("episodio %s: download avviato (%d MB)", video_id, dl.total // 2**20)
        return dl


def _fetch(dl: Download, url: str, headers: dict) -> None:
    started = time.monotonic()
    try:
        with open(dl.part, "wb") as out:
            while dl.written < dl.total:
                end = min(dl.written + CHUNK, dl.total) - 1
                resp = _http.get(url, headers={**headers, "Range": f"bytes={dl.written}-{end}"},
                                 timeout=30)
                resp.raise_for_status()
                if not resp.content:
                    raise IOError("risposta vuota da googlevideo")
                out.write(resp.content)
                out.flush()
                dl.written += len(resp.content)
        dl.part.replace(dl.final)
        log.info("episodio %s completo in %.1fs", dl.video_id, time.monotonic() - started)
    except Exception as exc:
        dl.error = exc
        log.exception("download episodio %s fallito", dl.video_id)
        dl.part.unlink(missing_ok=True)
    finally:
        dl.done.set()
        _downloads.pop(dl.video_id, None)
        _trim_cache()


def _trim_cache() -> None:
    files = sorted(CACHE_DIR.glob("*.m4a"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    while files and total > CACHE_MAX_BYTES:
        victim = files.pop(0)
        total -= victim.stat().st_size
        victim.unlink(missing_ok=True)


def _signature(video_id: str, expires: int) -> str:
    key = os.environ["JUKEBOX_SECRET"].encode()
    return hmac.new(key, f"{video_id}|{expires}".encode(), hashlib.sha256).hexdigest()[:32]


def signed_url(video_id: str, episode: bool = False) -> str:
    base = os.environ["JUKEBOX_PUBLIC_URL"].rstrip("/")
    expires = int(time.time()) + URL_TTL
    route = "p" if episode else "s"
    return f"{base}/{route}/{video_id}.m4a?x={expires}&s={_signature(video_id, expires)}"


def check_signature(video_id: str, expires: str, sig: str) -> bool:
    try:
        exp = int(expires)
    except (TypeError, ValueError):
        return False
    return exp > time.time() and hmac.compare_digest(_signature(video_id, exp), sig or "")
