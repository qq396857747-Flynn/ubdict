"""X11 platform backend.

Uses python-xlib for selection/mouse monitoring and mss for screenshots.
Falls back to xclip/xsel subprocesses when xlib is unavailable.
"""
from __future__ import annotations

import subprocess
import threading
import time

from loguru import logger

from ubdict.platform.base import PlatformBackend


class X11Backend(PlatformBackend):
    name = "x11"

    def __init__(self) -> None:
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._last_selection: str = ""

    def get_mouse_position(self) -> tuple[int, int]:
        try:
            import Xlib.display  # type: ignore
            import Xlib.X  # type: ignore

            display = Xlib.display.Display()
            root = display.screen().root
            ptr = root.query_pointer()
            return ptr.root_x, ptr.root_y
        except Exception:
            # Fallback: xdotool
            try:
                out = subprocess.check_output(
                    ["xdotool", "getmouselocation", "--shell"],
                    timeout=1,
                    text=True,
                )
                x = y = 0
                for line in out.splitlines():
                    if line.startswith("X="):
                        x = int(line[2:])
                    elif line.startswith("Y="):
                        y = int(line[2:])
                return x, y
            except Exception as e:
                logger.debug(f"get_mouse_position failed: {e}")
                return 0, 0

    def get_selection_text(self) -> str | None:
        """Read PRIMARY selection via xclip."""
        try:
            result = subprocess.run(
                ["xclip", "-o", "-selection", "primary"],
                capture_output=True,
                text=True,
                timeout=0.5,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
        except FileNotFoundError:
            # Try xsel as fallback
            try:
                result = subprocess.run(
                    ["xsel", "-o", "-p"],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                    stdin=subprocess.DEVNULL,
                )
                if result.returncode == 0 and result.stdout:
                    return result.stdout.strip()
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"get_selection_text failed: {e}")
        return None

    def capture_region(self, x: int, y: int, w: int, h: int) -> bytes:
        import mss

        with mss.mss() as sct:
            monitor = {"left": x, "top": y, "width": w, "height": h}
            shot = sct.grab(monitor)
            # Convert BGRA -> PNG via mss tools
            import mss.tools

            return mss.tools.to_png(shot.rgb, shot.size)

    def start_selection_watch(self, on_change: callable) -> None:
        """Poll PRIMARY selection for changes (500ms interval).

        A pure xlib event-driven approach would register a SelectionNotify
        event handler, but polling is simpler and robust across toolkits.
        """
        self._watch_stop.clear()

        def _loop() -> None:
            while not self._watch_stop.is_set():
                text = self.get_selection_text()
                if text and text != self._last_selection:
                    self._last_selection = text
                    try:
                        on_change(text)
                    except Exception as e:
                        logger.error(f"selection callback error: {e}")
                time.sleep(0.5)

        self._watch_thread = threading.Thread(
            target=_loop, name="x11-selection-watch", daemon=True
        )
        self._watch_thread.start()
        logger.info("X11 selection watch started")

    def stop_selection_watch(self) -> None:
        self._watch_stop.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=2)
        logger.info("X11 selection watch stopped")
