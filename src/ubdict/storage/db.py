"""SQLite connection helper for UbDict local stores."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ubdict.paths import user_data_dir

_DEFAULT_DB = user_data_dir() / "ubdict.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL,
    queried_at INTEGER NOT NULL,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_time ON history(queried_at DESC);

CREATE TABLE IF NOT EXISTS wordbook (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT UNIQUE NOT NULL,
    added_at INTEGER NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS cache (
    word TEXT PRIMARY KEY,
    translation_json TEXT NOT NULL,
    cached_at INTEGER NOT NULL
);
"""


def get_db(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or _DEFAULT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn
