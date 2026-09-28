"""Ricerca su YouTube Music (brani, album, artisti, playlist; niente video) via ytmusicapi."""
import logging
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from rapidfuzz import fuzz
from ytmusicapi import YTMusic

log = logging.getLogger("jukebox.music")

# language="it" rompe il parsing delle RICERCHE di ytmusicapi (testato: 0 risultati),
# quindi si cerca con l'interfaccia inglese e location="IT" per il catalogo italiano.
yt = YTMusic(location="IT")
# ...ma in inglese YouTube TRADUCE i titoli dei video ("Muschio Selvaggio" diventa
# "Wild Musk Podcast"): elenchi e dettagli dei podcast si leggono in italiano.
yt_it = YTMusic(language="it", location="IT")


def _artists(item: dict) -> str:
    names = [a["name"] for a in item.get("artists") or [] if a.get("name")]
    return ", ".join(names)


def _thumb(item: dict) -> str | None:
    thumbs = item.get("thumbnails") or []
    return thumbs[-1]["url"] if thumbs else None


def _track(item: dict, album: dict | None = None) -> dict | None:
    video_id = item.get("videoId")
    if not video_id:
        return None
    album_field = item.get("album") if isinstance(item.get("album"), dict) else {}
    artists = item.get("artists") or []
    return {
        "id": video_id,
        "title": item.get("title") or "",
        "artist": _artists(item) or (album or {}).get("artist", ""),
        "artist_id": next((a.get("id") for a in artists if a.get("id")), None)
                     or (album or {}).get("artist_id"),
        "album": album_field.get("name") or (album or {}).get("title"),
        "album_id": album_field.get("id") or (album or {}).get("browse_id"),
        "thumb": _thumb(item) or (album or {}).get("thumb"),
    }


def _tracks(items, album=None) -> list[dict]:
    return [t for t in (_track(x, album) for x in items or []) if t]


def search_songs(query: str, limit: int = 5) -> list[dict]:
    results = _tracks(yt.search(query, filter="songs", limit=limit))
    if not results and _without_connectors(query) != query:
        results = _tracks(yt.search(_without_connectors(query), filter="songs", limit=limit))
    return results[:limit]


def _album_summary(r: dict) -> dict:
    return {
        "browse_id": r["browseId"],
        "title": r.get("title") or "",
        "artist": _artists(r),
        "year": r.get("year"),
        "type": r.get("type") or "Album",
        "thumb": _thumb(r),
    }


TYPE_RANK = {"Album": 0, "EP": 1, "Single": 2}


def _without_connectors(query: str) -> str:
    return " ".join(w for w in query.split() if w.lower() not in CONNECTORS)


def search_albums(query: str, limit: int = 5) -> list[dict]:
    """Album veri prima di EP e singoli. YouTube Music non trova nulla con
    "wow dei verdena" ma trova subito "wow verdena": le preposizioni vanno tolte."""
    results = yt.search(query, filter="albums", limit=limit)
    if not results and _without_connectors(query) != query:
        results = yt.search(_without_connectors(query), filter="albums", limit=limit)
    albums = [_album_summary(r) for r in results if r.get("browseId")]
    albums.sort(key=lambda a: TYPE_RANK.get(a["type"], 1))
    return albums[:limit]


def album_tracks(browse_id: str) -> list[dict]:
    data = yt.get_album(browse_id)
    artists = data.get("artists") or []
    album = {"title": data.get("title"), "artist": _artists(data), "thumb": _thumb(data),
             "browse_id": browse_id,
             "artist_id": next((a.get("id") for a in artists if a.get("id")), None)}
    return _tracks(data.get("tracks"), album)


def find_artist(query: str) -> dict | None:
    """L'artista che corrisponde meglio, con brani più ascoltati e album in ordine cronologico."""
    found = yt.search(query, filter="artists", limit=3)
    if not found:
        return None
    return artist_by_id(found[0]["browseId"])


def artist_by_id(channel_id: str) -> dict:
    data = yt.get_artist(channel_id)
    section = data.get("albums") or {}
    albums = section.get("results") or []
    if section.get("browseId") and section.get("params"):
        try:
            albums = yt.get_artist_albums(section["browseId"], section["params"]) or albums
        except Exception:
            log.exception("elenco completo album non leggibile")
    albums = _discography([_album_summary(a) for a in albums if a.get("browseId")])
    return {"id": channel_id, "name": data.get("name") or "", "songs": data.get("songs") or {},
            "albums": albums}


REISSUE = re.compile(r"remaster|deluxe|anniversary|edition|edizione|expanded|reissue", re.I)


