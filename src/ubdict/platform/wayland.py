"""Wayland platform backend.

Wayland's security model restricts global input monitoring. We use:
- wl-paste / wl-copy for clipboard/selection access
- grim for screenshots
- Mouse position requires wlr-foreign-toplevel or a compositor-specific
  interface; when unavailable, image capture falls back to a hotkey trigger.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time

from loguru import logger

from ubdict.platform.base import PlatformBackend


class WaylandBackend(PlatformBackend):
    name = "wayland"

    def __init__(self) -> None:
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._last_selection: str = ""

    def get_mouse_position(self) -> tuple[int, int] | None:
        # Wayland does not expose global pointer position to clients.
        # Best-effort: try wlr-foreign-toplevel via wlr-randr or hyprctl.
        for cmd in (
            ["hyprctl", "cursorpos"],
            ["swaymsg", "-t", "get_cursor_position"],
        ):
            try:
                out = subprocess.check_output(cmd, timeout=0.5, text=True)
                text = out.strip()
                if cmd[0] == "swaymsg":
                    position = json.loads(text)
                    if isinstance(position, dict):
                        x, y = position.get("x"), position.get("y")
                        if isinstance(x, int) and isinstance(y, int):
                            return x, y
                elif "," in text:
                    # hyprctl returns "x, y"
                    xs, ys = text.split(",", 1)
                    return int(xs.strip()), int(ys.strip())
            except Exception:
                continue
        if not getattr(self, "_warned_pointer", False):
            logger.warning(
                "Wayland compositor does not expose global pointer coordinates; "
                "image hover capture is unavailable in this session"
            )
            self._warned_pointer = True
        return None

    def get_selection_text(self) -> str | None:
        # Wayland PRIMARY selection via wl-paste
        try:
            result = subprocess.run(
                ["wl-paste", "--primary"],
                capture_output=True,
                text=True,
                timeout=0.5,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
        except FileNotFoundError:
            if not getattr(self, "_warned_wl", False):
                logger.warning("wl-paste not found; install wl-clipboard for selection support")
                self._warned_wl = True
        except Exception as e:
            logger.debug(f"get_selection_text failed: {e}")
        return None

    def capture_region(self, x: int, y: int, w: int, h: int) -> bytes:
        # grim supports geometry: grim -g "WxH+X+Y". Clamp origin so the
        # geometry string never contains negative offsets (e.g. "WxH+-N+M").
        x = max(0, x)
        y = max(0, y)
        try:
            result = subprocess.run(
                ["grim", "-g", f"{w}x{h}+{x}+{y}", "-"],
                capture_output=True,
                timeout=2,
            )
            if result.returncode == 0:
                return result.stdout  # PNG bytes
        except Exception as e:
            logger.error(f"grim capture failed: {e}")
        return b""

    def start_selection_watch(self, on_change: callable) -> None:
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
            target=_loop, name="wayland-selection-watch", daemon=True
        )
        self._watch_thread.start()
        logger.info("Wayland selection watch started")

    def stop_selection_watch(self) -> None:
        self._watch_stop.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=2)
        logger.info("Wayland selection watch stopped")
