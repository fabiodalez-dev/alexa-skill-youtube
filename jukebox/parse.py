"""Interpreta la frase libera catturata da Alexa e la trasforma in un comando.

Alexa ammette un solo slot AMAZON.SearchQuery per frase e non lo combina con
altri slot: "la terza traccia dell'album Wow" o "Luna dall'album Il suicidio dei
samurai" arrivano quindi come testo libero, e la struttura la ricaviamo qui.
"""
import re
from dataclasses import dataclass

NUMBERS = {
    "uno": 1, "un": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
    "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12,
    "tredici": 13, "quattordici": 14, "quindici": 15, "sedici": 16, "diciassette": 17,
    "diciotto": 18, "diciannove": 19, "venti": 20, "ventuno": 21, "ventidue": 22,
    "ventitre": 23, "ventitré": 23, "ventiquattro": 24, "venticinque": 25, "trenta": 30,
}
ORDINALS = {
    "prim": 1, "second": 2, "terz": 3, "quart": 4, "quint": 5, "sest": 6, "settim": 7,
    "ottav": 8, "non": 9, "decim": 10, "undicesim": 11, "dodicesim": 12, "tredicesim": 13,
    "quattordicesim": 14, "quindicesim": 15, "sedicesim": 16, "diciassettesim": 17,
    "diciottesim": 18, "diciannovesim": 19, "ventesim": 20, "ultim": -1,
}
ORDINAL_RE = "|".join(sorted(ORDINALS, key=len, reverse=True))
# "musica di X", "le più ascoltate di X", "i classici di X"...
_SONGS = r"(?:(?:le )?canzoni|(?:i )?brani|(?:i )?pezzi|(?:le )?hit|(?:i )?successi)"
ARTIST_WORDS = "|".join([
    r"musica", r"qualcosa", r"un po'", _SONGS, r"(?:il )?meglio", r"(?:i )?grandi successi",
    r"(?:i )?più grandi successi", r"(?:i )?classici", r"(?:la |le )?top",
    rf"(?:le |i )?(?:{_SONGS} )?(?:più|migliori) ?(?:famos[ei]|ascoltat[ei]|bell[ei]|popolari|conosciut[ei]|note|noti|celebri|suonat[ei])?",
    rf"(?:le |i )?migliori(?: {_SONGS})?",
])
PREP = r"(?:di|dei|degli|del|della|delle|dello|de|da|dal|dalla|dai)"
ALBUM_WORD = r"(?:album|disco|cd|lp|ellepì)"
TRACK_WORD = r"(?:traccia|tracce|canzone|brano|pezzo)"
FROM_ALBUM = (r"(?:dall'|dall |dal |nell'|nel |dell'|del |contenut[ao] nell'|che sta nell'|"
              r"che c'è nell'|tratt[ao] dall'|presa dall'|preso dal )\s*" + ALBUM_WORD)


@dataclass
class Command:
    kind: str                # song, song_in_album, album, album_track, album_latest,
                             # album_first, artist, artist_shuffle, discography, radio,
                             # playlist, my_playlist, charts, podcast, podcast_latest, episode
    query: str = ""          # testo principale (brano, album, artista, playlist)
    album: str = ""          # per song_in_album
    number: int = 0          # per album_track (1 = prima, -1 = ultima)
    wake: bool = False       # "... come sveglia": per generi e atmosfere si cerca la versione mattutina


def _clean(text: str) -> str:
    text = (text or "").lower().strip()
    text = text.replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,!?")


def _number(word: str) -> int | None:
    word = word.strip()
    if word.isdigit():
        return int(word)
    if word in NUMBERS:
        return NUMBERS[word]
    m = re.fullmatch(rf"({ORDINAL_RE})[oaie]?", word)
    if m:
        return ORDINALS[m.group(1)]
    return None


def _strip_lead(text: str, words: str) -> str:
    return re.sub(rf"^(?:{words})\s+", "", text).strip()


