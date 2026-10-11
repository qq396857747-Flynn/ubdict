"""PDF viewer window with navigation controls."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QScrollArea,
    QFileDialog,
)

from loguru import logger

from ubdict.core.capture.ocr import OcrEngine
from ubdict.core.capture.pdf import PdfDocument, PdfViewer


class PdfWindow(QWidget):
    """Standalone PDF viewer window with hover word extraction."""

    def __init__(self, ocr_engine: OcrEngine | None = None) -> None:
        super().__init__()
        self.setWindowTitle("UbDict - PDF 取词")
        self.resize(900, 700)
        self._ocr = ocr_engine
        self._doc: PdfDocument | None = None
        self._viewer: PdfViewer | None = None

        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()
        self._btn_open = QPushButton("打开 PDF")
        self._btn_open.clicked.connect(self._open_file)
        toolbar.addWidget(self._btn_open)

        self._btn_prev = QPushButton("上一页")
        self._btn_prev.clicked.connect(self._prev_page)
        self._btn_prev.setEnabled(False)
        toolbar.addWidget(self._btn_prev)

        self._btn_next = QPushButton("下一页")
        self._btn_next.clicked.connect(self._next_page)
        self._btn_next.setEnabled(False)
        toolbar.addWidget(self._btn_next)

        self._page_label = QLabel("未打开")
        toolbar.addWidget(self._page_label, 1)
        layout.addLayout(toolbar)

        # Scroll area for the PDF page
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._scroll, 1)

        # Placeholder
        self._placeholder = QLabel("点击「打开 PDF」选择文件\n\n鼠标悬停在英文单词上 1.5 秒自动取词")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidget(self._placeholder)

    def open_path(self, path: str | Path) -> bool:
        """Open a PDF file. Returns True on success."""
        try:
            new_doc = PdfDocument(path)
        except Exception as e:
            logger.error(f"Failed to open PDF {path}: {e}")
            return False
        # Close the previous document to release its file handle.
        if self._doc:
            self._doc.close()
        self._doc = new_doc
        if self._viewer:
            self._viewer.deleteLater()
        self._viewer = PdfViewer(self._doc, self._ocr)
        self._scroll.setWidget(self._viewer)
        self._btn_prev.setEnabled(True)
        self._btn_next.setEnabled(True)
        self._update_page_label()
        return True

    def _open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 PDF 文件", "", "PDF 文件 (*.pdf)"
        )
        if path:
            self.open_path(path)

    def _prev_page(self) -> None:
        if self._viewer:
            self._viewer.prev_page()
            self._update_page_label()

    def _next_page(self) -> None:
        if self._viewer:
            self._viewer.next_page()
            self._update_page_label()

    def _update_page_label(self) -> None:
        if self._viewer:
            self._page_label.setText(
                f"第 {self._viewer.current_page + 1} / {self._viewer.page_count} 页"
            )

    def closeEvent(self, event) -> None:
        if self._doc:
            self._doc.close()
        super().closeEvent(event)
