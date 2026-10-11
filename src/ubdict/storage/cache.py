"""Translation result cache (LRU via SQLite)."""
from __future__ import annotations

import sqlite3
import time
from collections import OrderedDict

from loguru import logger
from pydantic import ValidationError

from ubdict.core.models import Translation


class CacheStore:
    """In-memory LRU cache backed by SQLite for persistence.

    Keeps the most recent `max_size` entries in memory for fast lookup;
    older entries remain in SQLite but are not reloaded. The SQLite table
    is periodically trimmed so it does not grow without bound.
    """

    _TRIM_INTERVAL = 50

    def __init__(self, conn: sqlite3.Connection, max_size: int = 1000) -> None:
        self._conn = conn
        self._max = max(1, max_size)
        self._mem: OrderedDict[str, Translation] = OrderedDict()
        self._write_count = 0

    def resize(self, max_size: int) -> None:
        """Update the LRU capacity and trim both memory and the backing table."""
        self._max = max(1, max_size)
        while len(self._mem) > self._max:
            self._mem.popitem(last=False)
        self._trim_db()

    def get(self, word: str) -> Translation | None:
        if word in self._mem:
            self._mem.move_to_end(word)
            return self._mem[word]
        try:
            row = self._conn.execute(
                "SELECT translation_json FROM cache WHERE word = ?", (word,)
            ).fetchone()
        except sqlite3.Error as e:
            logger.debug(f"CacheStore.get failed for {word!r}: {e}")
            return None
        if row:
            try:
                t = Translation.model_validate_json(row["translation_json"])
            except (ValidationError, ValueError) as e:
                logger.warning(f"Corrupt cache row for {word!r}: {e}; evicting")
                try:
                    self._conn.execute("DELETE FROM cache WHERE word = ?", (word,))
                    self._conn.commit()
                except sqlite3.Error:
                    pass
                return None
            self._set_mem(word, t)
            return t
        return None

    def set(self, word: str, translation: Translation) -> None:
        payload = translation.model_dump_json()
        now = int(time.time())
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache(word, translation_json, cached_at) "
                "VALUES (?, ?, ?)",
                (word, payload, now),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"CacheStore.set failed for {word!r}: {e}")
        self._set_mem(word, translation)
        self._write_count += 1
        if self._write_count % self._TRIM_INTERVAL == 0:
            self._trim_db()

    def _set_mem(self, word: str, t: Translation) -> None:
        if word in self._mem:
            self._mem.move_to_end(word)
        self._mem[word] = t
        while len(self._mem) > self._max:
            self._mem.popitem(last=False)

    def _trim_db(self) -> None:
        """Keep the SQLite cache table bounded to _max rows."""
        try:
            self._conn.execute(
                "DELETE FROM cache WHERE word NOT IN "
                "(SELECT word FROM cache ORDER BY cached_at DESC LIMIT ?)",
                (self._max,),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.debug(f"CacheStore._trim_db failed: {e}")
