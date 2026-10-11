"""Platform-specific application data and bundled resource locations."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def user_config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "UbDict"
    return Path.home() / ".config" / "ubdict"


def user_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")
        ) / "UbDict"
    return Path.home() / ".local" / "share" / "ubdict"


def resource_path(relative_path: str) -> Path:
    """Locate a bundled resource or its source-tree equivalent."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return bundle_root / relative_path
