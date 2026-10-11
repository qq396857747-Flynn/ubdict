"""Text capture engine.

Watches the PRIMARY selection via the platform backend and emits
`word_captured` events on the event bus. Includes a debounce timer
to avoid firing on intermediate selection changes.
"""
from __future__ import annotations

import re

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from loguru import logger

from ubdict.core.event_bus import bus
from ubdict.platform.base import PlatformBackend

# Match English words / short phrases (letters, apostrophes, hyphens, spaces).
_ENGLISH_RE = re.compile(r"^[A-Za-z][A-Za-z'\- ]{0,199}$")
_MAX_WORDS = 5
# Reject absurdly long single tokens (e.g. hashes) that are not real words.
_MAX_WORD_LEN = 64


class TextCapture(QObject):
    """Text selection capture with debounce."""

    name = "text"
    _selection_changed = pyqtSignal(str)

    def __init__(self, backend: PlatformBackend, debounce_ms: int = 300) -> None:
        super().__init__()
        self._backend = backend
        self._debounce_ms = debounce_ms
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._selection_changed.connect(self._on_selection_change)
        self._pending: str = ""
        self._enabled = True

    def start(self) -> None:
        self._backend.start_selection_watch(self._selection_changed.emit)
        logger.info("TextCapture started")

    def stop(self) -> None:
        self._backend.stop_selection_watch()
        self._timer.stop()
        logger.info("TextCapture stopped")

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def set_debounce_ms(self, debounce_ms: int) -> None:
        self._debounce_ms = debounce_ms
        if self._timer.isActive():
            self._timer.start(self._debounce_ms)

    def _on_selection_change(self, text: str) -> None:
        if not self._enabled:
            return
        cleaned = text.strip()
        if not cleaned or not self._is_valid(cleaned):
            return
        # Debounce: restart timer on each change.
        self._pending = cleaned
        self._timer.start(self._debounce_ms)

    def _is_valid(self, text: str) -> bool:
        if not _ENGLISH_RE.match(text):
            return False
        # Reject if too many words (likely a paragraph, not a word lookup)
        words = text.split()
        if len(words) > _MAX_WORDS:
            return False
        if any(len(w) > _MAX_WORD_LEN for w in words):
            return False
        return True

    def _fire(self) -> None:
        word = self._pending.strip()
        if not word:
            return
        logger.debug(f"TextCapture firing: {word!r}")
        bus.word_captured.emit(word)
