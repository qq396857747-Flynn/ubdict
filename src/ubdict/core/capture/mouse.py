"""Mouse position monitor.

Polls the mouse position on a background thread and reports:
- movement events
- hover events (position unchanged for `hover_delay` seconds)

Used by the image capture engine to trigger OCR after a 3-second hover.
"""
from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from loguru import logger

from ubdict.platform.base import PlatformBackend


class MouseMonitor(QObject):
    """Monitors mouse position and emits hover events.

    Signals
    -------
    mouse_moved(int, int)
        Emitted on every poll where the position changed.
    hovered(int, int)
        Emitted when the mouse stays at the same position for
        `hover_delay` seconds. Emitted on the monitor thread —
        receivers must be thread-safe or use Qt queued connections.
    """

    mouse_moved = pyqtSignal(int, int)
    hovered = pyqtSignal(int, int)

    def __init__(
        self,
        backend: PlatformBackend,
        hover_delay: float = 3.0,
        poll_interval: float = 0.2,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._hover_delay = hover_delay
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="mouse-monitor", daemon=True
        )
        self._thread.start()
        logger.info("MouseMonitor started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("MouseMonitor stopped")

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def set_hover_delay(self, delay: float) -> None:
        self._hover_delay = delay

    def _loop(self) -> None:
        last_pos: tuple[int, int] | None = None
        stable_since: float | None = None
        hover_fired_pos: tuple[int, int] | None = None

        while not self._stop.is_set():
            if not self._enabled:
                time.sleep(self._poll_interval)
                continue

            try:
                pos = self._backend.get_mouse_position()
            except Exception as e:
                logger.debug(f"mouse position error: {e}")
                time.sleep(self._poll_interval)
                continue

            if pos is None:
                last_pos = None
                stable_since = None
                hover_fired_pos = None
                time.sleep(self._poll_interval)
                continue

            now = time.monotonic()

            if pos != last_pos:
                # Mouse moved: reset hover tracking.
                self.mouse_moved.emit(pos[0], pos[1])
                last_pos = pos
                stable_since = now
                hover_fired_pos = None
            else:
                # Position stable — check if we should fire hover.
                if (
                    stable_since is not None
                    and hover_fired_pos != pos
                    and now - stable_since >= self._hover_delay
                ):
                    self.hovered.emit(pos[0], pos[1])
                    hover_fired_pos = pos  # Don't re-fire for same position.

            time.sleep(self._poll_interval)
