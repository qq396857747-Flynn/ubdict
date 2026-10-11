"""Platform abstraction base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable


class PlatformBackend(ABC):
    """Abstract platform backend for desktop input and screen operations."""

    name: str = "base"

    @abstractmethod
    def get_mouse_position(self) -> tuple[int, int] | None:
        """Return current mouse coordinates, or None when unavailable."""

    @abstractmethod
    def get_selection_text(self) -> str | None:
        """Return selected text when available, or None."""

    @abstractmethod
    def capture_region(self, x: int, y: int, w: int, h: int) -> bytes:
        """Capture a screen region and return PNG bytes."""

    @abstractmethod
    def start_selection_watch(self, on_change: Callable[[str], None]) -> None:
        """Watch for selected/copied text changes.

        Calls `on_change(text)` when the platform reports new text.
        """

    @abstractmethod
    def stop_selection_watch(self) -> None:
        """Stop watching the selection."""
