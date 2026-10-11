import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PyQt6.QtWidgets import QApplication

from ubdict.core.capture.image import ImageCapture
from ubdict.core.capture.ocr import FakeOcrEngine, OcrResult
from ubdict.core.event_bus import bus
from ubdict.platform.base import PlatformBackend
from ubdict.platform.wayland import WaylandBackend

_APP = QApplication.instance() or QApplication([])


def test_targeting_requires_cursor_inside_word_box():
    results = [
        OcrResult("first", 10, 10, 30, 14),
        OcrResult("adjacent", 46, 10, 48, 14),
    ]

    assert ImageCapture._under_cursor(results, (20, 15)).text == "first"
    assert ImageCapture._under_cursor(results, (70, 15)).text == "adjacent"
    assert ImageCapture._under_cursor(results, (43, 15)) is None
    assert ImageCapture._under_cursor(results, (150, 60)) is None


def test_wayland_edge_capture_uses_clamped_cursor_coordinates():
    app = _APP

    class Backend(PlatformBackend):
        name = "wayland"

        def __init__(self):
            self.capture_args = None

        def get_mouse_position(self):
            return (30, 20)

        def get_selection_text(self):
            return None

        def capture_region(self, x, y, w, h):
            self.capture_args = (x, y, w, h)
            return b"test image"

        def start_selection_watch(self, on_change):
            pass

        def stop_selection_watch(self):
            pass

    backend = Backend()
    capture = ImageCapture(
        backend,
        FakeOcrEngine([OcrResult("target", 25, 15, 32, 14)]),
    )
    captured = []
    on_word = captured.append
    bus.word_captured.connect(on_word)
    try:
        capture._on_hover(30, 20)
        deadline = time.monotonic() + 2
        while not captured and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        assert backend.capture_args == (0, 0, 240, 100)
        assert captured == ["target"]
    finally:
        bus.word_captured.disconnect(on_word)


def test_ocr_result_is_discarded_after_pointer_moves_or_capture_is_disabled():
    app = _APP

    class Backend(PlatformBackend):
        name = "test"

        def get_mouse_position(self):
            return (100, 100)

        def get_selection_text(self):
            return None

        def capture_region(self, x, y, w, h):
            return b"image"

        def start_selection_watch(self, on_change):
            pass

        def stop_selection_watch(self):
            pass

    capture = ImageCapture(Backend(), FakeOcrEngine())
    captured = []
    on_word = captured.append
    bus.word_captured.connect(on_word)
    try:
        capture._ocr_generation = 2
        capture._on_ocr_done(("stale", "image", 1, 50, 50))
        capture._on_ocr_done(("moved", "image", 2, 50, 50))
        capture.set_enabled(False)
        capture._on_ocr_done(("disabled", "image", 3, 100, 100))
        app.processEvents()
        assert captured == []
    finally:
        bus.word_captured.disconnect(on_word)


def test_capture_delay_can_be_updated_at_runtime():
    class Backend(PlatformBackend):
        name = "test"

        def get_mouse_position(self):
            return None

        def get_selection_text(self):
            return None

        def capture_region(self, x, y, w, h):
            return b""

        def start_selection_watch(self, on_change):
            pass

        def stop_selection_watch(self):
            pass

    capture = ImageCapture(Backend(), FakeOcrEngine())
    capture.set_hover_delay(1.5)
    assert capture._hover_delay == 1.5
    assert capture._mouse._hover_delay == 1.5


def test_wayland_backend_parses_sway_pointer_position(monkeypatch):
    def check_output(command, **_kwargs):
        if command[0] == "hyprctl":
            raise FileNotFoundError
        return '{"x": 123, "y": 456}'

    monkeypatch.setattr("ubdict.platform.wayland.subprocess.check_output", check_output)

    assert WaylandBackend().get_mouse_position() == (123, 456)


def test_wayland_backend_parses_hyprland_pointer_position(monkeypatch):
    monkeypatch.setattr(
        "ubdict.platform.wayland.subprocess.check_output",
        lambda *_args, **_kwargs: "12, 34",
    )

    assert WaylandBackend().get_mouse_position() == (12, 34)
