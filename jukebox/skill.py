"""Logica della skill Alexa "Jukebox": intent vocali ed eventi AudioPlayer."""
import logging
import itertools
import random
import re
from dataclasses import asdict

from . import music, streams
from .parse import Command, parse
from .state import Store

log = logging.getLogger("jukebox.skill")

# intent -> suggerimento per l'interprete delle frasi
QUERY_INTENTS = {
    "PlaySongIntent": "song",
    "PlayAlbumIntent": "album",
    "PlayAlbumTrackIntent": "track",
    "PlayArtistIntent": "artist",
    "PlayArtistShuffleIntent": "artist_shuffle",
    "PlayDiscographyIntent": "discography",
    "PlayLatestAlbumIntent": "album_latest",
    "PlayFirstAlbumIntent": "album_first",
    "PlayRadioIntent": "radio",
    "PlayPlaylistIntent": "playlist",
    "PlayMoodIntent": "mood",
    "PlayPodcastIntent": "podcast",
    "PlayLatestEpisodeIntent": "podcast_latest",
    "PlayEpisodeIntent": "episode",
    "MyPlaylistIntent": "my_playlist",
}
LOOP_INTENTS = ("LoopCurrentIntent", "LoopQueueIntent", "StopLoopIntent",
                "AMAZON.LoopOnIntent", "AMAZON.LoopOffIntent")
_seq = itertools.count()
PROGRESS_EVERY_MS = 60_000

HELP = ("Puoi chiedermi un brano, per esempio: metti Albachiara di Vasco Rossi. "
        "Un album: metti l'album Wow dei Verdena. Una traccia: metti la terza traccia di Wow. "
        "Un artista: metti musica di Lucio Dalla, oppure la discografia di De André. "
        "O ancora: la radio di Albachiara, la classifica, musica rilassante. "
        "Per i podcast: l'ultimo episodio di Tintoria, la puntata con Barbero, riprendi il podcast, "
        "vai avanti di cinque minuti. Le tue playlist: la mia playlist Relax, i miei preferiti. "
        "E per ripetere: metti in loop questa canzone, oppure metti in loop l'album Wow. "
        "Durante l'ascolto: Alexa, avanti, indietro, pausa, riprendi, casuale. Cosa vuoi ascoltare?")


# --- costruzione risposte -------------------------------------------------

