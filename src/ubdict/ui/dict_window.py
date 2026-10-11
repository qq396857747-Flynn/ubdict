"""Translation popup window.

Frameless, semi-transparent, stays-on-top widget that appears near the
cursor and auto-closes on focus loss.
"""
from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer, QPoint, QEvent
from PyQt6.QtGui import QFont, QCursor
from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFrame,
    QApplication,
)

from loguru import logger

from ubdict.core.models import Translation


_STYLE = """
#DictWindow {
    background: #2d2d32;
    border-radius: 10px;
    border: 1px solid rgba(120, 120, 130, 180);
}
QLabel { color: #e8e8e8; }
#WordLabel { font-size: 18px; font-weight: 600; color: #ffffff; }
#PhoneticLabel { color: #b0d0ff; font-size: 12px; }
#PosLabel { color: #ffd089; font-weight: 600; }
#MeaningLabel { color: #f0f0f0; font-size: 13px; }
#ExampleEn { color: #c8d8ff; font-size: 12px; font-style: italic; }
#ExampleZh { color: #d0d0d0; font-size: 12px; }
#SourceLabel { color: #888; font-size: 10px; }
#ErrorLabel { color: #ff9090; font-size: 13px; }
QPushButton { color: #ccc; border: none; padding: 2px 6px; }
QPushButton:hover { color: #fff; }
"""


