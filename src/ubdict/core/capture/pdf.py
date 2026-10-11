"""PDF capture engine.

Two modes:
  A) Passive: PDF readers (Evince/Okular) write selected text to PRIMARY
     selection, so the TextCapture engine already handles them. No extra
     code needed.

  B) Active: An embedded PDF viewer (PdfViewer widget) that renders pages
     via PyMuPDF and supports hover-based word extraction:
       - If the PDF has a text layer, extract the word at the hover point.
       - If no text layer (scanned PDF), fall back to OCR on the rendered
         page region around the cursor. OCR runs on a background thread so
         the GUI does not freeze.

This module provides:
  - PdfDocument: loads a PDF, exposes page rendering and text extraction.
  - PdfViewer: QWidget that displays a page and emits word_captured on hover.
"""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QMouseEvent, QPainter, QColor, QFont
from PyQt6.QtWidgets import QWidget, QScrollArea

from loguru import logger

from ubdict.core.capture.ocr import OcrEngine, OcrResult
from ubdict.core.event_bus import bus

# Hover delay for PDF word extraction.
_HOVER_DELAY = 1.5  # seconds (shorter than image capture — text layer is fast)
# OCR region around cursor for scanned PDFs (in page pixels).
_OCR_REGION = 200, 80


class PdfDocument:
    """Wrapper around a PyMuPDF document for rendering and text extraction."""

    def __init__(self, path: str | Path) -> None:
        import fitz  # PyMuPDF

        self._doc = fitz.open(str(path))
        self._path = Path(path)
        logger.info(f"PdfDocument opened: {self._path} ({self.page_count} pages)")

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    @property
    def path(self) -> Path:
        return self._path

    def render_page(self, page_num: int, zoom: float = 1.5) -> bytes:
        """Render a page to PNG bytes at the given zoom factor."""
        if not (0 <= page_num < self.page_count):
            raise IndexError(f"page_num {page_num} out of range [0,{self.page_count})")
        import fitz

        page = self._doc[page_num]
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")

    def extract_word_at(self, page_num: int, x: float, y: float, zoom: float = 1.5) -> str | None:
        """Extract the word at (x, y) in rendered-pixel coordinates.

        Returns the word text, or None if no text layer at that point.
        """
        if not (0 <= page_num < self.page_count):
            return None
        page = self._doc[page_num]
        # Convert rendered pixels back to PDF points.
        pdf_x = x / zoom
        pdf_y = y / zoom
        # get_text("words") returns list of (x0, y0, x1, y1, word, block, line, word_no)
        words = page.get_text("words")
        for x0, y0, x1, y1, word, *_ in words:
            if x0 <= pdf_x <= x1 and y0 <= pdf_y <= y1:
                cleaned = word.strip()
                if cleaned and cleaned.isalpha():
                    return cleaned
        return None

    def has_text_layer(self, page_num: int) -> bool:
        """Check if a page has extractable text."""
        if not (0 <= page_num < self.page_count):
            return False
        page = self._doc[page_num]
        text = page.get_text("text").strip()
        return len(text) > 10  # arbitrary threshold

    def close(self) -> None:
        self._doc.close()


class PdfViewer(QWidget):
    """Embedded PDF page viewer with hover-based word extraction.

    Signals
    -------
    word_hovered(str)
        Emitted when a word is extracted after hovering (text layer or OCR).
    """

    word_hovered = pyqtSignal(str)
    _hover_trigger = pyqtSignal(int, int)
    _word_done = pyqtSignal(object)  # (word, QPoint)

    def __init__(self, document: PdfDocument, ocr_engine: OcrEngine | None = None) -> None:
        super().__init__()
        self._doc = document
        self._ocr = ocr_engine
        self._page_num = 0
        self._zoom = 1.5
        self._pixmap: QPixmap | None = None
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._check_hover)
        self._last_pos: QPoint | None = None
        self._hover_fired_pos: QPoint | None = None
        self._ocr_busy = False
        self._doc_lock = threading.Lock()
        self._word_done.connect(self._on_word_done)

        self.setMouseTracking(True)
        self._load_page(0)

        # Minimum size based on page dimensions.
        if self._pixmap:
            self.setMinimumSize(self._pixmap.size())

    def _load_page(self, page_num: int) -> None:
        if not (0 <= page_num < self._doc.page_count):
            return
        self._page_num = page_num
        with self._doc_lock:
            png = self._doc.render_page(page_num, self._zoom)
        image = QImage()
        image.loadFromData(png, "PNG")
        self._pixmap = QPixmap.fromImage(image)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self._pixmap:
            painter.drawPixmap(0, 0, self._pixmap)
        else:
            painter.fillRect(self.rect(), QColor("#444"))
            painter.setPen(QColor("#888"))
            painter.setFont(QFont("Sans", 14))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No page")
        painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._last_pos = event.position().toPoint()
        self._hover_fired_pos = None
        self._hover_timer.start(int(_HOVER_DELAY * 1000))

    def _check_hover(self) -> None:
        if self._last_pos is None:
            return
        if self._hover_fired_pos == self._last_pos:
            return  # Already fired for this position.
        if self._ocr_busy:
            return

        pos = self._last_pos
        # Try the text layer first (fast, on the GUI thread).
        word = self._doc.extract_word_at(self._page_num, pos.x(), pos.y(), self._zoom)
        if word:
            self._hover_fired_pos = pos
            self.word_hovered.emit(word)
            bus.word_captured.emit(word)
            return

        # Fall back to OCR for scanned PDFs, off the GUI thread.
        if not self._ocr:
            return
        self._ocr_busy = True
        threading.Thread(
            target=self._ocr_hover_worker,
            args=(pos.x(), pos.y(), pos),
            name="pdf-ocr",
            daemon=True,
        ).start()

    def _ocr_hover_worker(self, x: int, y: int, pos: QPoint) -> None:
        word = self._ocr_fallback(x, y)
        self._word_done.emit((word, pos))

    def _on_word_done(self, result) -> None:
        self._ocr_busy = False
        word, pos = result
        if word:
            self._hover_fired_pos = pos
            self.word_hovered.emit(word)
            bus.word_captured.emit(word)

    def _ocr_fallback(self, x: int, y: int) -> str | None:
        """OCR a region around (x, y) on the rendered page (worker thread)."""
        w, h = _OCR_REGION
        try:
            with self._doc_lock:
                png = self._doc.render_page(self._page_num, self._zoom)
        except Exception as e:
            logger.debug(f"PDF OCR render failed: {e}")
            return None
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(png))
            left = max(0, x - w // 2)
            top = max(0, y - h // 2)
            right = min(img.width, left + w)
            bottom = min(img.height, top + h)
            cropped = img.crop((left, top, right, bottom))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            results = self._ocr.recognize(buf.getvalue())
        except Exception as e:
            logger.debug(f"PDF OCR fallback failed: {e}")
            return None
        if not results:
            return None
        # Pick nearest word to crop center.
        target = ((right - left) // 2, (bottom - top) // 2)
        best = min(results, key=lambda r: (r.center[0] - target[0]) ** 2 + (r.center[1] - target[1]) ** 2)
        return best.text if best and best.text.isalpha() else None

    def next_page(self) -> None:
        if self._page_num < self._doc.page_count - 1:
            self._load_page(self._page_num + 1)

    def prev_page(self) -> None:
        if self._page_num > 0:
            self._load_page(self._page_num - 1)

    @property
    def current_page(self) -> int:
        return self._page_num

    @property
    def page_count(self) -> int:
        return self._doc.page_count
