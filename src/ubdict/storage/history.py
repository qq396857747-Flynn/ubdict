"""Query history store."""
from __future__ import annotations

import sqlite3
import time

from loguru import logger


class HistoryStore:
    def __init__(self, conn: sqlite3.Connection, max_rows: int = 100) -> None:
        self._conn = conn
        self._max = max_rows

    def add(self, word: str, source: str = "") -> None:
        now = int(time.time())
        try:
            self._conn.execute(
                "INSERT INTO history(word, queried_at, source) VALUES (?, ?, ?)",
                (word, now, source),
            )
            self._conn.commit()
            # Trim old rows beyond 10x max to keep table bounded.
            self._conn.execute(
                "DELETE FROM history WHERE id NOT IN "
                "(SELECT id FROM history ORDER BY queried_at DESC LIMIT ?)",
                (self._max * 10,),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"HistoryStore.add failed: {e}")

    def recent(self, limit: int | None = None) -> list[dict]:
        n = limit or self._max
        try:
            rows = self._conn.execute(
                "SELECT word, queried_at, source FROM history "
                "ORDER BY queried_at DESC LIMIT ?",
                (n,),
            ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(r) for r in rows]
