"""Main window for searching, reviewing history, and reading translations."""
from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QFrame,
    QScrollArea,
)

from ubdict.core.models import Definition, Example, Translation
from ubdict.storage.history import HistoryStore
from ubdict.storage.wordbook import WordbookStore


class MainWindow(QWidget):
    """Search window with query history and full translation details."""

    query_requested = pyqtSignal(str, int)

    def __init__(self, history: HistoryStore, wordbook: WordbookStore) -> None:
        super().__init__()
        self._history = history
        self._wordbook = wordbook
        self._requested_word = ""
        self._request_id = 0
        self._current_translation: Translation | None = None
        self._pronunciation_callback: Callable[[str], None] | None = None
        self.setWindowTitle("UbDict")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(880, 620)

        root = QVBoxLayout(self)
        content = QHBoxLayout()
        root.addLayout(content, 1)

        sidebar = QFrame()
        sidebar.setMinimumWidth(230)
        sidebar.setMaximumWidth(290)
        sidebar_layout = QVBoxLayout(sidebar)
        search_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("输入英文单词查询…")
        self._input.returnPressed.connect(self._on_query)
        search_row.addWidget(self._input, 1)
        query_button = QPushButton("查询")
        query_button.clicked.connect(self._on_query)
        search_row.addWidget(query_button)
        sidebar_layout.addLayout(search_row)
        sidebar_layout.addWidget(QLabel("最近查询："))
        self._history_list = QListWidget()
        self._history_list.itemDoubleClicked.connect(self._on_history_click)
        sidebar_layout.addWidget(self._history_list, 1)
        content.addWidget(sidebar)

        detail_panel = QFrame()
        detail_layout = QVBoxLayout(detail_panel)
        detail_header = QHBoxLayout()
        self._word_label = QLabel("翻译详情")
        self._word_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        detail_header.addWidget(self._word_label, 1)
        self._add_word_button = QPushButton("加入生词本")
        self._add_word_button.setEnabled(False)
        self._add_word_button.clicked.connect(self._add_current_word)
        detail_header.addWidget(self._add_word_button)
        detail_layout.addLayout(detail_header)

        self._phonetic_label = QLabel()
        self._phonetic_label.setStyleSheet("color: #5577aa;")
        phonetic_row = QHBoxLayout()
        phonetic_row.addWidget(self._phonetic_label, 1)
        self._pronounce_btn = QPushButton("🔊 播放读音")
        self._pronounce_btn.setToolTip("播放单词读音（离线语音）")
        self._pronounce_btn.setEnabled(False)
        self._pronounce_btn.clicked.connect(self._on_pronounce)
        phonetic_row.addWidget(self._pronounce_btn)
        detail_layout.addLayout(phonetic_row)

        self._detail_status = QLabel("选择左侧历史记录，或输入单词开始查询。")
        self._detail_status.setWordWrap(True)
        detail_layout.addWidget(self._detail_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._details = QWidget()
        self._details_layout = QVBoxLayout(self._details)
        self._details_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._details)
        detail_layout.addWidget(scroll, 1)

        self._source_label = QLabel()
        self._source_label.setWordWrap(True)
        self._source_label.setStyleSheet("color: #777;")
        detail_layout.addWidget(self._source_label)
        self._wordbook_status = QLabel()
        self._wordbook_status.setStyleSheet("color: #477a3d;")
        detail_layout.addWidget(self._wordbook_status)
        content.addWidget(detail_panel, 1)

        self._refresh_history()

    def _on_query(self) -> None:
        word = self._input.text().strip()
        if word:
            self._request_id += 1
            self._requested_word = word
            self._current_translation = None
            self._word_label.setText(word)
            self._phonetic_label.clear()
            self._source_label.clear()
            self._wordbook_status.clear()
            self._detail_status.setText("正在查询…")
            self._add_word_button.setEnabled(False)
            self._pronounce_btn.setEnabled(False)
            self._clear_details()
            self.query_requested.emit(word, self._request_id)

    def _on_history_click(self, item) -> None:
        word = item.data(Qt.ItemDataRole.UserRole)
        if not word:
            word = item.text().split("  ")[0].strip()
        if word:
            self._input.setText(word)
            self._on_query()

    def show_query_translation(self, request_id: int, result: Translation) -> None:
        """Display a result only if it belongs to the current main-window query."""
        if (
            request_id != self._request_id
            or result.word.casefold() != self._requested_word.casefold()
        ):
            return
        self._render_translation(result)
        self._refresh_history()

    def show_translation_error(
        self, request_id: int, word: str, message: str
    ) -> None:
        """Show an error only if it belongs to the current main-window query."""
        if (
            request_id != self._request_id
            or word.casefold() != self._requested_word.casefold()
        ):
            return
        self._current_translation = None
        self._phonetic_label.clear()
        self._source_label.clear()
        self._clear_details()
        self._detail_status.setText(f"查询失败：{message}")
        self._add_word_button.setEnabled(False)
        self._pronounce_btn.setEnabled(False)

    def show_translation(self, result: Translation) -> None:
        """Display a supplied result and bring the main window forward."""
        self._request_id += 1
        self._input.setText(result.word)
        self._requested_word = result.word
        self._render_translation(result)
        self._refresh_history()
        self.show()
        self.raise_()
        self.activateWindow()

    def set_pronunciation_callback(self, callback: Callable[[str], None]) -> None:
        self._pronunciation_callback = callback

    def _on_pronounce(self) -> None:
        if self._current_translation and self._pronunciation_callback:
            self._detail_status.setText("正在获取读音；不可用时将使用离线语音…")
            self._pronunciation_callback(self._current_translation.word)

    def show_pronunciation_error(self, message: str) -> None:
        self._detail_status.setText(f"发音失败：{message}")

    def _render_translation(self, result: Translation) -> None:
        self._current_translation = result
        self._word_label.setText(result.word)
        self._wordbook_status.clear()
        self._add_word_button.setEnabled(True)

        phonetics = []
        if result.phonetic_us:
            phonetics.append(f"美音 /{result.phonetic_us}/")
        if result.phonetic_uk:
            phonetics.append(f"英音 /{result.phonetic_uk}/")
        self._phonetic_label.setText("    ".join(phonetics))
        self._pronounce_btn.setEnabled(True)

        self._clear_details()
        if result.definitions:
            self._add_section_title("简明释义")
            for definition in result.definitions:
                self._add_text(definition.meaning, definition.pos)
        if result.word_forms:
            self._add_section_title("词形变化")
            for word_form in result.word_forms:
                self._add_text(word_form)
        if result.collocations:
            self._add_section_title("常用搭配")
            for group in result.collocations:
                self._add_text("、".join(group.phrases), group.label)
        if result.antonyms:
            self._add_section_title("反义词")
            self._add_text("、".join(result.antonyms))
        if result.detailed_definitions:
            self._add_section_title("详细释义")
            for definition in result.detailed_definitions:
                self._render_detailed_definition(definition)
        if result.examples and (
            not result.detailed_definitions
            or not any(
                definition.examples for definition in result.detailed_definitions
            )
        ):
            self._add_section_title("例句")
            for example in result.examples:
                self._render_example(example)

        has_content = bool(
            result.definitions
            or result.detailed_definitions
            or result.examples
            or result.word_forms
            or result.collocations
            or result.antonyms
        )
        self._detail_status.setText(
            (
                "已显示词典返回的释义、词形、搭配、反义词与例句。"
                if has_content
                else "当前词条没有释义或例句。"
            )
        )
        self._source_label.setText(
            f"词典来源：{result.source}" if result.source else ""
        )

    def _render_detailed_definition(self, definition: Definition) -> None:
        meaning = definition.meaning
        if definition.usage:
            meaning = f"{meaning}  {definition.usage}".strip()
        self._add_text(meaning, definition.pos)
        if definition.english_meaning:
            self._add_text(definition.english_meaning, style="color: #666;")
        for example in definition.examples:
            self._render_example(example)

    def _render_example(self, example: Example) -> None:
        self._add_text(example.en, style="margin-left: 18px;")
        if example.zh:
            self._add_text(example.zh, style="color: #666; margin-left: 18px;")

    def _add_text(self, text: str, prefix: str = "", style: str = "") -> None:
        label = QLabel(f"{prefix}  {text}" if prefix else text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if style:
            label.setStyleSheet(style)
        self._details_layout.addWidget(label)

    def _add_section_title(self, text: str) -> None:
        title = QLabel(text)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-top: 8px;")
        self._details_layout.addWidget(title)

    def _clear_details(self) -> None:
        while self._details_layout.count():
            item = self._details_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _add_current_word(self) -> None:
        if not self._current_translation:
            return
        word = self._current_translation.word
        if self._wordbook.contains(word):
            self._wordbook_status.setText("该单词已在生词本中。")
        elif self._wordbook.add(word):
            self._wordbook_status.setText("已加入生词本。")
        else:
            self._wordbook_status.setText("保存失败，请查看应用日志。")

    def _refresh_history(self) -> None:
        self._history_list.clear()
        for row in self._history.recent(50):
            item = QListWidgetItem(f"{row['word']}  ({row.get('source', '')})")
            item.setData(Qt.ItemDataRole.UserRole, row["word"])
            self._history_list.addItem(item)

    def showEvent(self, event) -> None:
        self._refresh_history()
        super().showEvent(event)