class DictWindow(QWidget):
    """Popup translation window."""

    def __init__(self, auto_close_delay_ms: int = 8000, font_size: int = 13) -> None:
        self._auto_close_delay_ms = auto_close_delay_ms
        self._font_size = font_size
        super().__init__(
            flags=Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setObjectName("DictWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowOpacity(0.96)
        self.setFixedWidth(420)
        self.setStyleSheet(_STYLE)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 10, 14, 10)
        self._layout.setSpacing(6)

        # Header row: word + phonetic + close button
        header = QHBoxLayout()
        self._word_label = QLabel()
        self._word_label.setObjectName("WordLabel")
        self._phonetic_label = QLabel()
        self._phonetic_label.setObjectName("PhoneticLabel")
        header.addWidget(self._word_label)
        header.addWidget(self._phonetic_label, 1)
        self._pronounce_btn = QPushButton("🔊")
        self._pronounce_btn.setToolTip("播放单词读音（离线语音）")
        self._pronounce_btn.clicked.connect(self._on_pronounce)
        header.addWidget(self._pronounce_btn)
        self._close_btn = QPushButton("✕")
        self._close_btn.clicked.connect(self.close)
        header.addWidget(self._close_btn)
        self._layout.addLayout(header)

        # Definitions container
        self._defs_frame = QFrame()
        self._defs_layout = QVBoxLayout(self._defs_frame)
        self._defs_layout.setContentsMargins(0, 0, 0, 0)
        self._defs_layout.setSpacing(4)
        self._layout.addWidget(self._defs_frame)

        # Examples container
        self._examples_frame = QFrame()
        self._examples_layout = QVBoxLayout(self._examples_frame)
        self._examples_layout.setContentsMargins(0, 0, 0, 0)
        self._examples_layout.setSpacing(6)
        self._layout.addWidget(self._examples_frame)

        # Footer: source
        self._source_label = QLabel()
        self._source_label.setObjectName("SourceLabel")
        self._layout.addWidget(self._source_label)

        action_row = QHBoxLayout()
        self._main_btn = QPushButton("在主窗口显示更多")
        self._main_btn.clicked.connect(self._on_show_main)
        action_row.addWidget(self._main_btn)
        self._wordbook_btn = QPushButton("加入生词本")
        self._wordbook_btn.clicked.connect(self._on_star)
        action_row.addWidget(self._wordbook_btn)
        self._layout.addLayout(action_row)
        self._action_status = QLabel()
        self._action_status.setObjectName("SourceLabel")
        self._layout.addWidget(self._action_status)

        # Error label (hidden by default)
        self._error_label = QLabel()
        self._error_label.setObjectName("ErrorLabel")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        self._layout.addWidget(self._error_label)

        # Auto-close on focus loss (delayed).
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.hide)

        # Wordbook store (set by app; optional).
        self._wordbook = None
        self._current_word = ""
        self._current_result: Translation | None = None
        self._main_window_callback: Callable[[Translation], None] | None = None
        self._pronunciation_callback: Callable[[str], None] | None = None

    def set_wordbook_store(self, store) -> None:
        """Inject the WordbookStore used by the wordbook action."""
        self._wordbook = store

    def set_main_window_callback(
        self, callback: Callable[[Translation], None]
    ) -> None:
        self._main_window_callback = callback

    def set_pronunciation_callback(self, callback: Callable[[str], None]) -> None:
        self._pronunciation_callback = callback

    def set_font_size(self, font_size: int) -> None:
        self._font_size = font_size

    def set_auto_close_delay_ms(self, delay_ms: int) -> None:
        self._auto_close_delay_ms = delay_ms

    # ---- Public API ----------------------------------------------------------

    def show_result(self, result: Translation) -> None:
        """Populate and show the window near the cursor."""
        self._clear()
        self._current_word = result.word
        self._current_result = result
        self._action_status.clear()
        self._wordbook_btn.setText("加入生词本")
        self._wordbook_btn.setEnabled(True)
        self._main_btn.setEnabled(True)
        self._word_label.setText(result.word)
        phonetic_parts = []
        if result.phonetic_us:
            phonetic_parts.append(f"美 /{result.phonetic_us}/")
        if result.phonetic_uk:
            phonetic_parts.append(f"英 /{result.phonetic_uk}/")
        self._phonetic_label.setText("  ".join(phonetic_parts))

        meaning_font = QFont("Sans", self._font_size)
        for d in result.definitions[:3]:
            row = QHBoxLayout()
            pos = QLabel(d.pos)
            pos.setObjectName("PosLabel")
            meaning = QLabel(d.meaning)
            meaning.setObjectName("MeaningLabel")
            meaning.setWordWrap(True)
            meaning.setFont(meaning_font)
            row.addWidget(pos)
            row.addWidget(meaning, 1)
            self._defs_layout.addLayout(row)

        for ex in result.examples[:1]:
            en = QLabel(ex.en)
            en.setObjectName("ExampleEn")
            en.setWordWrap(True)
            en.setFont(QFont("Sans", self._font_size - 1))
            zh = QLabel(ex.zh)
            zh.setObjectName("ExampleZh")
            zh.setWordWrap(True)
            self._examples_layout.addWidget(en)
            self._examples_layout.addWidget(zh)

        if len(result.definitions) > 3 or len(result.examples) > 1:
            self._action_status.setText("主窗口可查看完整释义和全部例句。")

        source_text = f"来源：{result.source}" if result.source else ""
        self._source_label.setText(source_text)
        self._error_label.hide()

        self.adjustSize()
        self._move_near_cursor()
        self.show()
        self.raise_()
        self.activateWindow()
        self._close_timer.start(self._auto_close_delay_ms)

    def show_error(self, word: str, message: str) -> None:
        self._clear()
        self._word_label.setText(word)
        self._phonetic_label.clear()
        self._source_label.clear()
        self._current_word = word
        self._current_result = None
        self._action_status.clear()
        self._wordbook_btn.setEnabled(False)
        self._main_btn.setEnabled(False)
        self._error_label.setText(message)
        self._error_label.show()
        self.adjustSize()
        self._move_near_cursor()
        self.show()
        self.raise_()
        self.activateWindow()
        # Errors need more time to read than a normal result.
        self._close_timer.start(max(2000, self._auto_close_delay_ms))

    # ---- Helpers -------------------------------------------------------------

    def _clear(self) -> None:
        # Clear definitions
        while self._defs_layout.count():
            item = self._defs_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            else:
                sub = item.layout()
                if sub:
                    while sub.count():
                        sub_item = sub.takeAt(0)
                        sw = sub_item.widget()
                        if sw:
                            sw.deleteLater()
        # Clear examples
        while self._examples_layout.count():
            item = self._examples_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _move_near_cursor(self) -> None:
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if screen is None:
            screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = cursor_pos.x() + 16
        y = cursor_pos.y() + 16
        # Avoid right/bottom edges.
        if x + self.width() > geo.right() - 8:
            x = cursor_pos.x() - self.width() - 16
        if y + self.height() > geo.bottom() - 8:
            y = cursor_pos.y() - self.height() - 16
        self.move(max(geo.left(), x), max(geo.top(), y))

    # ---- Events --------------------------------------------------------------

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate:
            self._close_timer.start(self._auto_close_delay_ms)
        return super().event(event)

    def enterEvent(self, event) -> None:
        self._close_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._close_timer.start(self._auto_close_delay_ms)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def _on_star(self) -> None:
        """Add current word to the wordbook."""
        if not self._current_word:
            return
        if not self._wordbook:
            self._action_status.setText("生词本未启用。")
        elif self._wordbook.contains(self._current_word):
            self._action_status.setText("该单词已在生词本中。")
            self._wordbook_btn.setText("已在生词本")
        elif self._wordbook.add(self._current_word):
            self._action_status.setText("已加入生词本。")
            self._wordbook_btn.setText("已加入生词本")
        else:
            self._action_status.setText("保存失败，请查看应用日志。")

    def _on_show_main(self) -> None:
        if self._current_result and self._main_window_callback:
            self._close_timer.stop()
            self._main_window_callback(self._current_result)

    def _on_pronounce(self) -> None:
        if not self._current_word or not self._pronunciation_callback:
            return
        self._action_status.setText("正在获取读音；不可用时将使用离线语音…")
        self._pronunciation_callback(self._current_word)

    def show_pronunciation_error(self, message: str) -> None:
        self._action_status.setText(f"发音失败：{message}")
