"""Local dictionary adapter using ECDICT (SQLite).

ECDICT schema (key columns):
    word        TEXT
    phonetic    TEXT
    definition  TEXT   (newline-separated "pos. meaning" lines)
    translation TEXT   (Chinese translation, newline-separated)
    exchange    TEXT   (word form exchanges: p/D/0/d/s/ing/...)
    collins     TEXT   (Collins star count, optional)
    oxford      INT    (Oxford 3000 flag, optional)
    tag         TEXT   (frequency tags)

The database is optional; if absent this adapter returns None and the
service reports "no result".
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from loguru import logger

from ubdict.core.models import Definition, Example, Translation
from ubdict.core.translate.base import TranslateAdapter
from ubdict.paths import resource_path

_MODULE_PATH = Path(__file__).resolve()
_INSTALLED_DB = _MODULE_PATH.parents[3] / "config" / "ecdict.db"
_SOURCE_DB = _MODULE_PATH.parents[4] / "config" / "ecdict.db"
_BUNDLED_DB = resource_path("config/ecdict.db")
_DEFAULT_DB = next(
    (path for path in (_BUNDLED_DB, _INSTALLED_DB, _SOURCE_DB) if path.exists()),
    _BUNDLED_DB,
)

# ECDICT `exchange` format: "p/D/0/d/s/ing/ed/..." where each segment is
# "type/value". We extract the common forms to display.
_EXCHANGE_LABELS = {
    "p": "过去式",
    "d": "过去分词",
    "i": "现在分词",
    "s": "第三人称单数",
    "r": "比较级",
    "t": "最高级",
    "0": "词根",
    "1": "复数",
}


class LocalAdapter(TranslateAdapter):
    name = "local"

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB
        self._conn: sqlite3.Connection | None = None
        if self._db_path.exists():
            try:
                self._conn = sqlite3.connect(
                    str(self._db_path), check_same_thread=False
                )
                self._conn.row_factory = sqlite3.Row
                # Probe schema to detect available columns.
                self._columns = self._detect_columns()
                logger.info(
                    f"LocalAdapter loaded ECDICT from {self._db_path} "
                    f"({len(self._columns)} columns)"
                )
            except sqlite3.Error as e:
                logger.error(f"ECDICT open failed: {e}")
                self._conn = None
        else:
            logger.warning(
                f"ECDICT not found at {self._db_path}; local fallback disabled. "
                f"Run: python3 scripts/download_ecdict.py"
            )
            self._columns = set()

    def _detect_columns(self) -> set[str]:
        assert self._conn is not None
        try:
            rows = self._conn.execute("PRAGMA table_info(ecdict)").fetchall()
            return {r["name"] for r in rows}
        except sqlite3.Error:
            return set()

    async def translate(self, word: str) -> Translation | None:
        if not self._conn:
            return None
        cols = self._columns
        select = ["word", "phonetic", "definition", "translation"]
        for extra in ("exchange", "collins", "oxford"):
            if extra in cols:
                select.append(extra)
        query = (
            f"SELECT {', '.join(select)} FROM ecdict "
            f"WHERE word = ? COLLATE NOCASE LIMIT 1"
        )
        try:
            row = self._conn.execute(query, (word.lower(),)).fetchone()
        except sqlite3.Error as e:
            logger.error(f"LocalAdapter query error: {e}")
            return None
        if not row:
            return None

        definitions = self._parse_definitions(
            row["definition"], row["translation"]
        )
        # Add word forms as extra definitions if present.
        exchange = row["exchange"] if "exchange" in row.keys() else None
        forms = self._parse_exchange(exchange)
        if forms:
            definitions.append(
                Definition(pos="词形", meaning="；".join(forms))
            )

        phonetic = row["phonetic"] or None
        return Translation(
            word=word,
            phonetic_us=phonetic,
            definitions=definitions,
            source=self.name,
        )

    @staticmethod
    def _parse_definitions(
        definition: str | None, translation: str | None
    ) -> list[Definition]:
        """Parse ECDICT definition/translation into Definition list.

        ECDICT `definition` is like:
            n. 词汇，单词\\nadj. 字的
        Falls back to `translation` (pure Chinese) when `definition` is empty.
        """
        defs: list[Definition] = []
        source_text = definition or translation or ""
        if not source_text:
            return defs
        for line in source_text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^([a-z]+\.)\s*(.+)$", line)
            if m:
                defs.append(Definition(pos=m.group(1), meaning=m.group(2)))
            else:
                defs.append(Definition(pos="", meaning=line))
        return defs

    @staticmethod
    def _parse_exchange(exchange: str | None) -> list[str]:
        """Parse ECDICT exchange field into human-readable word forms.

        Format: "p/D/0/d/s/ing/ed" — alternating type/value pairs.
        """
        if not exchange:
            return []
        parts = exchange.split("/")
        forms: list[str] = []
        for i in range(0, len(parts) - 1, 2):
            etype = parts[i]
            value = parts[i + 1]
            if not value or value == "0":
                continue
            label = _EXCHANGE_LABELS.get(etype)
            if label:
                forms.append(f"{label}: {value}")
        return forms

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
