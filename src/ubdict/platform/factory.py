"""Platform backend factory."""
from __future__ import annotations

import os
import sys

from loguru import logger

from ubdict.platform.base import PlatformBackend


def detect_backend() -> PlatformBackend:
    """Auto-detect Windows, X11, or Wayland and return the matching backend."""
    if sys.platform == "win32":
        from ubdict.platform.windows import WindowsBackend

        logger.info("Detected Windows desktop")
        return WindowsBackend()
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland":
        from ubdict.platform.wayland import WaylandBackend

        logger.info("Detected Wayland session")
        return WaylandBackend()
    # Default to X11 (covers "x11" and unset)
    from ubdict.platform.x11 import X11Backend

    logger.info("Detected X11 session")
    return X11Backend()
