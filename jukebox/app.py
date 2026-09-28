"""Endpoint HTTP: /alexa riceve le richieste della skill, /s/ serve l'audio."""
import json
import logging
import os
import re

from ask_sdk_core.serialize import DefaultSerializer
from ask_sdk_model import RequestEnvelope
from ask_sdk_webservice_support.verifier import RequestVerifier, TimestampVerifier
from flask import Flask, Response, abort, jsonify, request

from . import music, skill, streams
from .state import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("jukebox")


def _check_config() -> None:
    """Rifiuta di partire con i segnaposto di deploy/jukebox.env.example, invece di
    funzionare a metà: URL audio verso example.com o firmati con una chiave pubblica."""
    problems = []
    secret = os.environ.get("JUKEBOX_SECRET", "")
    if len(secret) < 32 or secret == "cambiami":
        problems.append("JUKEBOX_SECRET mancante o di esempio: generane una con  openssl rand -hex 32")
    url = os.environ.get("JUKEBOX_PUBLIC_URL", "")
    if not url.startswith("https://") or "example.com" in url:
        problems.append("JUKEBOX_PUBLIC_URL mancante o di esempio: serve l'indirizzo HTTPS reale del server")
    if problems:
        raise SystemExit("Configurazione non valida in /etc/jukebox.env:\n  - " + "\n  - ".join(problems))
    if not os.environ.get("JUKEBOX_SKILL_ID"):
        log.warning("JUKEBOX_SKILL_ID vuoto: accetto richieste da qualsiasi skill Alexa. "
                    "Impostalo appena crei la skill nella console.")
    if "tuocanale" in os.environ.get("JUKEBOX_YT_CHANNEL", ""):
        log.warning("JUKEBOX_YT_CHANNEL è ancora il segnaposto: playlist personali disattivate.")
        os.environ["JUKEBOX_YT_CHANNEL"] = ""


_check_config()

app = Flask(__name__)
store = Store(os.environ.get("JUKEBOX_DB", "/var/lib/jukebox/state.sqlite"))
SKILL_ID = os.environ.get("JUKEBOX_SKILL_ID", "")
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

music.warm_user_playlists()

_serializer = DefaultSerializer()
_verifiers = [RequestVerifier(), TimestampVerifier()]


def _verify(body: str, envelope: dict) -> None:
    """Accetta solo richieste firmate da Alexa e destinate alla nostra skill."""
    typed = _serializer.deserialize(body, RequestEnvelope)
    headers = {k.lower(): v for k, v in request.headers.items()}
    for verifier in _verifiers:
        verifier.verify(headers=headers, serialized_request_env=body,
                        deserialized_request_env=typed)
    app_id = envelope["context"]["System"]["application"]["applicationId"]
    if SKILL_ID and app_id != SKILL_ID:
        raise PermissionError(f"skill sconosciuta {app_id}")


@app.post("/alexa")
def alexa():
    body = request.get_data(as_text=True)
    try:
        envelope = json.loads(body)
        _verify(body, envelope)
    except Exception as exc:
        log.warning("richiesta rifiutata: %s", exc)
        abort(400)
    log.info("-> %s %s", envelope["request"]["type"],
             envelope["request"].get("intent", {}).get("name", ""))
    try:
        return jsonify(skill.handle(store, envelope))
    except Exception:
        log.exception("errore gestendo la richiesta")
        if envelope["request"]["type"].startswith(("AudioPlayer.", "PlaybackController.")):
            return jsonify({"version": "1.0", "response": {}})
        return jsonify(skill._response("Qualcosa è andato storto, riprova tra poco."))


@app.route("/s/<video_id>.m4a", methods=["GET", "HEAD"])
def stream(video_id):
    if not VIDEO_ID.match(video_id) or not streams.check_signature(
            video_id, request.args.get("x"), request.args.get("s")):
        abort(403)
    try:
        path = streams.ensure(video_id)
    except Exception:
        log.exception("estrazione fallita per %s", video_id)
        abort(502)
    # nginx serve il file (con supporto Range) dalla location interna.
    return Response(headers={"X-Accel-Redirect": f"/_jukebox_cache/{path.name}",
                             "Content-Type": "audio/mp4"})


RANGE = re.compile(r"bytes=(\d*)-(\d*)")


@app.route("/p/<video_id>.m4a", methods=["GET", "HEAD"])
def episode(video_id):
    """Episodio di podcast: servito mentre si scarica, con supporto Range."""
    if not VIDEO_ID.match(video_id) or not streams.check_signature(
            video_id, request.args.get("x"), request.args.get("s")):
        abort(403)
    try:
        source = streams.start_episode(video_id)
    except Exception:
        log.exception("estrazione episodio fallita per %s", video_id)
        abort(502)
    if not isinstance(source, streams.Download):
        return Response(headers={"X-Accel-Redirect": f"/_jukebox_cache/{source.name}",
                                 "Content-Type": "audio/mp4"})

    dl = source
    start, end, status = 0, dl.total - 1, 200
    m = RANGE.fullmatch(request.headers.get("Range", ""))
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), dl.total - 1) if m.group(2) else dl.total - 1
        else:  # ultimi N byte
            start = max(dl.total - int(m.group(2)), 0)
        if start > end:
            return Response(status=416, headers={"Content-Range": f"bytes */{dl.total}"})
        status = 206
    headers = {"Content-Type": "audio/mp4", "Accept-Ranges": "bytes",
               "Content-Length": str(end - start + 1), "X-Accel-Buffering": "no"}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{dl.total}"
    if request.method == "HEAD":
        return Response(status=status, headers=headers)

    def body():
        pos = start
        with dl.open() as f:
            while pos <= end:
                if not dl.wait_for(pos):
                    log.warning("episodio %s: dati non arrivati in tempo a %d", video_id, pos)
                    return
                f.seek(pos)
                data = f.read(min(256 * 1024, end + 1 - pos, dl.written - pos))
                if not data:
                    return
                pos += len(data)
                yield data

    return Response(body(), status=status, headers=headers, direct_passthrough=True)


@app.get("/health")
def health():
    return {"ok": True}