def _original_year(album: dict) -> int:
    """Anno dell'uscita originale: le ristampe "20th Anniversary" del 2024 sono del 2004."""
    year = int(album["year"]) if str(album.get("year") or "").isdigit() else 9999
    m = re.search(r"(\d+)\s*(?:st|nd|rd|th|°)?\s*anniversar", album["title"], re.I)
    return year - int(m.group(1)) if m and year != 9999 else year


def _discography(albums: list[dict]) -> list[dict]:
    """Un solo album per titolo (l'originale se c'è, non la ristampa), in ordine cronologico."""
    by_title = {}
    for album in albums:
        key = normalize(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", album["title"]))
        album = dict(album, year=_original_year(album))
        best = by_title.get(key)
        if best is None or (REISSUE.search(best["title"]) and not REISSUE.search(album["title"])):
            by_title[key] = album
    return sorted(by_title.values(), key=lambda a: a["year"])


def artist_top_songs(artist: dict, limit: int = 50) -> list[dict]:
    songs = artist["songs"]
    items = songs.get("results") or []
    if songs.get("browseId"):
        try:
            items = yt.get_playlist(songs["browseId"], limit=limit).get("tracks", items)
        except Exception:
            log.exception("playlist brani artista non leggibile")
    return _tracks(items)[:limit]


def radio(video_id: str, limit: int = 25) -> list[dict]:
    """Coda "radio" di YouTube Music a partire da un brano (escluso il brano stesso)."""
    data = yt.get_watch_playlist(videoId=video_id, radio=True, limit=limit)
    return [t for t in _tracks(data.get("tracks")) if t["id"] != video_id]


def search_playlist(query: str, limit: int = 100) -> tuple[str, list[dict]]:
    for flt in ("featured_playlists", "community_playlists"):
        for r in yt.search(query, filter=flt, limit=5):
            pid = r.get("browseId") or r.get("playlistId") or ""
            pid = pid[2:] if pid.startswith("VL") else pid
            if not pid:
                continue
            tracks = _tracks(yt.get_playlist(pid, limit=limit).get("tracks"))
            if tracks:
                return r.get("title") or query, tracks
    return "", []


def _as_song(video: dict) -> dict:
    """La versione audio (brano) di un videoclip, se YouTube Music la conosce."""
    title = re.sub(r"\((official|video|videoclip|lyric|visualizer)[^)]*\)|\[[^\]]*\]", " ",
                   video["title"], flags=re.I)
    title = title.split(" - ", 1)[-1].strip()
    try:
        for cand in search_songs(f"{title} {video['artist']}", limit=3):
            if match_score(title, cand["title"], cand["artist"]) >= 70:
                return cand
    except Exception:
        log.exception("conversione videoclip -> brano fallita")
    return video


def charts(limit: int = 30) -> tuple[str, list[dict]]:
    """La classifica italiana. YouTube Music la pubblica solo come playlist di
    videoclip: ogni voce viene convertita nel brano audio corrispondente."""
    data = yt.get_charts(country="IT")
    for pl in data.get("videos") or []:
        if not pl.get("playlistId"):
            continue
        videos = _tracks(yt.get_playlist(pl["playlistId"], limit=limit).get("tracks"))[:limit]
        if videos:
            with ThreadPoolExecutor(max_workers=8) as pool:
                songs = list(pool.map(_as_song, videos))
            return "la classifica italiana del momento", songs
    return search_playlist("top 100 italia")


# --- podcast -----------------------------------------------------------------

def parse_duration(text) -> int:
    """"1 hr 36 min", "45 min", "1:23:45" -> millisecondi (0 se ignoto)."""
    if isinstance(text, (int, float)):
        return int(text * 1000)
    text = str(text or "")
    if re.fullmatch(r"[\d:]+", text):
        secs = 0
        for part in text.split(":"):
            secs = secs * 60 + int(part)
        return secs * 1000
    h = re.search(r"(\d+)\s*(?:hr|h|or)", text)
    m = re.search(r"(\d+)\s*min", text)
    s = re.search(r"(\d+)\s*sec", text)
    return ((int(h.group(1)) if h else 0) * 3600 + (int(m.group(1)) if m else 0) * 60
            + (int(s.group(1)) if s else 0)) * 1000


def _episode(item: dict, show: dict) -> dict | None:
    if not item.get("videoId"):
        return None
    return {
        "id": item["videoId"],
        "kind": "episode",
        "title": item.get("title") or "",
        "artist": show.get("title") or "",
        "podcast": show.get("title") or "",
        "podcast_id": show.get("id"),
        "duration_ms": parse_duration(item.get("duration") or item.get("duration_seconds")),
        "thumb": _thumb(item) or show.get("thumb"),
    }


def _podcast_id(browse_id: str) -> str:
    return browse_id[4:] if browse_id.startswith("MPSP") else browse_id


def search_podcasts(query: str, limit: int = 5) -> list[dict]:
    results = yt_it.search(query, filter="podcasts", limit=limit)
    if not results and _without_connectors(query) != query:
        results = yt_it.search(_without_connectors(query), filter="podcasts", limit=limit)
    return [{"id": _podcast_id(r["browseId"]), "title": r.get("title") or "", "artist": "",
             "thumb": _thumb(r)} for r in results if r.get("browseId")][:limit]


def podcast_episodes(show: dict, limit: int = 100) -> list[dict]:
    """Episodi dal più recente al più vecchio."""
    data = yt_it.get_podcast(show["id"], limit=limit)
    show = dict(show, title=data.get("title") or show.get("title"), thumb=_thumb(data) or show.get("thumb"))
    return [e for e in (_episode(x, show) for x in data.get("episodes") or []) if e]


def search_episodes(query: str, limit: int = 5) -> list[dict]:
    """Episodi che parlano di qualcosa o con un ospite; ripiega sui video di YouTube."""
    items = yt.search(query, filter="episodes", limit=limit)
    episodes = []
    for it in items:
        pod = it.get("podcast") if isinstance(it.get("podcast"), dict) else {}
        author = it.get("author")
        author_name = author.get("name", "") if isinstance(author, dict) else (author or "")
        show = {"title": pod.get("name") or author_name,
                "id": _podcast_id(pod["id"]) if pod.get("id") else None}
        ep = _episode(it, show)
        if ep:
            episodes.append(ep)
    if not episodes:
        for it in yt.search(query, filter="videos", limit=limit):
            ep = _episode(it, {"title": _artists(it), "id": None})
            if ep:
                episodes.append(ep)
    episodes = episodes[:limit]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(_original_title, episodes))


