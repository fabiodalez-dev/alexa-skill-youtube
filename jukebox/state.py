"""Coda di riproduzione per dispositivo e posizione di ascolto dei podcast, in SQLite."""
import json
import sqlite3
import threading
import time

DEFAULT = {"queue": [], "index": 0, "offset": 0, "radio_seed": None, "loop": False,
           "upcoming_albums": [], "unshuffled": None}


class Store:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS devices ("
                "device_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL NOT NULL)"
            )
            # Una riga per episodio: dove eri arrivato, anche a distanza di giorni.
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS progress ("
                "video_id TEXT PRIMARY KEY, podcast_id TEXT, track TEXT NOT NULL, "
                "offset_ms INTEGER NOT NULL, finished INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL)"
            )
            self._db.commit()

    def get(self, device_id: str) -> dict:
        with self._lock:
            row = self._db.execute(
                "SELECT data FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
        state = dict(DEFAULT)
        if row:
            state.update(json.loads(row[0]))
        return state

    def put(self, device_id: str, state: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO devices (device_id, data, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(device_id) DO UPDATE SET data = excluded.data, updated = excluded.updated",
                (device_id, json.dumps(state), time.time()),
            )
            self._db.commit()

    # --- podcast ---------------------------------------------------------

    def save_progress(self, track: dict, offset_ms: int, finished: bool = False) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO progress (video_id, podcast_id, track, offset_ms, finished, updated) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(video_id) DO UPDATE SET "
                "offset_ms = excluded.offset_ms, finished = excluded.finished, updated = excluded.updated",
                (track["id"], track.get("podcast_id"), json.dumps(track), int(offset_ms),
                 int(finished), time.time()),
            )
            self._db.commit()

    def progress(self, video_id: str) -> tuple[int, bool] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT offset_ms, finished FROM progress WHERE video_id = ?", (video_id,)
            ).fetchone()
        return (row[0], bool(row[1])) if row else None

    def last_unfinished(self, podcast_id: str | None = None) -> tuple[dict, int] | None:
        """L'episodio lasciato a metà più di recente (di un podcast, o di tutti)."""
        with self._lock:
            row = self._db.execute(
                "SELECT track, offset_ms FROM progress WHERE finished = 0 AND offset_ms > 0 "
                "AND (? IS NULL OR podcast_id = ?) ORDER BY updated DESC LIMIT 1",
                (podcast_id, podcast_id),
            ).fetchone()
        return (json.loads(row[0]), row[1]) if row else None
