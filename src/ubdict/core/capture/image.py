"""Image capture engine (OCR).

When the mouse hovers over the same position for `hover_delay` seconds,
captures a region around the cursor, runs OCR, and emits `word_captured`
for the word nearest the cursor.

Includes a cooldown after failed recognitions to avoid CPU thrash. OCR runs
on a background thread so the GUI never freezes during recognition.
"""
from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from loguru import logger

from ubdict.core.capture.mouse import MouseMonitor
from ubdict.core.capture.ocr import OcrEngine, OcrResult
from ubdict.core.event_bus import bus
from ubdict.platform.base import PlatformBackend

# Capture region size around the cursor (width x height).
_REGION_W = 240
_REGION_H = 100
# Cooldown after a failed OCR (no words found), seconds.
_FAIL_COOLDOWN = 10.0
# Minimum word length to accept.
_MIN_WORD_LEN = 2


class ImageCapture(QObject):
    """Image (OCR) capture engine.

    Inherits QObject for signal/slot wiring with MouseMonitor.
    """

    name = "image"

    # Internal signal to bridge cross-thread hover events to the GUI thread.
    _hover_triggered = pyqtSignal(int, int)
    # Bridge OCR worker thread results back to the GUI thread.
    _ocr_done = pyqtSignal(object)  # str | None

    def __init__(
        self,
        backend: PlatformBackend,
        ocr_engine: OcrEngine,
        hover_delay: float = 3.0,
    ) -> None:
        QObject.__init__(self)
        self._backend = backend
        self._ocr = ocr_engine
        self._enabled = True
        self._capture_kind = "image"
        self._hover_delay = hover_delay
        self._last_fail_time: float = 0.0
        self._ocr_busy = False
        self._ocr_generation = 0

        self._mouse = MouseMonitor(backend, hover_delay=hover_delay)
        # Bridge the mouse monitor's hovered signal (emitted from monitor
        # thread) to our _hover_triggered signal, then connect to the slot
        # that runs on the GUI thread.
        self._mouse.hovered.connect(self._hover_triggered)
        self._mouse.mouse_moved.connect(self._on_mouse_moved)
        self._hover_triggered.connect(self._on_hover)
        self._ocr_done.connect(self._on_ocr_done)

    def start(self) -> None:
        self._mouse.start()
        logger.info(
            f"ImageCapture started (hover_delay={self._hover_delay}s, region={_REGION_W}x{_REGION_H})"
        )

    def stop(self) -> None:
        self._ocr_generation += 1
        self._mouse.stop()
        logger.info("ImageCapture stopped")

    def set_enabled(self, enabled: bool) -> None:
        if self._enabled != enabled:
            self._ocr_generation += 1
        self._enabled = enabled
        self._mouse.set_enabled(enabled)

    def set_capture_kind(self, kind: str) -> None:
        if kind not in {"image", "pdf"}:
            raise ValueError(f"Unsupported OCR capture kind: {kind}")
        if self._capture_kind != kind:
            self._ocr_generation += 1
        self._capture_kind = kind

    def set_hover_delay(self, delay: float) -> None:
        self._hover_delay = delay
        self._mouse.set_hover_delay(delay)

    def _on_mouse_moved(self, _x: int, _y: int) -> None:
        self._ocr_generation += 1

    def _on_hover(self, x: int, y: int) -> None:
        if not self._enabled:
            return
        if self._ocr_busy:
            return  # A previous OCR is still running; skip this hover.
        # Cooldown after recent failures.
        now = time.monotonic()
        if now - self._last_fail_time < _FAIL_COOLDOWN:
            return

        # Capture the screen region on the GUI thread (fast); OCR is slow and
        # runs on a worker thread to avoid freezing the UI.
        left = x - _REGION_W // 2
        top = y - _REGION_H // 2
        if getattr(self._backend, "name", None) == "wayland":
            # WaylandBackend clamps capture origins at the top/left screen
            # edges, so use the same origin when mapping the cursor into OCR
            # image coordinates.
            left = max(0, left)
            top = max(0, top)
        cursor_local = (x - left, y - top)
        try:
            image_bytes = self._backend.capture_region(left, top, _REGION_W, _REGION_H)
        except Exception as e:
            logger.error(f"capture_region failed: {e}")
            return
        if not image_bytes:
            return

        self._ocr_busy = True
        capture_kind = self._capture_kind
        self._ocr_generation += 1
        generation = self._ocr_generation
        threading.Thread(
            target=self._ocr_worker,
            args=(image_bytes, cursor_local, capture_kind, generation, x, y),
            name="ocr",
            daemon=True,
        ).start()

    def _ocr_worker(
        self,
        image_bytes: bytes,
        cursor_local: tuple[int, int],
        capture_kind: str,
        generation: int,
        cursor_x: int,
        cursor_y: int,
    ) -> None:
        """Run OCR off the GUI thread and bridge the result back."""
        word: str | None = None
        try:
            results = self._ocr.recognize(image_bytes)
            if results:
                best = self._under_cursor(results, cursor_local)
                if best and len(best.text) >= _MIN_WORD_LEN:
                    word = best.text
        except Exception as e:
            logger.error(f"OCR worker error: {e}")
        # Emit back to the GUI thread (queued connection).
        self._ocr_done.emit((word, capture_kind, generation, cursor_x, cursor_y))

    def _on_ocr_done(self, result) -> None:
        self._ocr_busy = False
        word, capture_kind, generation, cursor_x, cursor_y = result
        if (
            not self._enabled
            or capture_kind != self._capture_kind
            or generation != self._ocr_generation
        ):
            logger.debug("Discarded stale OCR result")
            return
        try:
            if self._backend.get_mouse_position() != (cursor_x, cursor_y):
                logger.debug("Discarded OCR result after pointer moved")
                return
        except Exception as e:
            logger.warning(f"Could not verify OCR pointer position: {e}")
            return
        if word:
            logger.info(f"{capture_kind.title()} capture recognized: {word!r}")
            bus.word_captured.emit(word)
        else:
            self._last_fail_time = time.monotonic()
            logger.debug(f"ImageCapture no word; cooldown {_FAIL_COOLDOWN}s")

    @staticmethod
    def _under_cursor(
        results: list[OcrResult], target: tuple[int, int]
    ) -> OcrResult | None:
        """Return an OCR word only when the cursor is inside its bounding box."""
        tx, ty = target
        matches = [
            result
            for result in results
            if result.x <= tx < result.x + result.w
            and result.y <= ty < result.y + result.h
        ]
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        # Overlapping OCR boxes can occur; prefer the most specific word box.
        return min(matches, key=lambda result: result.w * result.h)
