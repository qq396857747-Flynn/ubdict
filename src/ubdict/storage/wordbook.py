"""Wordbook (vocabulary notebook) store."""
from __future__ import annotations

import csv
import sqlite3
import time
import unicodedata

from loguru import logger

# Bound the interactive list view; CSV export streams every row.
_MAX_LIST = 5000
_EXPORT_BATCH_SIZE = 1000


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formulas after leading spaces or controls."""
    s = "" if value is None else str(value)
    index = 0
    while index < len(s) and (
        s[index].isspace() or unicodedata.category(s[index]).startswith("C")
    ):
        index += 1
    if any(char in s[:index] for char in ("\t", "\r", "\n")):
        return "'" + s
    if index < len(s) and s[index] in ("=", "+", "-", "@"):
        return "'" + s
    return s


class WordbookStore:
    """Manages the user's saved words (生词本)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, word: str, note: str = "") -> bool:
        """Add a word. Returns True if newly added, False if already existed."""
        now = int(time.time())
        try:
            self._conn.execute(
                "INSERT INTO wordbook(word, added_at, note) VALUES (?, ?, ?)",
                (word.lower(), now, note),
            )
            self._conn.commit()
            logger.info(f"Added to wordbook: {word}")
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.Error as e:
            logger.error(f"WordbookStore.add failed: {e}")
            return False

    def remove(self, word: str) -> None:
        try:
            self._conn.execute(
                "DELETE FROM wordbook WHERE word = ?", (word.lower(),)
            )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"WordbookStore.remove failed: {e}")

    def contains(self, word: str) -> bool:
        try:
            row = self._conn.execute(
                "SELECT 1 FROM wordbook WHERE word = ?", (word.lower(),)
            ).fetchone()
            return row is not None
        except sqlite3.Error as e:
            logger.error(f"WordbookStore.contains failed: {e}")
            return False

    def list_all(self, limit: int = _MAX_LIST) -> list[dict]:
        try:
            rows = self._conn.execute(
                "SELECT word, added_at, note FROM wordbook "
                "ORDER BY added_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"WordbookStore.list_all failed: {e}")
            return []

    def count(self) -> int:
        try:
            return self._conn.execute("SELECT COUNT(*) FROM wordbook").fetchone()[0]
        except sqlite3.Error as e:
            logger.error(f"WordbookStore.count failed: {e}")
            return 0

    def export_csv(self, path: str) -> int:
        """Export wordbook to CSV. Returns number of rows written."""
        try:
            cursor = self._conn.execute(
                "SELECT word, added_at, note FROM wordbook ORDER BY added_at DESC"
            )
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["word", "added_at", "note"])
                count = 0
                while rows := cursor.fetchmany(_EXPORT_BATCH_SIZE):
                    for row in rows:
                        writer.writerow(
                            [
                                _csv_safe(row["word"]),
                                row["added_at"],
                                _csv_safe(row["note"]),
                            ]
                        )
                        count += 1
                return count
        except (OSError, sqlite3.Error, csv.Error) as e:
            logger.error(f"WordbookStore.export_csv failed: {e}")
            raise
