"""Event bus for decoupled inter-module communication.

Uses Qt signals so slots run on the GUI thread (thread-safe UI updates).
The bus is lazily created on first access to ensure QApplication exists.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class EventBus(QObject):
    """Global event bus.

    Signals
    -------
    word_captured(str)
        Emitted by a capture engine when a word is extracted.
    translate_started(str)
        Emitted when a translation query begins.
    translate_result(Translation)
        Emitted on successful translation.
    translate_error(str, str)
        Emitted on failure: (word, error_message).
    """

    word_captured = pyqtSignal(str)
    translate_started = pyqtSignal(str)
    translate_result = pyqtSignal(object)  # Translation
    translate_error = pyqtSignal(str, str)  # word, message


_bus: EventBus | None = None


def get_bus() -> EventBus:
    """Get the global event bus singleton (lazy creation)."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


# Convenience proxy: `from ubdict.core.event_bus import bus` then `bus.word_captured.emit(...)`.
# Access triggers lazy creation.
class _BusProxy:
    def __getattr__(self, name):
        return getattr(get_bus(), name)


bus = _BusProxy()
