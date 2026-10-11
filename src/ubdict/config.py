"""Configuration management for UbDict.

Loads/saves a TOML config file in the platform-specific UbDict config directory.
Falls back to defaults if the file is missing or invalid.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore

import tomli_w  # type: ignore

from loguru import logger
from ubdict.paths import user_config_dir

_CONFIG_DIR = user_config_dir()
_CONFIG_FILE = _CONFIG_DIR / "config.toml"


def _clamp(value: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def _clamp_int(value, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


@dataclass
class CaptureConfig:
    text_enabled: bool = True
    image_enabled: bool = False
    pdf_enabled: bool = False
    image_hover_delay: float = 3.0
    text_debounce_ms: int = 300
    ocr_min_confidence: int = 60


@dataclass
class TranslateConfig:
    sources: list[str] = field(default_factory=lambda: ["bing", "local"])
    cache_size: int = 1000
    request_timeout: float = 5.0


@dataclass
class UiConfig:
    window_opacity: float = 1.0
    font_size: int = 13
    auto_close_delay_ms: int = 8000


@dataclass
class HotkeyConfig:
    toggle_text: str = "Ctrl+Shift+T"
    toggle_image: str = "Ctrl+Shift+O"
    show_main: str = "Ctrl+Shift+D"
    show_pdf: str = "Ctrl+Shift+P"


@dataclass
class AppConfig:
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    translate: TranslateConfig = field(default_factory=TranslateConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    autostart: bool = False


class ConfigManager:
    """Load and save application configuration."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _CONFIG_FILE
        self.config = self._load()

    def _load(self) -> AppConfig:
        if not self._path.exists():
            logger.info(f"Config not found, using defaults: {self._path}")
            return AppConfig()
        try:
            with open(self._path, "rb") as f:
                data = tomllib.load(f)
            return self._from_dict(data)
        except Exception as e:
            logger.warning(f"Config load failed ({e}), using defaults")
            return AppConfig()

    def _from_dict(self, data: dict) -> AppConfig:
        cfg = AppConfig()
        self._apply_section(cfg.capture, data.get("capture", {}), CaptureConfig)
        self._apply_section(cfg.translate, data.get("translate", {}), TranslateConfig)
        self._apply_section(cfg.ui, data.get("ui", {}), UiConfig)
        self._apply_section(cfg.hotkeys, data.get("hotkeys", {}), HotkeyConfig)
        if "autostart" in data:
            try:
                cfg.autostart = bool(data["autostart"])
            except Exception:
                pass
        self._validate(cfg)
        return cfg

    @staticmethod
    def _apply_section(target, section: dict, cls) -> None:
        """Update a dataclass section from a dict, ignoring unknown keys and
        bad values so one corrupt section never discards the whole config."""
        if not isinstance(section, dict):
            return
        valid_keys = set(getattr(cls, "__dataclass_fields__", {}))
        for key, value in section.items():
            if key not in valid_keys:
                continue
            try:
                setattr(target, key, value)
            except Exception as e:
                logger.warning(f"Config field {key}={value!r} rejected: {e}")

    @staticmethod
    def _validate(cfg: AppConfig) -> None:
        """Clamp numeric fields to sane ranges."""
        cfg.capture.image_hover_delay = _clamp(cfg.capture.image_hover_delay, 0.1, 30.0)
        cfg.capture.text_debounce_ms = _clamp_int(cfg.capture.text_debounce_ms, 10, 5000)
        cfg.capture.ocr_min_confidence = _clamp_int(cfg.capture.ocr_min_confidence, 0, 100)
        cfg.translate.cache_size = _clamp_int(cfg.translate.cache_size, 1, 100000)
        cfg.translate.request_timeout = _clamp(cfg.translate.request_timeout, 0.5, 60.0)
        cfg.ui.window_opacity = _clamp(cfg.ui.window_opacity, 0.3, 1.0)
        cfg.ui.font_size = _clamp_int(cfg.ui.font_size, 8, 40)
        cfg.ui.auto_close_delay_ms = _clamp_int(cfg.ui.auto_close_delay_ms, 3000, 30000)

    def save(self) -> None:
        """Persist current config to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "capture": asdict(self.config.capture),
            "translate": asdict(self.config.translate),
            "ui": asdict(self.config.ui),
            "hotkeys": asdict(self.config.hotkeys),
            "autostart": self.config.autostart,
        }
        try:
            with open(self._path, "wb") as f:
                tomli_w.dump(data, f)
            logger.info(f"Config saved: {self._path}")
        except Exception as e:
            logger.error(f"Config save failed: {e}")

    @property
    def path(self) -> Path:
        return self._path