def _original_title(ep: dict) -> dict:
    """Titolo, durata e podcast come li ha scritti l'autore, non tradotti in inglese."""
    try:
        data = yt_it.get_episode(f"MPED{ep['id']}")
    except Exception:
        return ep
    author = data.get("author")
    show = author.get("name") if isinstance(author, dict) else author
    return dict(ep, title=data.get("title") or ep["title"],
                podcast=show or ep["podcast"], artist=show or ep["artist"],
                duration_ms=parse_duration(data.get("duration")) or ep["duration_ms"])


# --- playlist personali (profilo pubblico YouTube) ------------------------------

USER_CHANNEL = os.environ.get("JUKEBOX_YT_CHANNEL", "")  # es. https://www.youtube.com/@tuocanale
if "tuocanale" in USER_CHANNEL:  # segnaposto dell'esempio lasciato com'è
    USER_CHANNEL = ""
FAVORITES_WORDS = {"preferiti", "preferite", "favorites", "favoriti", "mi piace", "canzoni preferite",
                   "brani preferiti", "musica preferita"}
_user_cache = {"at": 0.0, "items": []}
_tracks_cache: dict[str, tuple[float, list]] = {}
PLAYLIST_TTL = 1800
_user_lock = threading.Lock()


def _flat(url: str, limit: int | None = None) -> dict:
    """Elenco "piatto" (senza scaricare nulla) di una pagina YouTube via yt-dlp."""
    import yt_dlp
    from . import streams
    extra = {"playlistend": limit} if limit else {}
    with yt_dlp.YoutubeDL(streams._ydl_opts(extract_flat=True, noplaylist=False, **extra)) as ydl:
        return ydl.extract_info(url, download=False) or {}


def user_playlists(max_age: float = 3600) -> list[dict]:
    """Le playlist pubbliche del profilo, aggiornate al massimo ogni ora.

    ytmusicapi ne vede solo una parte (in una prova, 3 su 7): l'elenco
    completo lo dà la scheda "Playlist" del canale letta con yt-dlp."""
    if not USER_CHANNEL:
        return []
    with _user_lock:
        if time.time() - _user_cache["at"] < max_age and _user_cache["items"]:
            return _user_cache["items"]
        try:
            data = _flat(USER_CHANNEL.rstrip("/") + "/playlists")
            items = [{"id": e["id"], "title": e.get("title") or "", "artist": ""}
                     for e in data.get("entries") or [] if e.get("id")]
            _user_cache.update(at=time.time(), items=items)
        except Exception:
            log.exception("playlist del profilo non leggibili")
        return _user_cache["items"]


