"""Test dell'interprete delle frasi: python3 -m pytest tests/ oppure python3 tests/test_parse.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jukebox.parse import Command, parse  # noqa: E402

CASES = [
    # (frase, hint, atteso)
    ("albachiara di vasco rossi", "song", Command("song", "albachiara di vasco rossi")),
    ("la canzone luna dall'album il suicidio dei samurai", "song",
     Command("song_in_album", "luna", album="il suicidio dei samurai")),
    ("luna dal disco il suicidio dei samurai", "song",
     Command("song_in_album", "luna", album="il suicidio dei samurai")),
    ("la terza traccia dell'album wow", "song", Command("album_track", "wow", number=3)),
    ("l'ultima canzone di wow", "song", Command("album_track", "wow", number=-1)),
    ("la traccia 3 dell'album wow", "song", Command("album_track", "wow", number=3)),
    ("la canzone numero tre di wow", "song", Command("album_track", "wow", number=3)),
    ("3 dell'album wow", "track", Command("album_track", "wow", number=3)),
    ("tre di wow", "track", Command("album_track", "wow", number=3)),
    ("numero 12 del disco requiem", "track", Command("album_track", "requiem", number=12)),
    ("la discografia di vasco rossi", "song", Command("discography", "vasco rossi")),
    ("tutta la discografia dei verdena", "song", Command("discography", "verdena")),
    ("tutti gli album di lucio dalla", "song", Command("discography", "lucio dalla")),
    ("vasco rossi", "discography", Command("discography", "vasco rossi")),
    ("l'ultimo album di vasco", "song", Command("album_latest", "vasco")),
    ("il nuovo disco dei verdena", "song", Command("album_latest", "verdena")),
    ("il primo album di de andré", "song", Command("album_first", "de andré")),
    ("l'album wow", "song", Command("album", "wow")),
    ("tutto il disco wow dei verdena", "song", Command("album", "wow dei verdena")),
    ("wow", "album", Command("album", "wow")),
    ("musica di lucio dalla", "song", Command("artist", "lucio dalla")),
    ("i successi dei pooh", "song", Command("artist", "pooh")),
    ("lucio dalla", "artist", Command("artist", "lucio dalla")),
    ("canzoni a caso di vasco", "song", Command("artist_shuffle", "vasco")),
    ("la radio di albachiara", "song", Command("radio", "albachiara")),
    ("musica simile ai verdena", "song", Command("radio", "verdena")),
    ("musica simile a verdena", "song", Command("radio", "verdena")),
    ("la classifica", "song", Command("charts")),
    ("le canzoni più ascoltate", "song", Command("charts")),
    ("la playlist musica per studiare", "song", Command("playlist", "musica per studiare")),
    ("musica rilassante", "song", Command("playlist", "musica rilassante")),
    ("musica per studiare", "song", Command("playlist", "musica per studiare")),
    ("le canzoni più ascoltate di vasco", "song", Command("artist", "vasco")),
    ("le più ascoltate di vasco rossi", "song", Command("artist", "vasco rossi")),
    ("le più famose dei pooh", "song", Command("artist", "pooh")),
    ("i brani più ascoltati di mina", "song", Command("artist", "mina")),
    ("le canzoni più belle di battisti", "song", Command("artist", "battisti")),
    ("le migliori di de andré", "song", Command("artist", "de andré")),
    ("i classici di celentano", "song", Command("artist", "celentano")),
    ("la top di ultimo", "song", Command("artist", "ultimo")),
    ("le canzoni più ascoltate", "song", Command("charts")),
    ("la mia playlist relax", "song", Command("my_playlist", "relax")),
    ("le canzoni della mia playlist musica da viaggio", "song", Command("my_playlist", "musica da viaggio")),
    ("i miei preferiti", "song", Command("my_playlist", "preferiti")),
    ("le mie canzoni preferite", "song", Command("my_playlist", "preferiti")),
    ("palestra", "my_playlist", Command("my_playlist", "palestra")),
    ("musica classica come sveglia", "song", Command("playlist", "musica classica", wake=True)),
    ("wow dei verdena come sveglia", "album", Command("album", "wow dei verdena", wake=True)),
    ("vasco rossi per svegliarmi", "artist", Command("artist", "vasco rossi", wake=True)),
    ("albachiara come sveglia", "song", Command("song", "albachiara", wake=True)),
    ("musica classica", "playlist", Command("playlist", "musica classica")),
    ("musica per svegliarmi", "song", Command("playlist", "musica", wake=True)),
    ("qualcosa come sveglia", "song", Command("playlist", "musica", wake=True)),
    ("la mia playlist relax al risveglio", "song", Command("my_playlist", "relax", wake=True)),
    ("l'ultimo episodio di tintoria", "song", Command("podcast_latest", "tintoria")),
    ("l'ultima puntata del podcast muschio selvaggio", "song", Command("podcast_latest", "muschio selvaggio")),
    ("il podcast tintoria", "song", Command("podcast", "tintoria")),
    ("podcast di barbero", "song", Command("podcast", "barbero")),
    ("la puntata con alessandro barbero", "song", Command("episode", "alessandro barbero")),
    ("l'episodio su napoleone", "song", Command("episode", "napoleone")),
    ("tintoria", "podcast", Command("podcast", "tintoria")),
    ("di tintoria", "podcast_latest", Command("podcast_latest", "tintoria")),
    ("con fedez", "episode", Command("episode", "fedez")),
]


def test_parse():
    failures = []
    for text, hint, expected in CASES:
        got = parse(text, hint)
        if got != expected:
            failures.append(f"{text!r} [{hint}] -> {got} (atteso {expected})")
    assert not failures, "\n" + "\n".join(failures)


if __name__ == "__main__":
    test_parse()
    print(f"ok, {len(CASES)} frasi")