# Code da sveglia: "Wow dei Verdena come sveglia", "musica classica per svegliarmi".
# Arrivano dalle routine di Alexa programmate all'orario della sveglia.
WAKE_RE = re.compile(r"\s+(?:come|per la|da|per) sveglia$|\s+per (?:svegliarmi|svegliarci|svegliarsi|il risveglio)$"
                     r"|\s+al risveglio$|\s+(?:di|la) mattina$|\s+stamattina$")


def parse(text: str, hint: str = "song") -> Command:
    """`hint` viene dall'intent che Alexa ha scelto; la frase può smentirlo."""
    t = _clean(text)
    m = WAKE_RE.search(t)
    rest = t[:m.start()] if m else t
    if m and re.fullmatch(r"(?:(?:della |un po' di |una |delle |qualche )?(?:musica|canzon[ei]|brani|qualcosa))?", rest):
        # "musica per svegliarmi", "qualcosa come sveglia": nessun titolo, solo l'intenzione
        return Command("playlist", "musica", wake=True)
    cmd = _parse(rest, hint)
    cmd.wake = bool(m)
    return cmd


def _parse(t: str, hint: str) -> Command:

    # --- forme esplicite dall'intent (il prefisso della frase è già stato tolto) ---
    if hint == "discography":
        return Command("discography", _strip_lead(t, PREP))
    if hint == "album_latest":
        return Command("album_latest", _strip_lead(t, PREP))
    if hint == "album_first":
        return Command("album_first", _strip_lead(t, PREP))
    if hint == "artist_shuffle":
        return Command("artist_shuffle", _strip_lead(t, PREP))
    if hint == "radio":
        return Command("radio", _strip_lead(t, PREP + r"|basata su|simile a|simili a"))
    if hint == "playlist":
        return Command("playlist", _strip_lead(t, PREP + r"|per"))
    if hint == "mood":
        return Command("playlist", f"musica per {_strip_lead(t, 'per')}")
    if hint == "my_playlist":
        return Command("my_playlist", _strip_lead(t, r"la mia playlist|la playlist|playlist|mia|la"))
    if hint == "podcast":
        return Command("podcast", _strip_lead(t, PREP + r"|il podcast|podcast"))
    if hint == "podcast_latest":
        return Command("podcast_latest", _strip_lead(t, PREP + r"|il podcast|podcast"))
    if hint == "episode":
        return Command("episode", _strip_lead(t, r"con|su|di|del|della|dove|in cui|sul|sulla"))
    if hint == "track":
        # "3 dell'album wow", "tre di wow", "numero 3 di wow"
        t = _strip_lead(t, "numero|n")
        m = re.match(rf"^(\S+)\s+(?:{PREP}\s+|dell'|nell'|{FROM_ALBUM}\s+)?(?:{ALBUM_WORD}\s+)?(.+)$", t)
        if m and _number(m.group(1)) is not None:
            return Command("album_track", m.group(2).strip(), number=_number(m.group(1)))
        return Command("album", t)

    # --- riconoscimento dalla frase completa ---
    # playlist personali: "la mia playlist Relax", "i miei preferiti"
    m = re.match(r"^(?:(?:le canzoni|i brani|la musica) (?:della|dalla) |la |una )?"
                 r"(?:mia playlist|playlist mia|mia lista|mia raccolta) (.+)$", t)
    if m:
        return Command("my_playlist", m.group(1))
    if re.fullmatch(r"(?:i miei |le mie |la mia )?(?:preferiti|preferite|canzoni preferite|"
                    r"brani preferiti|musica preferita)", t):
        return Command("my_playlist", "preferiti")
    # podcast prima di tutto il resto: "l'ultima puntata di Tintoria", "il podcast Muschio Selvaggio"
    m = re.match(rf"^(?:l'|il |la )?(?:ultim[oa]|nuov[oa]|più recente) (?:episodio|puntata|podcast)"
                 rf"(?: del podcast)? {PREP} (.+)$", t)
    if m:
        return Command("podcast_latest", _strip_lead(m.group(1), r"podcast"))
    m = re.match(r"^(?:il |un )?podcast (?:di |del |della |dei )?(.+)$", t)
    if m:
        return Command("podcast", m.group(1))
    m = re.match(r"^(?:l'|la |un'|una )?(?:episodio|puntata|intervista) "
                 r"(?:con|su|sul|sulla|sui|dove parla(?:no)? di|in cui parla(?:no)? di|a) (.+)$", t)
    if m:
        return Command("episode", m.group(1))

    m = re.match(rf"^(?:tutta |l'intera )?(?:la )?discografia(?: completa)? {PREP} (.+)$", t) or \
        re.match(rf"^tutti (?:gli album|i dischi) {PREP} (.+)$", t)
    if m:
        return Command("discography", m.group(1))

    m = re.match(rf"^(?:l'|il |lo )?(?:ultimo|nuovo|più recente) {ALBUM_WORD}(?: più recente)? {PREP} (.+)$", t) or \
        re.match(rf"^(?:l'|il )?{ALBUM_WORD} più recente {PREP} (.+)$", t)
    if m:
        return Command("album_latest", m.group(1))
    m = re.match(rf"^(?:il )?primo {ALBUM_WORD} {PREP} (.+)$", t) or \
        re.match(rf"^(?:l')?album di debutto {PREP} (.+)$", t)
    if m:
        return Command("album_first", m.group(1))

    # "la terza traccia dell'album wow", "l'ultima canzone di wow"
    m = re.match(rf"^(?:la |il |l')?({ORDINAL_RE})[oaie]? {TRACK_WORD} (?:{FROM_ALBUM} |{PREP} |dell'{ALBUM_WORD} )(.+)$", t)
    if m:
        return Command("album_track", m.group(2), number=ORDINALS[m.group(1)])
    # "la traccia 3 dell'album wow", "la canzone numero tre di wow"
    m = re.match(rf"^(?:la |il )?{TRACK_WORD} (?:numero |n )?(\S+) (?:{FROM_ALBUM} |{PREP} |dell'{ALBUM_WORD} )(.+)$", t)
    if m and _number(m.group(1)) is not None:
        return Command("album_track", m.group(2), number=_number(m.group(1)))

    m = re.match(r"^(?:la |una )?radio (?:di |dei |del |della |basata su |ispirata a )?(.+)$", t) or \
        re.match(r"^(?:musica|canzoni|qualcosa) (?:di )?simil[ei] (?:a|ad|ai|agli|al|allo|alla|alle|a quell[ao] d[ei]) (.+)$", t)
    if m:
        return Command("radio", m.group(1))

    # prima della classifica: "le più ascoltate di Vasco" è un artista, non la top italiana
    m = re.match(rf"^(?:la |della )?(?:{ARTIST_WORDS}) {PREP} (.+)$", t)
    if m:
        return Command("artist", m.group(1))

    if re.search(r"classific|più ascoltat|del momento|top (?:venti|cinquanta|cento|\d+)|tendenz", t):
        return Command("charts")

    m = re.match(r"^(?:la |una )?playlist (?:di |per )?(.+)$", t)
    if m:
        return Command("playlist", m.group(1))

    m = re.match(rf"^(?:l'|il |lo |tutto l'|tutto il |l'intero |l'intero )?{ALBUM_WORD}(?: intero| completo)? (.+)$", t)
    if m:
        return Command("album", m.group(1))

    m = re.match(rf"^(?:(?:le |delle )?canzoni|(?:la )?musica|(?:i )?brani|(?:i )?pezzi) a caso {PREP} (.+)$", t) or \
        re.match(rf"^(?:un )?mix {PREP} (.+)$", t)
    if m:
        return Command("artist_shuffle", m.group(1))

    # generi e atmosfere: "musica rilassante", "musica per studiare"
    m = re.match(r"^(?:della |un po' di )?musica (?!di |dei |del |della )(.+)$", t)
    if m:
        return Command("playlist", f"musica {m.group(1)}")

    # --- brani, eventualmente "dall'album ..." ---
    song = _strip_lead(t, r"la canzone|il brano|il pezzo|il singolo|la traccia")
    m = re.match(rf"^(.+?) {FROM_ALBUM} (.+)$", song)
    if m:
        return Command("song_in_album", m.group(1), album=m.group(2))
    if hint == "album":
        return Command("album", song)
    if hint == "artist":
        return Command("artist", _strip_lead(song, PREP))
    return Command("song", song)