def user_playlist_tracks(playlist: dict, limit: int = 200, max_age: float = PLAYLIST_TTL) -> list[dict]:
    """Brani di una playlist personale, con cache: Alexa aspetta al massimo 8 secondi
    e "Favorites" letta da zero ne richiedeva quasi 10."""
    cached = _tracks_cache.get(playlist["id"])
    if cached and time.time() - cached[0] < max_age:
        return cached[1]
    try:
        tracks = _tracks(yt.get_playlist(playlist["id"], limit=limit).get("tracks"))
    except Exception:
        # "Favorites" e simili: ytmusicapi non le legge, yt-dlp sì
        data = _flat(f"https://www.youtube.com/playlist?list={playlist['id']}", limit=limit)
        tracks = [{"id": e["id"], "title": e.get("title") or "", "artist": e.get("channel") or "",
                   "thumb": None} for e in data.get("entries") or [] if e.get("id")][:limit]
    _tracks_cache[playlist["id"]] = (time.time(), tracks)
    return tracks


def warm_user_playlists() -> None:
    """Rilegge in background elenco e contenuto delle playlist personali, ogni mezz'ora."""
    def loop():
        while True:
            try:
                playlists = user_playlists(max_age=0)
                total = sum(len(user_playlist_tracks(pl, max_age=0)) for pl in playlists)
                log.info("playlist personali aggiornate: %d playlist, %d brani", len(playlists), total)
            except Exception:
                log.exception("aggiornamento playlist personali fallito")
            time.sleep(PLAYLIST_TTL - 60)

    if USER_CHANNEL:
        threading.Thread(target=loop, daemon=True, name="playlist-warmup").start()


def find_user_playlist(name: str) -> tuple[dict | None, float]:
    """La playlist personale col nome più simile a quello detto, e quanto somiglia (0-100)."""
    playlists = user_playlists()
    if not playlists:
        return None, 0.0
    wanted = normalize(name)
    if wanted in {normalize(w) for w in FAVORITES_WORDS}:
        fav = next((p for p in playlists if p["id"].startswith(("FL", "LL"))
                    or normalize(p["title"]) in ("favorites", "preferiti")), None)
        if fav:
            return fav, 100.0
    scored = [(fuzz.ratio(wanted, normalize(p["title"])), p) for p in playlists]
    score, best = max(scored, key=lambda x: x[0])
    return best, float(score)


def rank(query: str, items: list[dict]) -> list[dict]:
    """Candidati ordinati per somiglianza a quanto detto (a parità, l'ordine di YouTube)."""
    return sorted(items, key=lambda it: -match_score(query, it["title"], it.get("artist", "")))


def find_in_album(tracks: list[dict], title: str) -> int | None:
    """Indice del brano dell'album che somiglia di più al titolo detto."""
    scored = [(match_score(title, t["title"], ""), i) for i, t in enumerate(tracks)]
    best = max(scored, default=(0, None))
    return best[1] if best[0] >= 60 else None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"\((feat|ft|with|remaster)[^)]*\)|\[[^\]]*\]", " ", text.lower())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


CONNECTORS = {"di", "dei", "degli", "del", "della", "delle", "de", "da", "by", "the"}


def match_score(query: str, title: str, artist: str) -> float:
    """0-100: quanto il titolo corrisponde a ciò che è stato detto.

    Le parole dell'artista e le preposizioni vengono tolte dalla frase prima del
    confronto, e il titolo è confrontato per intero (senza parentesi): così
    "sole" NON corrisponde a "Alma de Rezabaile (Casa Sole)", mentre
    "albachiara vasco rossi" corrisponde pienamente ad "Albachiara".
    """
    artist_words = set(normalize(artist).split())
    rest = [w for w in normalize(query).split() if w not in artist_words and w not in CONNECTORS]
    clean_title = normalize(re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title))
    if not rest or not clean_title:
        return 0.0
    return fuzz.ratio(" ".join(rest), clean_title)


def is_confident(query: str, best: dict, runner_up: dict | None) -> bool:
    """Decide se suonare subito il primo risultato o chiedere conferma.

    `best`/`runner_up` hanno "title" e "artist". Restituire False fa chiedere
    ad Alexa "Intendi <titolo> di <artista>?".
    """
    # Regola di partenza, da tarare sull'uso reale: soglie più alte = più domande, meno errori.
    score = match_score(query, best["title"], best["artist"])
    if runner_up is None:
        return score >= 70
    gap = score - match_score(query, runner_up["title"], runner_up["artist"])
    return score >= 85 or (score >= 70 and gap >= 15)
