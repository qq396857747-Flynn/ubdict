"""Wordbook (vocabulary notebook) window."""
from __future__ import annotations

import csv
import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QLabel,
    QInputDialog,
    QFileDialog,
    QMessageBox,
)

from loguru import logger

from ubdict.core.event_bus import bus
from ubdict.storage.wordbook import WordbookStore


class WordbookWindow(QWidget):
    """Window to view and manage saved words."""

    def __init__(self, store: WordbookStore) -> None:
        super().__init__()
        self._store = store
        self.setWindowTitle("UbDict - 生词本")
        self.resize(500, 600)

        layout = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        self._count_label = QLabel()
        header.addWidget(self._count_label, 1)
        layout.addLayout(header)

        # Word list
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_query)
        layout.addWidget(self._list, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_query = QPushButton("查询")
        btn_query.clicked.connect(self._on_query)
        btn_row.addWidget(btn_query)

        btn_remove = QPushButton("删除")
        btn_remove.clicked.connect(self._on_remove)
        btn_row.addWidget(btn_remove)

        btn_export = QPushButton("导出 CSV")
        btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(btn_export)

        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        words = self._store.list_all()
        total = self._store.count()
        suffix = f"（仅显示最近 {len(words)} 个）" if total > len(words) else ""
        self._count_label.setText(f"共 {total} 个生词{suffix}")
        for w in words:
            self._list.addItem(f"{w['word']}")

    def refresh(self) -> None:
        """Refresh the list after changes made elsewhere in the application."""
        self._refresh()

    def add_current(self, word: str) -> None:
        """Add a word and show confirmation."""
        if self._store.add(word):
            logger.info(f"Added to wordbook: {word}")
            self._refresh()
        else:
            logger.debug(f"Already in wordbook: {word}")

    def _on_query(self) -> None:
        item = self._list.currentItem()
        if item:
            word = item.text().strip()
            if word:
                bus.word_captured.emit(word)

    def _on_remove(self) -> None:
        item = self._list.currentItem()
        if item:
            word = item.text().strip()
            self._store.remove(word)
            self._refresh()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出生词本", "wordbook.csv", "CSV 文件 (*.csv)"
        )
        if path:
            try:
                count = self._store.export_csv(path)
            except (OSError, sqlite3.Error, csv.Error) as e:
                QMessageBox.critical(self, "导出失败", str(e))
                return
            QMessageBox.information(self, "导出成功", f"已导出 {count} 个生词到 {path}")

    def showEvent(self, event) -> None:
        self._refresh()
        super().showEvent(event)
