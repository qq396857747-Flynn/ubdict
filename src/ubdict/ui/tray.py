"""System tray icon for UbDict."""
from __future__ import annotations

from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu

from loguru import logger


def _make_icon() -> QIcon:
    """Generate a simple icon (letter 'D' on rounded square)."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#3b6ea5"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 12, 12)
    p.setPen(QColor("#ffffff"))
    f = QFont("Sans", 36, QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "D")
    p.end()
    return QIcon(pix)


class TrayIcon:
    """System tray with quick actions."""

    def __init__(
        self,
        app,
        on_quit,
        on_toggle_text,
        on_toggle_image,
        on_toggle_pdf,
        on_show_main,
        on_show_pdf,
        on_show_wordbook,
        on_show_settings,
    ) -> None:
        self._tray = QSystemTrayIcon(_make_icon(), app)
        self._tray.setToolTip("UbDict 字典")

        self._menu = QMenu()
        menu = self._menu

        # Capture toggles
        self._text_action = QAction("文本取词：开", menu)
        self._text_action.setCheckable(True)
        self._text_action.setChecked(True)
        self._text_action.toggled.connect(on_toggle_text)
        menu.addAction(self._text_action)

        self._image_action = QAction("图片取词：关", menu)
        self._image_action.setCheckable(True)
        self._image_action.setChecked(False)
        self._image_action.toggled.connect(on_toggle_image)
        menu.addAction(self._image_action)

        self._pdf_capture_action = QAction("PDF 悬停取词：关", menu)
        self._pdf_capture_action.setCheckable(True)
        self._pdf_capture_action.setChecked(False)
        self._pdf_capture_action.toggled.connect(on_toggle_pdf)
        menu.addAction(self._pdf_capture_action)

        menu.addSeparator()

        # Windows
        act_main = QAction("主窗口", menu)
        act_main.triggered.connect(on_show_main)
        menu.addAction(act_main)

        act_pdf = QAction("内置 PDF 阅读器", menu)
        act_pdf.triggered.connect(on_show_pdf)
        menu.addAction(act_pdf)

        act_wordbook = QAction("生词本", menu)
        act_wordbook.triggered.connect(on_show_wordbook)
        menu.addAction(act_wordbook)

        act_settings = QAction("设置", menu)
        act_settings.triggered.connect(on_show_settings)
        menu.addAction(act_settings)

        menu.addSeparator()
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(on_quit)
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)
        self._tray.show()

    def set_text_capture_state(self, enabled: bool) -> None:
        # Block signals so programmatic setChecked does not re-trigger the
        # toggled handler (which would double-apply the toggle logic).
        with QSignalBlocker(self._text_action):
            self._text_action.setChecked(enabled)
            self._text_action.setText(f"文本取词：{'开' if enabled else '关'}")

    def set_image_capture_state(self, enabled: bool) -> None:
        with QSignalBlocker(self._image_action):
            self._image_action.setChecked(enabled)
            self._image_action.setText(f"图片取词：{'开' if enabled else '关'}")

    def set_pdf_capture_state(self, enabled: bool) -> None:
        with QSignalBlocker(self._pdf_capture_action):
            self._pdf_capture_action.setChecked(enabled)
            self._pdf_capture_action.setText(f"PDF 悬停取词：{'开' if enabled else '关'}")
