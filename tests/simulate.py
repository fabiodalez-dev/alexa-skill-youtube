"""Simula le richieste di Alexa contro la logica della skill (senza firma HTTP).

Uso sul server:
  sudo runuser -u jukebox -- bash -c 'set -a; . /etc/jukebox.env; cd /opt/jukebox/app && /opt/jukebox/venv/bin/python tests/simulate.py'
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jukebox import skill  # noqa: E402
from jukebox.state import Store  # noqa: E402

store = Store(os.path.join(tempfile.mkdtemp(), "test.sqlite"))


def env(req, attrs=None):
    return {
        "context": {"System": {"device": {"deviceId": "dev1"}, "application": {"applicationId": "x"}}},
        "session": {"attributes": attrs or {}},
        "request": req,
    }


def intent(name, query=None, attrs=None):
    slots = {"query": {"name": "query", "value": query}} if query else {}
    return skill.handle(store, env({"type": "IntentRequest", "intent": {"name": name, "slots": slots}}, attrs))


def event(kind, token=None):
    return skill.handle(store, env({"type": kind, "token": token}))


def show(tag, out, started=None):
    resp = out["response"]
    speech = resp.get("outputSpeech", {}).get("text")
    plays = [d["audioItem"]["metadata"]["title"] for d in resp.get("directives", [])
             if d["type"] == "AudioPlayer.Play"]
    queue = len(store.get("dev1")["queue"])
    took = f"{time.monotonic() - started:.1f}s" if started else ""
    print(f"{tag:44} {took:>5} | {speech!r} | suona={plays} coda={queue}")
    return out


def run(tag, name, query=None, attrs=None):
    t = time.monotonic()
    return show(tag, intent(name, query, attrs), t)


run("brano (catch-all)", "PlaySongIntent", "albachiara di vasco rossi")
run("brano dall'album (catch-all)", "PlaySongIntent", "luna dall'album il suicidio dei samurai")
run("terza traccia (catch-all)", "PlaySongIntent", "la terza traccia dell'album wow dei verdena")
run("traccia numero (intent traccia)", "PlayAlbumTrackIntent", "3 dell'album wow")
run("ultima traccia (catch-all)", "PlaySongIntent", "l'ultima canzone di requiem dei verdena")
run("album", "PlayAlbumIntent", "wow dei verdena")
run("artista", "PlayArtistIntent", "lucio dalla")
run("artista a caso", "PlayArtistShuffleIntent", "vasco rossi")
run("discografia", "PlayDiscographyIntent", "verdena")
state = store.get("dev1")
print("   album successivi in attesa:", len(state["upcoming_albums"]))
last = len(state["queue"]) - 1
show("  fine primo album -> secondo album", event("AudioPlayer.PlaybackNearlyFinished",
                                                   f"{last}:{state['queue'][last]['id']}"))
run("ultimo album", "PlayLatestAlbumIntent", "vasco rossi")
run("primo album", "PlayFirstAlbumIntent", "fabrizio de andré")
run("radio", "PlayRadioIntent", "albachiara")
run("classifica (intent)", "PlayChartsIntent")
run("classifica (catch-all)", "PlaySongIntent", "le canzoni più ascoltate")
run("atmosfera (intent)", "PlayMoodIntent", "studiare")
run("genere (catch-all)", "PlaySongIntent", "musica rilassante")
run("playlist", "PlayPlaylistIntent", "anni ottanta")
run("canzone dal testo", "PlaySongIntent", "e la chiamano estate")
run("brano", "PlaySongIntent", "luna dei verdena")
run("aggiungi alla coda", "AddToQueueIntent", "vita spericolata")
print("   prossimo in coda:", store.get("dev1")["queue"][1]["title"])
run("album di questo brano", "PlayAlbumOfCurrentIntent")
run("altro di questo artista", "PlayArtistOfCurrentIntent")
run("casuale on", "AMAZON.ShuffleOnIntent")
run("casuale off", "AMAZON.ShuffleOffIntent")
run("cosa suona", "NowPlayingIntent")
out = run("ambiguo", "PlaySongIntent", "sole")
if out.get("sessionAttributes"):
    out = run("  -> no", "AMAZON.NoIntent", attrs=out["sessionAttributes"])
    if out.get("sessionAttributes"):
        run("  -> sì", "AMAZON.YesIntent", attrs=out["sessionAttributes"])

print("\n--- podcast ---")


def audio_env(req, token, offset):
    e = env(req)
    e["context"]["AudioPlayer"] = {"token": token, "offsetInMilliseconds": offset, "playerActivity": "PLAYING"}
    return e


run("ultimo episodio (intent)", "PlayLatestEpisodeIntent", "tintoria")
state = store.get("dev1")
ep = state["queue"][0]
token = f"0:{ep['id']}"
print("   episodi in coda:", len(state["queue"]), "| durata ms:", ep.get("duration_ms"))
show("  avviato", event("AudioPlayer.PlaybackStarted", token))
r = skill.handle(store, env({"type": "AudioPlayer.ProgressReportIntervalElapsed", "token": token,
                             "offsetInMilliseconds": 34 * 60000}))
print("   posizione salvata dopo il report:", store.progress(ep["id"]))
show("cosa sto ascoltando", skill.handle(store, audio_env(
    {"type": "IntentRequest", "intent": {"name": "NowPlayingIntent", "slots": {}}}, token, 34 * 60000)))
show("avanti di 5 minuti", skill.handle(store, audio_env(
    {"type": "IntentRequest", "intent": {"name": "SeekForwardIntent",
                                         "slots": {"duration": {"name": "duration", "value": "PT5M"}}}},
    token, 34 * 60000)))
print("   offset richiesto:", store.get("dev1")["offset"] // 60000, "minuti")
show("indietro di 30 secondi", skill.handle(store, audio_env(
    {"type": "IntentRequest", "intent": {"name": "SeekBackIntent",
                                         "slots": {"duration": {"name": "duration", "value": "PT30S"}}}},
    token, 39 * 60000)))
show("vai al minuto 90", skill.handle(store, audio_env(
    {"type": "IntentRequest", "intent": {"name": "SeekToIntent",
                                         "slots": {"minute": {"name": "minute", "value": "90"}}}},
    token, 0)))
show("  pausa (stop a 41 min)", skill.handle(store, env({"type": "AudioPlayer.PlaybackStopped", "token": token,
                                                         "offsetInMilliseconds": 41 * 60000})))
run("musica nel frattempo", "PlaySongIntent", "albachiara")
run("riprendi il podcast", "ResumePodcastIntent")
run("il podcast (riprende)", "PlayPodcastIntent", "tintoria")
run("episodio precedente", "OlderEpisodeIntent")
run("catch-all ultima puntata", "PlaySongIntent", "l'ultima puntata di muschio selvaggio")
run("puntata con ospite", "PlayEpisodeIntent", "alessandro barbero")
run("catch-all lezione", "PlaySongIntent", "la puntata su napoleone")

print("\n--- loop e playlist personali ---")
out = run("in loop una canzone", "LoopPlayIntent", "albachiara di vasco rossi")
state = store.get("dev1")
tok = f"0:{state['queue'][0]['id']}:1"
show("  quasi finita -> la ripete", event("AudioPlayer.PlaybackNearlyFinished", tok))
run("stop loop", "StopLoopIntent")
show("  quasi finita -> radio", event("AudioPlayer.PlaybackNearlyFinished", tok))
run("in loop un album", "LoopPlayIntent", "l'album wow dei verdena")
state = store.get("dev1")
last = len(state["queue"]) - 1
show("  ultima traccia -> torna alla prima", event("AudioPlayer.PlaybackNearlyFinished",
                                                    f"{last}:{state['queue'][last]['id']}:2"))
run("in loop un artista", "LoopPlayIntent", "i successi dei verdena")
print("   modalità loop:", store.get("dev1")["loop"], "| radio:", store.get("dev1")["radio_seed"])
run("loop su questa canzone", "LoopCurrentIntent")
run("ripeti tutto", "LoopQueueIntent")
from jukebox import music  # noqa: E402

playlists = music.user_playlists()
if not playlists:
    print("   (JUKEBOX_YT_CHANNEL non impostato: salto le playlist personali)")
else:
    name = playlists[0]["title"]
    run("elenco playlist", "ListMyPlaylistsIntent")
    run(f"  risposta: {name}", "PlaySongIntent", name.lower(), attrs={"expect": "my_playlist"})
    run("la mia playlist", "MyPlaylistIntent", name.lower())
    run("catch-all mia playlist", "PlaySongIntent", f"la mia playlist {name.lower()}")
    run("i miei preferiti", "MyFavoritesIntent")
    run("in loop la mia playlist", "LoopPlayIntent", f"la mia playlist {name.lower()}")
