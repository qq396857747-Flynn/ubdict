"""Application wiring: creates all components and connects signals."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from loguru import logger

from ubdict.config import ConfigManager
from ubdict.core.capture.image import ImageCapture
from ubdict.core.capture.ocr import TesseractEngine
from ubdict.core.capture.text import TextCapture
from ubdict.core.event_bus import bus
from ubdict.core.translate.bing import BingAdapter
from ubdict.core.translate.local import LocalAdapter
from ubdict.core.translate.service import TranslateService
from ubdict.platform.factory import detect_backend
from ubdict.platform.hotkey import HotkeyManager
from ubdict.storage.cache import CacheStore
from ubdict.storage.db import get_db
from ubdict.storage.history import HistoryStore
from ubdict.storage.wordbook import WordbookStore
from ubdict.ui.dict_window import DictWindow
from ubdict.ui.main_window import MainWindow
from ubdict.ui.pdf_window import PdfWindow
from ubdict.ui.pronunciation import PronunciationPlayer
from ubdict.ui.settings import SettingsDialog
from ubdict.ui.tray import TrayIcon
from ubdict.ui.wordbook_window import WordbookWindow


class UbDictApp:
    """Top-level application controller."""

    def __init__(self) -> None:
        self._qapp = QApplication(sys.argv)
        self._qapp.setApplicationName("UbDict")
        self._qapp.setQuitOnLastWindowClosed(False)  # tray-only mode

        # Config
        self._config_mgr = ConfigManager()
        cfg = self._config_mgr.config

        # Storage
        self._db = get_db()
        self._cache = CacheStore(self._db, max_size=cfg.translate.cache_size)
        self._history = HistoryStore(self._db)
        self._wordbook = WordbookStore(self._db)

        # Platform
        self._backend = detect_backend()

        # Capture engines
        self._text_capture = TextCapture(
            self._backend, debounce_ms=cfg.capture.text_debounce_ms
        )
        self._text_capture.set_enabled(cfg.capture.text_enabled)
        self._ocr_engine = TesseractEngine(
            min_confidence=cfg.capture.ocr_min_confidence
        )
        self._image_capture = ImageCapture(
            self._backend, self._ocr_engine,
            hover_delay=cfg.capture.image_hover_delay,
        )
        if cfg.capture.pdf_enabled:
            cfg.capture.image_enabled = False
            self._image_capture.set_capture_kind("pdf")
        self._image_capture.set_enabled(
            cfg.capture.image_enabled or cfg.capture.pdf_enabled
        )

        # Translation
        self._bing = BingAdapter(timeout=cfg.translate.request_timeout)
        self._local = LocalAdapter()
        self._translate_service = TranslateService(
            [self._bing, self._local], self._cache, self._history
        )

        # UI
        self._dict_window = DictWindow(
            auto_close_delay_ms=cfg.ui.auto_close_delay_ms,
            font_size=cfg.ui.font_size,
        )
        self._pronunciation = PronunciationPlayer(self._qapp)
        self._dict_window.set_wordbook_store(self._wordbook)
        self._dict_window.set_main_window_callback(self._show_translation_in_main)
        self._dict_window.set_pronunciation_callback(self._pronunciation.play)
        self._dict_window.setWindowOpacity(cfg.ui.window_opacity)
        self._main_window = MainWindow(self._history, self._wordbook)
        self._main_window.set_pronunciation_callback(self._pronunciation.play)
        self._pronunciation.failed.connect(
            self._dict_window.show_pronunciation_error
        )
        self._pronunciation.failed.connect(
            self._main_window.show_pronunciation_error
        )
        self._pdf_window = PdfWindow(self._ocr_engine)
        self._wordbook_window = WordbookWindow(self._wordbook)
        self._settings_dialog: SettingsDialog | None = None
        self._tray = TrayIcon(
            self._qapp,
            on_quit=self.quit,
            on_toggle_text=self._toggle_text_capture,
            on_toggle_image=self._toggle_image_capture,
            on_toggle_pdf=self._toggle_pdf_capture,
            on_show_main=self._main_window.show,
            on_show_pdf=self._pdf_window.show,
            on_show_wordbook=self._show_wordbook,
            on_show_settings=self._show_settings,
        )
        # Sync tray state with config.
        self._tray.set_text_capture_state(cfg.capture.text_enabled)
        self._tray.set_image_capture_state(
            cfg.capture.image_enabled and not cfg.capture.pdf_enabled
        )
        self._tray.set_pdf_capture_state(cfg.capture.pdf_enabled)

        # Hotkeys
        self._hotkeys = HotkeyManager(self._backend)
        self._register_hotkeys(cfg)

        # Wire events
        bus.translate_result.connect(self._dict_window.show_result)
        bus.translate_error.connect(self._dict_window.show_error)
        self._main_window.query_requested.connect(
            self._translate_service.translate_for_main
        )
        self._translate_service.main_query_result.connect(
            self._main_window.show_query_translation
        )
        self._translate_service.main_query_error.connect(
            self._main_window.show_translation_error
        )

    def _register_hotkeys(self, cfg) -> None:
        self._hotkeys.register(cfg.hotkeys.toggle_text, self._hotkey_toggle_text)
        self._hotkeys.register(cfg.hotkeys.toggle_image, self._hotkey_toggle_image)
        self._hotkeys.register(cfg.hotkeys.show_main, self._main_window.show)
        self._hotkeys.register(cfg.hotkeys.show_pdf, self._pdf_window.show)

    def run(self) -> int:
        self._text_capture.start()
        self._image_capture.start()
        self._hotkeys.start()
        logger.info("UbDict started")
        return self._qapp.exec()

    def quit(self) -> None:
        logger.info("UbDict quitting")
        self._text_capture.stop()
        self._image_capture.stop()
        self._hotkeys.stop()
        self._translate_service.shutdown()
        self._db.close()
        self._qapp.quit()

    def _toggle_text_capture(self, enabled: bool) -> None:
        self._text_capture.set_enabled(enabled)
        self._tray.set_text_capture_state(enabled)
        self._config_mgr.config.capture.text_enabled = enabled
        logger.info(f"Text capture {'enabled' if enabled else 'disabled'}")

    def _toggle_image_capture(self, enabled: bool) -> None:
        if enabled:
            self._image_capture.set_capture_kind("image")
            self._config_mgr.config.capture.pdf_enabled = False
            self._tray.set_pdf_capture_state(False)
        self._image_capture.set_enabled(enabled)
        self._tray.set_image_capture_state(enabled)
        self._config_mgr.config.capture.image_enabled = enabled
        logger.info(f"Image capture {'enabled' if enabled else 'disabled'}")

    def _toggle_pdf_capture(self, enabled: bool) -> None:
        if enabled:
            if getattr(self._backend, "name", None) == "wayland":
                logger.warning(
                    "PDF hover OCR on Wayland requires a compositor that exposes "
                    "global pointer coordinates; standard GNOME Wayland does not"
                )
            self._image_capture.set_capture_kind("pdf")
            self._config_mgr.config.capture.image_enabled = False
            self._tray.set_image_capture_state(False)
        self._image_capture.set_enabled(enabled)
        self._tray.set_pdf_capture_state(enabled)
        self._config_mgr.config.capture.pdf_enabled = enabled
        logger.info(f"External PDF hover capture {'enabled' if enabled else 'disabled'}")

    def _show_translation_in_main(self, result) -> None:
        self._main_window.show_translation(result)

    def _show_wordbook(self) -> None:
        self._wordbook_window.refresh()
        self._wordbook_window.show()
        self._wordbook_window.raise_()
        self._wordbook_window.activateWindow()

    def _hotkey_toggle_text(self) -> None:
        new = not self._config_mgr.config.capture.text_enabled
        self._toggle_text_capture(new)

    def _hotkey_toggle_image(self) -> None:
        new = not self._config_mgr.config.capture.image_enabled
        self._toggle_image_capture(new)

    def _show_settings(self) -> None:
        self._settings_dialog = SettingsDialog(
            self._config_mgr.config, on_save=self._on_config_saved
        )
        self._settings_dialog.show()

    def _on_config_saved(self, config) -> None:
        self._config_mgr.config = config
        self._config_mgr.save()
        # Apply runtime changes.
        self._dict_window.setWindowOpacity(config.ui.window_opacity)
        self._dict_window.set_font_size(config.ui.font_size)
        self._dict_window.set_auto_close_delay_ms(config.ui.auto_close_delay_ms)
        self._text_capture.set_enabled(config.capture.text_enabled)
        self._text_capture.set_debounce_ms(config.capture.text_debounce_ms)
        self._image_capture.set_hover_delay(config.capture.image_hover_delay)
        if config.capture.pdf_enabled:
            config.capture.image_enabled = False
            self._image_capture.set_capture_kind("pdf")
        else:
            self._image_capture.set_capture_kind("image")
        self._image_capture.set_enabled(
            config.capture.image_enabled or config.capture.pdf_enabled
        )
        self._tray.set_text_capture_state(config.capture.text_enabled)
        self._tray.set_image_capture_state(
            config.capture.image_enabled and not config.capture.pdf_enabled
        )
        self._tray.set_pdf_capture_state(config.capture.pdf_enabled)
        self._cache.resize(config.translate.cache_size)
        self._ocr_engine.set_min_confidence(config.capture.ocr_min_confidence)
        self._translate_service.set_bing_timeout(config.translate.request_timeout)
        # Re-register hotkeys with the new bindings.
        self._hotkeys.reregister({
            config.hotkeys.toggle_text: self._hotkey_toggle_text,
            config.hotkeys.toggle_image: self._hotkey_toggle_image,
            config.hotkeys.show_main: self._main_window.show,
            config.hotkeys.show_pdf: self._pdf_window.show,
        })
        # Apply autostart.
        self._apply_autostart(config.autostart)
        logger.info("Configuration saved and applied")

    @staticmethod
    def _apply_autostart(enabled: bool) -> None:
        """Create or remove the XDG autostart desktop entry."""
        if sys.platform == "win32":
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            command = (
                f'"{sys.executable}"'
                if getattr(sys, "frozen", False)
                else f'"{sys.executable}" -m ubdict.main'
            )
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    if enabled:
                        winreg.SetValueEx(key, "UbDict", 0, winreg.REG_SZ, command)
                    else:
                        try:
                            winreg.DeleteValue(key, "UbDict")
                        except FileNotFoundError:
                            pass
            except OSError:
                logger.exception("Failed to update Windows autostart registry entry")
            return
        autostart_dir = Path.home() / ".config" / "autostart"
        try:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            desktop = autostart_dir / "ubdict.desktop"
            if enabled:
                desktop.write_text(
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=UbDict\n"
                    "Exec=ubdict\n"
                    "Icon=ubdict\n"
                    "Terminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n"
                )
            elif desktop.exists():
                desktop.unlink()
        except OSError as e:
            logger.warning(f"Failed to update autostart entry: {e}")