def _response(speech=None, directives=None, end=True, reprompt=None, session=None):
    body = {"shouldEndSession": end}
    if speech:
        body["outputSpeech"] = {"type": "PlainText", "text": speech}
    if reprompt:
        body["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    if directives:
        body["directives"] = directives
    out = {"version": "1.0", "response": body}
    if session:
        out["sessionAttributes"] = session
    return out


def _ask(speech, session=None):
    return _response(speech, end=False, reprompt=speech, session=session)


def _only_directives(out):
    """Le risposte ai tasti fisici e agli eventi non possono contenere voce né shouldEndSession."""
    directives = out["response"].get("directives")
    return {"version": "1.0", "response": {"directives": directives} if directives else {}}


def _token(index, track):
    # il contatore rende unico ogni accodamento: serve per ripetere lo stesso brano in loop
    return f"{index}:{track['id']}:{next(_seq)}"


def _index_from_token(token):
    try:
        return int((token or "").split(":", 1)[0])
    except ValueError:
        return None


def _play_directive(state, index, offset=0, behavior="REPLACE_ALL", previous_token=None):
    track = state["queue"][index]
    episode = track.get("kind") == "episode"
    stream = {
        "url": streams.signed_url(track["id"], episode=episode),
        "token": _token(index, track),
        "offsetInMilliseconds": int(offset),
    }
    if episode:
        # Alexa ci manda la posizione ogni minuto: se la corrente salta, non si perde il punto.
        stream["progressReport"] = {"progressReportIntervalInMilliseconds": PROGRESS_EVERY_MS}
    if behavior == "ENQUEUE":
        stream["expectedPreviousToken"] = previous_token
    metadata = {"title": track["title"], "subtitle": track["artist"]}
    if track.get("thumb"):
        metadata["art"] = {"sources": [{"url": track["thumb"]}]}
    return {"type": "AudioPlayer.Play", "playBehavior": behavior,
            "audioItem": {"stream": stream, "metadata": metadata}}


def _stop_directive():
    return {"type": "AudioPlayer.Stop"}


def _minutes(ms):
    return max(int(ms // 60000), 0)


def _describe(item, kind="song"):
    if kind == "podcast":
        return f"il podcast {item['title']}"
    if kind == "my_playlist":
        return f"la tua playlist {item['title']}"
    if item.get("kind") == "episode":
        return f"{item['title']}, di {item['podcast']}" if item.get("podcast") else item["title"]
    what = f"l'album {item['title']}" if kind == "album" else item["title"]
    return f"{what} di {item['artist']}" if item.get("artist") else what


# --- coda -------------------------------------------------------------------

def _next_index(state, index):
    """Indice del brano dopo `index`, allungando la coda (discografia o radio) se serve."""
    if state.get("loop") == "one":
        return index
    nxt = index + 1
    if nxt < len(state["queue"]):
        return nxt
    while state.get("upcoming_albums"):
        browse_id = state["upcoming_albums"].pop(0)
        try:
            tracks = music.album_tracks(browse_id)
        except Exception:
            log.exception("album successivo non leggibile")
            continue
        if tracks:
            state["queue"].extend(tracks)
            return nxt
    if state.get("radio_seed") and state["queue"]:
        seen = {t["id"] for t in state["queue"]}
        try:
            more = [t for t in music.radio(state["queue"][-1]["id"]) if t["id"] not in seen]
        except Exception:
            log.exception("radio non disponibile")
            more = []
        if more:
            state["queue"].extend(more)
            return nxt
    if state.get("loop") and state["queue"]:
        return 0
    return None


def _start(store, device_id, tracks, index=0, speech=None, radio_seed=None, upcoming=None,
           offset=0, loop=False):
    state = store.get(device_id)
    state.update(queue=tracks, index=index, offset=offset, radio_seed=radio_seed,
                 upcoming_albums=upcoming or [], unshuffled=None, loop=loop)
    store.put(device_id, state)
    if index + 1 < len(tracks) and tracks[index + 1].get("kind") != "episode":
        streams.prefetch(tracks[index + 1]["id"])
    return _response(speech, [_play_directive(state, index, offset)])


# --- risoluzione dei comandi ------------------------------------------------

class Plan:
    """Cosa suonare: la coda, da dove partire, cosa dire e come proseguire."""

    def __init__(self, tracks, index=0, speech=None, radio_seed=None, upcoming=None, offset=0):
        self.tracks, self.index, self.speech = tracks, index, speech
        self.radio_seed, self.upcoming, self.offset = radio_seed, upcoming or [], offset


class Question:
    """Serve una conferma prima di suonare."""

    def __init__(self, speech, pending):
        self.speech, self.pending = speech, pending


class Nothing:
    def __init__(self, speech):
        self.speech = speech


def _pick(query, candidates, kind, cmd, confirmed):
    """Primo candidato se sicuro (o già confermato), altrimenti una domanda."""
    if not confirmed:
        candidates = music.rank(query, candidates)
    if confirmed or len(candidates) == 1 and music.is_confident(query, candidates[0], None):
        return candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    if music.is_confident(query, candidates[0], runner_up):
        return candidates[0]
    pending = {"cmd": asdict(cmd), "kind": kind, "cands": candidates[:3], "i": 0}
    return Question(f"Intendi {_describe(candidates[0], kind)}?", pending)


def _album_plan(album, cmd, song_title=None):
    tracks = music.album_tracks(album["browse_id"])
    if not tracks:
        return Nothing(f"L'album {album['title']} non ha brani ascoltabili.")
    if cmd.kind == "album_track":
        n = cmd.number
        if n == -1:
            n = len(tracks)
        if not 1 <= n <= len(tracks):
            n_tracks = "una traccia" if len(tracks) == 1 else f"{len(tracks)} tracce"
            return Nothing(f"L'album {album['title']} ha solo {n_tracks}.")
        return Plan(tracks, n - 1, f"Traccia {n} di {album['title']}: {tracks[n - 1]['title']}.")
    if cmd.kind == "song_in_album":
        idx = music.find_in_album(tracks, song_title or cmd.query)
        if idx is not None:
            return Plan(tracks, idx, f"Ecco {tracks[idx]['title']}, dall'album {album['title']}.")
        return None  # il chiamante ripiega sulla ricerca normale
    return Plan(tracks, 0, f"Ecco {_describe(album, 'album')}.")


def _episode_plan(store, episodes, index, intro):
    """Parte dall'episodio scelto, dal punto in cui eri rimasto se l'avevi iniziato."""
    ep = episodes[index]
    saved = store.progress(ep["id"])
    if saved and not saved[1] and saved[0] > 60_000:
        return Plan(episodes, index, f"{intro}Riprendo {_describe(ep)} dal minuto {_minutes(saved[0])}.",
                    offset=saved[0])
    return Plan(episodes, index, f"{intro}{_describe(ep)}.")


def _resolve(cmd: Command, chosen=None, confirmed=False, store=None):
    """Trasforma un comando in Plan, Question o Nothing."""
    kind, q = cmd.kind, cmd.query

    if kind in ("podcast", "podcast_latest"):
        cands = [chosen] if chosen else music.search_podcasts(q)
        if not cands:
            return Nothing(f"Non ho trovato nessun podcast per {q}.")
        pick = _pick(q, cands, "podcast", cmd, confirmed or bool(chosen))
        if isinstance(pick, Question):
            return pick
        episodes = music.podcast_episodes(pick)
        if not episodes:
            return Nothing(f"Il podcast {pick['title']} non ha episodi ascoltabili.")
        if kind == "podcast":
            unfinished = store.last_unfinished(pick["id"]) if store else None
            if unfinished:
                idx = next((i for i, e in enumerate(episodes) if e["id"] == unfinished[0]["id"]), None)
                if idx is None:
                    episodes, idx = [unfinished[0]] + episodes, 0
                return _episode_plan(store, episodes, idx, "")
        return _episode_plan(store, episodes, 0, "Ultimo episodio: ")

    if kind in ("my_playlist", "playlist"):
        pick, score = (chosen, 100.0) if chosen else music.find_user_playlist(q)
        if pick and (score >= 75 or (kind == "my_playlist" and score >= 60 and confirmed)):
            tracks = music.user_playlist_tracks(pick)
            if not tracks:
                return Nothing(f"La tua playlist {pick['title']} è vuota o non è leggibile.")
            return Plan(tracks, 0, f"Ecco la tua playlist {pick['title']}: {len(tracks)} brani.",
                        radio_seed=tracks[-1]["id"])
        if kind == "my_playlist":
            playlists = music.user_playlists()
            if not playlists:
                return Nothing("Non riesco a leggere le playlist del tuo profilo.")
            cands = music.rank(q, playlists)[:3]
            pending = {"cmd": asdict(cmd), "kind": "my_playlist", "cands": cands, "i": 0}
            return Question(f"Intendi {_describe(cands[0], 'my_playlist')}?", pending)
        # "la playlist X" che non è tua: si cerca fra quelle pubbliche di YouTube Music

    if kind == "episode":
        cands = music.search_episodes(q)
        if not cands:
            return Nothing(f"Non ho trovato episodi su {q}.")
        return _episode_plan(store, cands[:1], 0, "")

    if kind == "song":
        cands = [chosen] if chosen else music.search_songs(q)
        if not cands:
            return Nothing(f"Non ho trovato nessun brano per {q}.")
        pick = _pick(q, cands, "song", cmd, confirmed or bool(chosen))
        if isinstance(pick, Question):
            return pick
        return Plan([pick], 0, f"Ecco {_describe(pick)}.", radio_seed=pick["id"])

    if kind in ("album", "album_track", "song_in_album"):
        album_query = cmd.album if kind == "song_in_album" else q
        cands = [chosen] if chosen else music.search_albums(album_query)
        if not cands:
            if kind == "song_in_album":
                return _resolve(Command("song", f"{q} {cmd.album}"))
            return Nothing(f"Non ho trovato nessun album per {album_query}.")
        if kind == "album_track" and not chosen and cmd.number > 1:
            # "la traccia 3 di Wow": scarta i singoli e gli EP troppo corti
            long_enough = [a for a in cands if a["type"] == "Album"] or cands
            cands = long_enough
        pick = _pick(album_query, cands, "album", cmd, confirmed or bool(chosen))
        if isinstance(pick, Question):
            return pick
        plan = _album_plan(pick, cmd)
        if plan is None:  # brano non trovato nell'album
            return _resolve(Command("song", f"{q} {cmd.album}"))
        return plan

    if kind in ("artist", "artist_shuffle", "discography", "album_latest", "album_first"):
        artist = music.find_artist(q)
        if not artist:
            return Nothing(f"Non ho trovato l'artista {q}.")
        name = artist["name"]
        if kind in ("artist", "artist_shuffle"):
            tracks = music.artist_top_songs(artist)
            if not tracks:
                return Nothing(f"Non ho trovato brani di {name}.")
            if kind == "artist_shuffle":
                random.shuffle(tracks)
                return Plan(tracks, 0, f"Brani di {name} in ordine casuale.", radio_seed=tracks[-1]["id"])
            return Plan(tracks, 0, f"Ecco i brani più ascoltati di {name}.", radio_seed=tracks[-1]["id"])
        albums = artist["albums"]
        if not albums:
            return Nothing(f"Non ho trovato album di {name}.")
        if kind == "discography":
            first = albums[0]
            tracks = music.album_tracks(first["browse_id"])
            year = f", del {first['year']}" if first.get("year") else ""
            return Plan(tracks, 0,
                        f"Discografia di {name}: {len(albums)} album dal primo all'ultimo. "
                        f"Si parte con {first['title']}{year}.",
                        upcoming=[a["browse_id"] for a in albums[1:]])
        album = albums[-1] if kind == "album_latest" else albums[0]
        album = dict(album, artist=album.get("artist") or name)
        year = f", del {album['year']}" if album.get("year") else ""
        plan = _album_plan(album, Command("album"))
        if isinstance(plan, Plan):
            label = "l'ultimo album" if kind == "album_latest" else "il primo album"
            plan.speech = f"Ecco {label} di {name}: {album['title']}{year}."
        return plan

    if kind == "radio":
        cands = music.search_songs(q)
        if not cands:
            return Nothing(f"Non ho trovato niente per {q}.")
        seed = cands[0]
        return Plan([seed] + music.radio(seed["id"]), 0,
                    f"Radio a partire da {_describe(seed)}.", radio_seed=seed["id"])

    if kind == "playlist":  # non è una playlist personale (vedi sopra)
        title, tracks = ("", [])
        if cmd.wake:  # "musica classica come sveglia" -> prima la versione per il risveglio
            title, tracks = music.search_playlist(f"{q} per svegliarsi")
        if not tracks:
            title, tracks = music.search_playlist(q)
        if not tracks:
            return Nothing(f"Non ho trovato playlist per {q}.")
        return Plan(tracks, 0, f"Ecco la playlist {title}.", radio_seed=tracks[-1]["id"])

    if kind == "charts":
        title, tracks = music.charts()
        if not tracks:
            return Nothing("Non riesco a leggere la classifica in questo momento.")
        return Plan(tracks, 0, f"Ecco {title}.")

    return Nothing("Non ho capito cosa vuoi ascoltare.")


def _execute(store, device_id, result):
    if isinstance(result, Plan):
        return _start(store, device_id, result.tracks, result.index, result.speech,
                      result.radio_seed, result.upcoming, result.offset)
    if isinstance(result, Question):
        return _ask(result.speech, {"pending": result.pending})
    return _response(result.speech)


# --- intent vocali ----------------------------------------------------------

def _slot(intent, name="query"):
    return ((intent.get("slots") or {}).get(name) or {}).get("value")


def _confirm(store, device_id, session, yes):
    pending = session.get("pending")
    if not pending:
        return _response("Dimmi cosa vuoi ascoltare, per esempio: metti l'album Wow dei Verdena.")
    cmd = Command(**pending["cmd"])
    if yes:
        choice = pending["cands"][pending["i"]]
        return _execute(store, device_id, _resolve(cmd, chosen=choice, confirmed=True, store=store))
    pending["i"] += 1
    if pending["i"] >= len(pending["cands"]):
        return _response("Va bene. Prova a ripetere il titolo insieme al nome dell'artista.")
    return _ask(f"Allora intendi {_describe(pending['cands'][pending['i']], pending['kind'])}?",
                {"pending": pending})


def _add_to_queue(store, device_id, query):
    state = store.get(device_id)
    result = _resolve(parse(query), confirmed=True, store=store)
    if not isinstance(result, Plan):
        return _response(getattr(result, "speech", "Non ho trovato niente da aggiungere."))
    if not state["queue"]:
        return _execute(store, device_id, result)
    new = result.tracks[result.index:] if len(result.tracks) > 1 and result.index else result.tracks
    pos = state["index"] + 1
    state["queue"][pos:pos] = new
    store.put(device_id, state)
    streams.prefetch(new[0]["id"])
    what = _describe(new[0]) if len(new) == 1 else f"{len(new)} brani"
    return _response(f"Aggiunto {what}: parte dopo questo.")


def _navigate(store, device_id, action):
    """Comandi di trasporto, sia vocali che dai tasti del dispositivo."""
    state = store.get(device_id)
    if not state["queue"]:
        return _response("Non c'è niente in riproduzione.")
    index = min(state["index"], len(state["queue"]) - 1)
    if action == "next":
        target = _next_index(state, index)
        if target is None:
            return _response("Questo era l'ultimo brano.", [_stop_directive()])
    elif action == "previous":
        target = max(index - 1, 0)
    elif action == "restart":
        target = index
    else:  # resume
        return _response(None, [_play_directive(state, index, state.get("offset", 0))])
    state.update(index=target, offset=0)
    store.put(device_id, state)
    return _response(None, [_play_directive(state, target)])


def _shuffle(store, device_id, on):
    state = store.get(device_id)
    head, rest = state["queue"][:state["index"] + 1], state["queue"][state["index"] + 1:]
    if on:
        if not rest:
            return _response("Non ci sono altri brani in coda da mescolare.")
        state["unshuffled"] = list(rest)
        random.shuffle(rest)
        speech = "Ordine casuale attivato."
    else:
        if not state.get("unshuffled"):
            return _response("L'ordine casuale non era attivo.")
        rest, state["unshuffled"] = state["unshuffled"], None
        speech = "Ordine casuale disattivato."
    state["queue"] = head + rest
    store.put(device_id, state)
    return _response(speech)


def _current(store, device_id):
    state = store.get(device_id)
    if not state["queue"]:
        return state, None
    return state, state["queue"][min(state["index"], len(state["queue"]) - 1)]


def _now_playing(store, device_id, audio):
    state, track = _current(store, device_id)
    if not track:
        return _response("Non c'è niente in riproduzione.")
    if track.get("kind") == "episode":
        pos = _position(state, audio)
        total = f" su {_minutes(track['duration_ms'])}" if track.get("duration_ms") else ""
        return _response(f"Stai ascoltando {_describe(track)}. Sei al minuto {_minutes(pos)}{total}.")
    album = f", dall'album {track['album']}" if track.get("album") else ""
    return _response(f"Sta suonando {_describe(track)}{album}.")


def _position(state, audio):
    """Posizione attuale: dal contesto di Alexa se riguarda il brano corrente, sennò l'ultima salvata."""
    idx = _index_from_token((audio or {}).get("token"))
    if idx is not None and idx == state["index"]:
        return int(audio.get("offsetInMilliseconds") or 0)
    return int(state.get("offset") or 0)


def _duration_ms(value):
    """Slot AMAZON.DURATION in formato ISO 8601: PT5M, PT30S, PT1H10M."""
    m = re.fullmatch(r"P(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)", value or "")
    if not m or not any(m.groups()):
        return None
    h, mi, se = (int(g or 0) for g in m.groups())
    return ((h * 60 + mi) * 60 + se) * 1000


def _seek(store, device_id, audio, delta_ms=None, absolute_ms=None):
    state, track = _current(store, device_id)
    if not track:
        return _response("Non c'è niente in riproduzione.")
    pos = absolute_ms if absolute_ms is not None else _position(state, audio) + delta_ms
    if track.get("duration_ms"):
        pos = min(pos, track["duration_ms"] - 5000)
    pos = max(int(pos), 0)
    state["offset"] = pos
    store.put(device_id, state)
    return _response(None, [_play_directive(state, state["index"], pos)])


def _resume_podcast(store, device_id):
    last = store.last_unfinished()
    if not last:
        return _response("Non hai podcast lasciati a metà.")
    track, offset = last
    return _start(store, device_id, [track], 0,
                  f"Riprendo {_describe(track)} dal minuto {_minutes(offset)}.", offset=offset)


def _album_of_current(store, device_id):
    _, track = _current(store, device_id)
    if not track or not track.get("album_id"):
        return _response("Non so da che album viene questo brano.")
    tracks = music.album_tracks(track["album_id"])
    idx = next((i for i, t in enumerate(tracks) if t["id"] == track["id"]), None)
    where = f" Questo brano è la traccia {idx + 1}." if idx is not None else ""
    return _start(store, device_id, tracks, 0,
                  f"Ecco l'album {track.get('album') or ''} dall'inizio.{where}")


def _artist_of_current(store, device_id):
    _, track = _current(store, device_id)
    if not track or not track.get("artist_id"):
        return _response("Non so di che artista è questo brano.")
    artist = music.artist_by_id(track["artist_id"])
    tracks = [t for t in music.artist_top_songs(artist) if t["id"] != track["id"]]
    if not tracks:
        return _response(f"Non ho trovato altri brani di {artist['name']}.")
    return _start(store, device_id, tracks, 0, f"Altri brani di {artist['name']}.",
                  radio_seed=tracks[-1]["id"])


def _requeue(state, speech):
    """Dopo un cambio di loop sostituisce il brano già accodato, senza interrompere l'ascolto."""
    index = state["index"]
    nxt = _next_index(state, index) if state["queue"] else None
    if nxt is None:
        return _response(speech)
    return _response(speech, [_play_directive(state, nxt, behavior="REPLACE_ENQUEUED")])


def _loop(store, device_id, name):
    state = store.get(device_id)
    if not state["queue"]:
        return _response("Non c'è niente in riproduzione da ripetere.")
    if name == "LoopCurrentIntent":
        state["loop"] = "one"
        speech = f"Ripeto {_describe(_current(store, device_id)[1])} finché non mi dici basta."
    elif name in ("LoopQueueIntent", "AMAZON.LoopOnIntent"):
        state.update(loop="all", radio_seed=None)
        speech = "Ripeto tutta la coda dall'inizio quando finisce."
    else:
        state["loop"] = False
        speech = "Loop disattivato."
    store.put(device_id, state)
    return _requeue(state, speech)


def _loop_play(store, device_id, query):
    """"metti in loop Albachiara" / "metti in loop l'album Wow" / "in loop i Verdena"."""
    cmd = parse(query)
    result = _resolve(cmd, confirmed=True, store=store)
    if not isinstance(result, Plan):
        return _execute(store, device_id, result)
    single = len(result.tracks) == 1 or cmd.kind in ("song", "song_in_album", "album_track")
    if single:
        tracks, index, what = [result.tracks[result.index]], 0, _describe(result.tracks[result.index])
    else:
        tracks, index, what = result.tracks, result.index, (result.speech or "").removeprefix("Ecco ").rstrip(".")
    # su un brano singolo la radio resta pronta: se togli il loop, la musica continua
    return _start(store, device_id, tracks, index, f"In loop: {what}.", upcoming=result.upcoming,
                  radio_seed=tracks[0]["id"] if single else None, loop="one" if single else "all")


def _list_playlists():
    playlists = music.user_playlists()
    if not playlists:
        return _response("Non riesco a leggere le playlist del tuo profilo.")
    names = ", ".join(p["title"] for p in playlists)
    return _ask(f"Sul tuo profilo hai {len(playlists)} playlist: {names}. Quale vuoi ascoltare?",
                {"expect": "my_playlist"})


def _intent(store, device_id, request, session, audio=None):
    intent = request["intent"]
    name = intent["name"]
    query = _slot(intent)

    if name in QUERY_INTENTS:
        if not query:
            return _ask("Non ho capito il titolo. Cosa vuoi ascoltare?")
        cmd = parse(query, QUERY_INTENTS[name])
        if session.get("expect") == "my_playlist" and cmd.kind in ("song", "playlist"):
            # risposta a "quale vuoi ascoltare?" dopo l'elenco delle playlist
            cmd = parse(query, "my_playlist")
        log.info("frase %r -> %s", query, cmd)
        return _execute(store, device_id, _resolve(cmd, store=store))
    if name == "LoopPlayIntent":
        return _loop_play(store, device_id, query) if query else _ask("Cosa metto in loop?")
    if name in LOOP_INTENTS:
        return _loop(store, device_id, name)
    if name == "ListMyPlaylistsIntent":
        return _list_playlists()
    if name == "MyFavoritesIntent":
        return _execute(store, device_id, _resolve(Command("my_playlist", "preferiti"), store=store))
    if name == "PlayChartsIntent":
        return _execute(store, device_id, _resolve(Command("charts")))
    if name == "AddToQueueIntent":
        return _add_to_queue(store, device_id, query) if query else _ask("Cosa aggiungo alla coda?")
    if name == "PlayAlbumOfCurrentIntent":
        return _album_of_current(store, device_id)
    if name == "PlayArtistOfCurrentIntent":
        return _artist_of_current(store, device_id)
    if name == "NowPlayingIntent":
        return _now_playing(store, device_id, audio)
    if name == "ResumePodcastIntent":
        return _resume_podcast(store, device_id)
    if name == "OlderEpisodeIntent":
        return _navigate(store, device_id, "next")
    if name == "NewerEpisodeIntent":
        return _navigate(store, device_id, "previous")
    if name in ("SeekForwardIntent", "SeekBackIntent"):
        delta = _duration_ms(_slot(intent, "duration"))
        if delta is None:
            return _ask("Di quanto? Per esempio: vai avanti di cinque minuti.")
        return _seek(store, device_id, audio, delta if name == "SeekForwardIntent" else -delta)
    if name == "SeekToIntent":
        minute = _slot(intent, "minute")
        if not (minute or "").isdigit():
            return _ask("A che minuto? Per esempio: vai al minuto venti.")
        return _seek(store, device_id, audio, absolute_ms=int(minute) * 60000)
    if name == "AMAZON.YesIntent":
        return _confirm(store, device_id, session, True)
    if name == "AMAZON.NoIntent":
        return _confirm(store, device_id, session, False)
    if name == "AMAZON.NextIntent":
        return _navigate(store, device_id, "next")
    if name == "AMAZON.PreviousIntent":
        return _navigate(store, device_id, "previous")
    if name in ("AMAZON.StartOverIntent", "AMAZON.RepeatIntent"):
        return _navigate(store, device_id, "restart")
    if name == "AMAZON.ResumeIntent":
        return _navigate(store, device_id, "resume")
    if name in ("AMAZON.PauseIntent", "AMAZON.StopIntent", "AMAZON.CancelIntent"):
        return _response(None, [_stop_directive()])
    if name in ("AMAZON.ShuffleOnIntent", "AMAZON.ShuffleOffIntent"):
        return _shuffle(store, device_id, name == "AMAZON.ShuffleOnIntent")
    if name == "AMAZON.HelpIntent":
        return _ask(HELP)
    return _ask("Non ho capito. Puoi dire per esempio: metti Albachiara di Vasco Rossi, "
                "oppure l'album Wow dei Verdena. Cosa vuoi ascoltare?")


# --- eventi AudioPlayer / PlaybackController --------------------------------

def _audio_event(store, device_id, request):
    kind = request["type"].split(".", 1)[1]
    index = _index_from_token(request.get("token"))
    state = store.get(device_id)
    valid = index is not None and index < len(state["queue"])

    track = state["queue"][index] if valid else None
    episode = bool(track and track.get("kind") == "episode")
    offset = int(request.get("offsetInMilliseconds") or 0)

    if kind == "PlaybackStarted" and valid:
        state.update(index=index, offset=offset)
        store.put(device_id, state)
        nxt = state["queue"][index + 1] if index + 1 < len(state["queue"]) else None
        if nxt and nxt.get("kind") != "episode":
            streams.prefetch(nxt["id"])
    elif kind in ("PlaybackStopped", "ProgressReportIntervalElapsed") and valid:
        state.update(index=index, offset=offset)
        store.put(device_id, state)
        if episode:
            store.save_progress(track, offset)
    elif kind == "PlaybackFinished" and episode:
        store.save_progress(track, track.get("duration_ms") or offset, finished=True)
    elif kind == "PlaybackNearlyFinished" and episode:
        pass  # a fine episodio ci si ferma: il precedente si chiede a voce
    elif kind == "PlaybackNearlyFinished" and valid:
        nxt = _next_index(state, index)
        store.put(device_id, state)
        if nxt is not None:
            streams.prefetch(state["queue"][nxt]["id"])
            return _only_directives(_response(None, [_play_directive(
                state, nxt, behavior="ENQUEUE", previous_token=request["token"])]))
    elif kind == "PlaybackFailed":
        log.error("riproduzione fallita: %s", request.get("error"))
    return {"version": "1.0", "response": {}}


def _controller_event(store, device_id, request):
    action = {
        "NextCommandIssued": "next",
        "PreviousCommandIssued": "previous",
        "PlayCommandIssued": "resume",
    }.get(request["type"].split(".", 1)[1])
    if action:
        return _only_directives(_navigate(store, device_id, action))
    return _only_directives(_response(None, [_stop_directive()]))  # PauseCommandIssued


# --- ingresso ---------------------------------------------------------------

def handle(store: Store, envelope: dict) -> dict:
    request = envelope["request"]
    rtype = request["type"]
    device_id = envelope["context"]["System"]["device"]["deviceId"]
    session = (envelope.get("session") or {}).get("attributes") or {}

    if rtype == "LaunchRequest":
        return _ask("Jukebox pronto. Cosa vuoi ascoltare?")
    if rtype == "IntentRequest":
        audio = (envelope.get("context") or {}).get("AudioPlayer")
        return _intent(store, device_id, request, session, audio)
    if rtype.startswith("AudioPlayer."):
        return _audio_event(store, device_id, request)
    if rtype.startswith("PlaybackController."):
        return _controller_event(store, device_id, request)
    if rtype == "System.ExceptionEncountered":
        log.error("eccezione lato Alexa: %s", request.get("error"))
    return {"version": "1.0", "response": {}}
