"""Genera il modello di interazione it-IT combinando verbi e forme di richiesta.

Uso: python3 tools/build_model.py  ->  skill-package/interactionModels/custom/it-IT.json

Vincoli di Alexa tenuti presenti:
- un solo slot AMAZON.SearchQuery per frase, mai da solo (serve un verbo davanti);
- la stessa frase non può stare in due intent;
- niente cifre nelle frasi di esempio.
La struttura fine (traccia N, "dall'album", discografia...) la ricava jukebox/parse.py
dal testo libero, quindi qui basta far arrivare la frase all'intent giusto.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "skill-package/interactionModels/custom/it-IT.json"

# Tutti i modi di chiedere: imperativo ("apri Jukebox" + "metti ..."), infinito
# ("chiedi a Jukebox di mettere ..."), prima plurale, richieste cortesi.
VERBS_ALL = [
    "metti", "mettere", "mettiamo", "mettimi", "mi metti", "puoi mettere", "potresti mettere",
    "riproduci", "riprodurre", "riproduciamo",
    "suona", "suonare", "suoniamo",
    "fammi sentire", "farmi sentire", "mi fai sentire", "sentiamo", "voglio sentire", "vorrei sentire",
    "fammi ascoltare", "farmi ascoltare", "mi fai ascoltare", "ascoltiamo", "voglio ascoltare",
    "vorrei ascoltare",
    "fai partire", "far partire", "avvia", "avviare", "manda", "mandare", "spara", "sparare",
    "cerca", "cercare", "trova", "trovare", "play",
]
# Sottoinsieme usato per le forme con molte varianti, per non esplodere di numero.
VERBS_MAIN = [
    "metti", "mettere", "mettiamo", "riproduci", "riprodurre", "fammi sentire", "farmi sentire",
    "fammi ascoltare", "farmi ascoltare", "voglio sentire", "voglio ascoltare", "suona", "suonare",
]
PREPS = ["di", "dei", "degli", "del", "della", "delle"]
PREPS_SHORT = ["di", "dei", "del", "della"]


def expand(verbs, objects, preps=None):
    out = []
    for v in verbs:
        for o in objects:
            fill = {"q": "{query}", "d": "{duration}", "minute": "{minute}"}
            if "{p}" in o:
                out += [f"{v} {o.format(p=p, **fill)}".strip() for p in (preps or PREPS)]
            else:
                out.append(f"{v} {o.format(**fill)}".strip())
    return out


SLOT = [{"name": "query", "type": "AMAZON.SearchQuery"}]

INTENTS = {
    # catch-all: qualsiasi frase dopo il verbo; l'interprete riconosce anche
    # "la terza traccia di Wow", "Luna dall'album ...", "musica rilassante", "la classifica".
    "PlaySongIntent": (SLOT, expand(VERBS_ALL, [
        "{q}", "la canzone {q}", "il brano {q}", "il pezzo {q}", "il singolo {q}",
        "la canzone che fa {q}", "quella canzone che fa {q}", "la canzone che dice {q}",
    ])),
    "PlayAlbumIntent": (SLOT, expand(VERBS_ALL, [
        "l'album {q}", "il disco {q}", "tutto l'album {q}", "tutto il disco {q}",
        "l'intero album {q}", "l'album completo {q}", "il cd {q}",
    ])),
    "PlayAlbumTrackIntent": (SLOT, expand(VERBS_ALL, [
        "la traccia {q}", "la traccia numero {q}", "il brano numero {q}",
        "la canzone numero {q}", "il pezzo numero {q}",
    ])),
    "PlayArtistIntent": (SLOT, expand(VERBS_MAIN, [
        "musica {p} {q}", "qualcosa {p} {q}", "le canzoni {p} {q}", "canzoni {p} {q}",
        "i brani {p} {q}", "i successi {p} {q}", "le hit {p} {q}", "il meglio {p} {q}",
        "le migliori canzoni {p} {q}", "i pezzi {p} {q}", "i pezzi migliori {p} {q}",
        "le canzoni più famose {p} {q}", "i grandi successi {p} {q}", "un po' {p} {q}",
        "le più famose {p} {q}", "le più ascoltate {p} {q}", "le canzoni più ascoltate {p} {q}",
        "i brani più ascoltati {p} {q}", "i pezzi più famosi {p} {q}", "le più belle {p} {q}",
        "le canzoni più belle {p} {q}", "le migliori {p} {q}", "i più grandi successi {p} {q}",
        "i classici {p} {q}", "la top {p} {q}", "le più popolari {p} {q}", "le più conosciute {p} {q}",
    ]) + expand([v for v in VERBS_ALL if v not in VERBS_MAIN], [
        "musica di {q}", "qualcosa di {q}", "le canzoni di {q}", "i successi di {q}",
    ])),
    "PlayArtistShuffleIntent": (SLOT, expand(VERBS_MAIN, [
        "canzoni a caso {p} {q}", "musica a caso {p} {q}", "brani a caso {p} {q}",
        "un mix {p} {q}", "le canzoni {p} {q} a caso", "le canzoni {p} {q} in ordine casuale",
        "musica {p} {q} in ordine sparso",
    ], PREPS_SHORT)),
    "PlayDiscographyIntent": (SLOT, expand(VERBS_MAIN, [
        "la discografia {p} {q}", "tutta la discografia {p} {q}", "la discografia completa {p} {q}",
        "tutti gli album {p} {q}", "tutti i dischi {p} {q}", "l'intera discografia {p} {q}",
    ])),
    "PlayLatestAlbumIntent": (SLOT, expand(VERBS_MAIN, [
        "l'ultimo album {p} {q}", "l'ultimo disco {p} {q}", "il nuovo album {p} {q}",
        "il nuovo disco {p} {q}", "l'album più recente {p} {q}", "il disco più recente {p} {q}",
    ], PREPS_SHORT)),
    "PlayFirstAlbumIntent": (SLOT, expand(VERBS_MAIN, [
        "il primo album {p} {q}", "il primo disco {p} {q}", "l'album di debutto {p} {q}",
    ], PREPS_SHORT)),
    "PlayRadioIntent": (SLOT, expand(VERBS_MAIN, [
        "la radio {p} {q}", "una radio {p} {q}",
    ], PREPS_SHORT) + expand(VERBS_MAIN, [
        "la radio basata su {q}", "una radio basata su {q}", "la radio del brano {q}",
        "la radio della canzone {q}", "musica simile a {q}", "canzoni simili a {q}",
        "qualcosa di simile a {q}", "musica tipo {q}", "canzoni tipo {q}", "qualcosa tipo {q}",
        "musica come {q}", "qualcosa che somiglia a {q}",
    ])),
    "PlayPlaylistIntent": (SLOT, expand(VERBS_MAIN, [
        "la playlist {q}", "una playlist {q}", "la playlist di {q}", "una playlist di {q}",
        "la compilation {q}", "una compilation di {q}",
    ])),
    "PlayMoodIntent": (SLOT, expand(VERBS_MAIN, [
        "musica per {q}", "della musica per {q}", "canzoni per {q}", "qualcosa per {q}",
        "una playlist per {q}", "musica adatta per {q}", "qualcosa di adatto per {q}",
    ])),
    "PlayChartsIntent": ([], expand(VERBS_MAIN, [
        "la classifica", "la classifica italiana", "la classifica di youtube",
        "le canzoni più ascoltate", "le canzoni più ascoltate in italia", "le canzoni del momento",
        "i successi del momento", "le hit del momento", "la top venti", "la top cinquanta",
        "la top cento", "i brani di tendenza", "le canzoni di tendenza", "le novità",
    ])),
    # --- podcast ---
    "PlayPodcastIntent": (SLOT, expand(VERBS_ALL, [
        "il podcast {q}", "un podcast {q}", "il podcast di {q}", "il podcast del {q}",
        "il podcast della {q}", "il podcast dei {q}", "i podcast di {q}",
    ])),
    "PlayLatestEpisodeIntent": (SLOT, expand(VERBS_MAIN, [
        "l'ultimo episodio {p} {q}", "l'ultima puntata {p} {q}", "il nuovo episodio {p} {q}",
        "la nuova puntata {p} {q}", "l'episodio più recente {p} {q}", "la puntata più recente {p} {q}",
        "la puntata di oggi {p} {q}", "l'episodio di oggi {p} {q}", "l'ultimo podcast {p} {q}",
        "l'ultima puntata del podcast {q}", "l'ultimo episodio del podcast {q}",
    ], PREPS_SHORT)),
    "PlayEpisodeIntent": (SLOT, expand(VERBS_MAIN, [
        "l'episodio con {q}", "la puntata con {q}", "l'episodio su {q}", "la puntata su {q}",
        "l'episodio sul {q}", "la puntata sul {q}", "l'episodio sulla {q}", "la puntata sulla {q}",
        "l'intervista a {q}", "l'intervista con {q}", "il podcast con {q}", "un podcast su {q}",
        "un podcast sul {q}", "un podcast sulla {q}", "l'episodio in cui parla {q}",
        "la puntata in cui parlano di {q}", "la lezione su {q}", "la lezione di {q}",
        "una lezione su {q}",
    ])),
    "ResumePodcastIntent": ([], expand(["", "riprendi", "riprendere", "continua", "continuare",
                                        "fammi continuare", "fammi riprendere", "rimetti", "rimettere"], [
        "il podcast", "l'episodio", "la puntata", "il podcast di prima", "il podcast di ieri",
        "l'ultimo podcast", "il podcast che stavo ascoltando", "la puntata che stavo ascoltando",
        "l'episodio che stavo ascoltando", "da dove ero rimasto", "dove ero rimasto",
        "da dove mi ero fermato", "dove mi ero fermato", "l'ascolto",
    ]) + ["dove ero rimasto", "da dove ero rimasto", "dove eravamo rimasti",
          "riprendi da dove ero rimasto", "riprendere da dove ero rimasto",
          "continua da dove ero rimasto", "continuare da dove ero rimasto"]),
    "OlderEpisodeIntent": ([], expand(["metti", "mettere", "passa", "passare", "vai",
                                      "andare", "fammi sentire", "farmi sentire"], [
        "all'episodio precedente", "alla puntata precedente", "l'episodio precedente",
        "la puntata precedente", "all'episodio prima", "alla puntata prima",
        "l'episodio prima", "la puntata prima", "l'episodio più vecchio",
    ])),
    "NewerEpisodeIntent": ([], expand(["metti", "mettere", "passa", "passare", "vai",
                                          "andare", "fammi sentire", "farmi sentire", "torna", "tornare"], [
        "all'episodio successivo", "alla puntata successiva", "l'episodio successivo",
        "la puntata successiva", "all'episodio dopo", "alla puntata dopo",
        "l'episodio dopo", "la puntata dopo", "all'episodio più nuovo", "l'episodio più nuovo",
    ])),
    "SeekForwardIntent": ([{"name": "duration", "type": "AMAZON.DURATION"}], expand([
        "vai", "andare", "manda", "mandare", "porta", "portare", "spostati", "spostarti",
        "salta", "saltare", "fai", "fare"], [
        "avanti di {d}", "in avanti di {d}", "avanti {d}",
    ]) + [f"{v} {d}" for v in ["salta", "saltare", "avanza di", "avanzare di", "skippa", "skippare"]
          for d in ["{d}"]] + ["avanti di {d}", "più avanti di {d}", "{d} avanti", "{d} più avanti",
                               "vai {d} avanti", "andare {d} avanti", "vai {d} più avanti"]),
    "SeekBackIntent": ([{"name": "duration", "type": "AMAZON.DURATION"}], expand([
        "torna", "tornare", "vai", "andare", "manda", "mandare", "porta", "portare",
        "spostati", "spostarti", "riavvolgi", "riavvolgere"], [
        "indietro di {d}", "indietro {d}",
    ]) + ["indietro di {d}", "{d} indietro", "vai {d} indietro", "tornare {d} indietro",
          "torna {d} indietro", "riascolta gli ultimi {d}", "riascoltare gli ultimi {d}",
          "fammi riascoltare gli ultimi {d}", "farmi riascoltare gli ultimi {d}",
          "riavvolgi di {d}", "riavvolgere di {d}"]),
    "SeekToIntent": ([{"name": "minute", "type": "AMAZON.NUMBER"}], [
        f"{v} {o}" for v in ["vai", "andare", "salta", "saltare", "porta", "portare", "riprendi",
                             "riprendere", "fai partire", "far partire", "metti", "mettere"]
        for o in ["al minuto {minute}", "dal minuto {minute}", "al minuto numero {minute}"]
    ] + ["minuto {minute}", "dal minuto {minute}", "al minuto {minute}"]),
    # --- loop ---
    "LoopPlayIntent": (SLOT, expand(VERBS_ALL, [
        "in loop {q}", "{q} in loop", "a ripetizione {q}", "{q} a ripetizione", "in repeat {q}",
        "{q} in repeat", "{q} all'infinito", "in loop continuo {q}", "{q} in loop continuo",
    ]) + [f"{v} {{query}}" for v in ["loopa", "loopare", "ripeti all'infinito", "ripetere all'infinito",
                                      "ripeti in loop", "ripetere in loop", "manda in loop", "mandare in loop"]]),
    "LoopCurrentIntent": ([], expand(["metti", "mettere", "manda", "mandare", "tieni", "tenere", "lascia", "lasciare"], [
        "in loop questa canzone", "questa canzone in loop", "in loop questo brano", "questo brano in loop",
        "in loop questo pezzo", "questo pezzo in loop", "in repeat questa canzone", "questa canzone in repeat",
        "questa canzone a ripetizione", "questo brano a ripetizione", "in loop", "in repeat", "a ripetizione",
    ]) + ["ripeti questa canzone", "ripetere questa canzone", "ripeti questo brano", "ripetere questo brano",
          "ripeti questa canzone all'infinito", "ripetere questa canzone all'infinito",
          "ripeti questo pezzo", "loop su questa canzone", "loop questa canzone", "loop",
          "fai il loop di questa canzone", "fare il loop di questa canzone", "ripeti sempre questa"]),
    "LoopQueueIntent": ([], expand(["metti", "mettere", "manda", "mandare", "tieni", "tenere"], [
        "in loop tutto l'album", "in loop l'album", "l'album in loop", "tutto l'album in loop",
        "in loop tutto", "tutto in loop", "in loop la coda", "la coda in loop", "in loop la playlist",
        "la playlist in loop", "in loop tutta la playlist", "in loop questo album", "questo album in loop",
        "in loop queste canzoni", "in loop questo artista",
    ]) + ["ripeti tutto l'album", "ripetere tutto l'album", "ripeti l'album", "ripetere l'album",
          "ripeti la playlist", "ripetere la playlist", "ripeti tutta la coda", "ripetere tutta la coda",
          "ripeti tutto", "ripetere tutto", "ripeti questo album", "ripetere questo album"]),
    "StopLoopIntent": ([], [f"{v} {o}" for v in ["togli", "togliere", "disattiva", "disattivare",
                                                   "ferma", "fermare", "leva", "levare", "spegni", "spegnere"]
                             for o in ["il loop", "la ripetizione", "il repeat"]]
                     + ["basta loop", "basta ripetere", "smetti di ripetere", "smettere di ripetere",
                        "niente loop", "stop loop", "senza loop", "non ripetere più", "non ripetere"]),
    # --- playlist personali (profilo YouTube) ---
    "MyPlaylistIntent": (SLOT, expand(VERBS_ALL, [
        "la mia playlist {q}", "la playlist mia {q}", "una mia playlist {q}", "la mia lista {q}",
        "le canzoni della mia playlist {q}", "la mia raccolta {q}", "dalla mia playlist {q}",
    ])),
    "ListMyPlaylistsIntent": ([], [
        "quali playlist ho", "che playlist ho", "quali sono le mie playlist", "elenca le mie playlist",
        "elencare le mie playlist", "dimmi le mie playlist", "dirmi le mie playlist", "le mie playlist",
        "leggi le mie playlist", "leggere le mie playlist", "che playlist ho salvato", "quante playlist ho",
        "dimmi quali playlist ho", "dirmi quali playlist ho", "che playlist ci sono", "quali playlist ci sono",
    ]),
    "MyFavoritesIntent": ([], expand(VERBS_MAIN, [
        "i miei preferiti", "le mie preferite", "le mie canzoni preferite", "i miei brani preferiti",
        "i preferiti", "la mia musica preferita", "le canzoni che mi piacciono", "i brani che mi piacciono",
    ])),
    "AddToQueueIntent": (SLOT, [
        "aggiungi {query} alla coda", "aggiungi alla coda {query}", "aggiungere {query} alla coda",
        "aggiungere alla coda {query}", "metti in coda {query}", "mettere in coda {query}",
        "mettimi in coda {query}", "accoda {query}", "accodare {query}", "aggiungi {query}",
        "aggiungere {query}", "aggiungi {query} dopo questa", "dopo questa metti {query}",
        "dopo questa canzone metti {query}", "dopo metti {query}", "poi metti {query}",
        "subito dopo metti {query}", "dopo fammi sentire {query}", "dopo questa fammi sentire {query}",
        "prenota {query}", "prenotare {query}", "in coda metti {query}",
    ]),
    "PlayAlbumOfCurrentIntent": ([], expand(VERBS_MAIN, [
        "l'album di questa canzone", "il disco di questa canzone", "tutto l'album di questa canzone",
        "l'album da cui viene questa canzone", "l'album di questo brano", "il disco di questo brano",
        "tutto l'album", "l'album intero", "il resto dell'album", "tutto il disco",
        "l'album completo", "tutto l'album di questo pezzo",
    ])),
    "PlayArtistOfCurrentIntent": ([], expand(VERBS_MAIN, [
        "altre canzoni di questo artista", "altro di questo artista", "altre canzoni di questo cantante",
        "altre canzoni di questa cantante", "altre canzoni di questo gruppo", "altre canzoni di questa band",
        "altro di questo gruppo", "altro di questa band", "i successi di questo artista",
        "altri pezzi di questo artista", "altre sue canzoni", "altro di lui", "altro di lei",
        "altro di loro", "altra musica di questo artista",
    ])),
    "NowPlayingIntent": ([], [
        "cosa sta suonando", "cosa stai suonando", "cosa suona", "che canzone è", "che canzone è questa",
        "che brano è", "che pezzo è", "come si chiama questa canzone", "come si chiama questo pezzo",
        "come si chiama", "chi canta", "chi canta questa canzone", "chi è l'artista", "di chi è",
        "di chi è questa canzone", "di che album è", "da che album è", "che album è",
        "in che disco è", "da quale album viene", "cosa sto ascoltando", "cosa stiamo ascoltando",
        "dimmi cosa sta suonando", "dimmi che canzone è", "dimmi chi canta",
        "dirmi cosa sta suonando", "dirmi che canzone è", "dirmi chi canta", "dirmi di che album è",
        "il titolo", "dimmi il titolo", "dirmi il titolo",
    ]),
    "AMAZON.YesIntent": ([], [
        "sì quella", "sì proprio quella", "esatto", "esattamente", "proprio quella", "quella",
        "giusto", "va bene", "perfetto", "confermo", "sì grazie", "certo", "sì metti quella",
    ]),
    "AMAZON.NoIntent": ([], [
        "no un'altra", "no non quella", "non quella", "sbagliato", "hai sbagliato", "no quella no",
        "no è un'altra", "no la prossima", "un'altra", "no grazie", "no dai",
    ]),
}

BUILTINS = [
    "AMAZON.HelpIntent", "AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.PauseIntent",
    "AMAZON.ResumeIntent", "AMAZON.NextIntent", "AMAZON.PreviousIntent", "AMAZON.StartOverIntent",
    "AMAZON.LoopOnIntent", "AMAZON.LoopOffIntent", "AMAZON.ShuffleOnIntent",
    "AMAZON.ShuffleOffIntent", "AMAZON.RepeatIntent", "AMAZON.FallbackIntent",
    "AMAZON.NavigateHomeIntent",
]


def build():
    seen = {}
    intents = []
    for name, (slots, samples) in INTENTS.items():
        unique = []
        for s in samples:
            s = " ".join(s.replace("{d}", "{duration}").split())
            if s in seen:
                if seen[s] != name:
                    raise SystemExit(f"frase duplicata fra {seen[s]} e {name}: {s!r}")
                continue
            if any(ch.isdigit() for ch in s) or len(s) > 200:
                raise SystemExit(f"frase non valida: {s!r}")
            seen[s] = name
            unique.append(s)
        intents.append({"name": name, "slots": slots, "samples": unique})
    intents += [{"name": n, "samples": []} for n in BUILTINS]
    model = {"interactionModel": {"languageModel": {
        "invocationName": "jukebox", "intents": intents, "types": []}}}
    OUT.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
    for i in intents:
        if i["samples"]:
            print(f"{i['name']:28} {len(i['samples']):5}")
    print(f"{'TOTALE':28} {len(seen):5}  ->  {OUT}")


if __name__ == "__main__":
    build()
