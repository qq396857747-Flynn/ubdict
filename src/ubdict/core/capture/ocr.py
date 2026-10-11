"""OCR engine abstraction.

Wraps Tesseract via pytesseract. Provides a clean interface so the capture
engine does not depend on pytesseract directly, and tests can substitute a
fake OCR engine.
"""
from __future__ import annotations

import io
import shutil
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger

from ubdict.paths import resource_path


class OcrResult:
    """A single OCR-recognized word with bounding box."""

    __slots__ = ("text", "x", "y", "w", "h")

    def __init__(self, text: str, x: int, y: int, w: int, h: int) -> None:
        self.text = text
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


class OcrEngine(ABC):
    """Abstract OCR engine."""

    @abstractmethod
    def recognize(self, image_bytes: bytes, lang: str = "eng") -> list[OcrResult]:
        """Recognize words in `image_bytes` (PNG), return list with positions."""


class TesseractEngine(OcrEngine):
    """Tesseract OCR via pytesseract.

    Requires the `tesseract` system binary and `eng.traineddata` model.
    """

    def __init__(self, min_confidence: int = 60) -> None:
        self._min_confidence = min_confidence
        try:
            import pytesseract
        except ImportError:
            logger.warning("pytesseract not installed")
            return
        bundled_tesseract = resource_path("tools/tesseract/tesseract.exe")
        if sys.platform == "win32" and bundled_tesseract.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(bundled_tesseract)
            self._tessdata_dir = bundled_tesseract.parent / "tessdata"
        else:
            self._tessdata_dir = None
        if not shutil.which("tesseract"):
            if sys.platform == "win32" and bundled_tesseract.is_file():
                return
            logger.warning(
                "tesseract binary not found; install: sudo apt install tesseract-ocr tesseract-ocr-eng"
            )

    def set_min_confidence(self, value: int) -> None:
        self._min_confidence = max(0, min(100, int(value)))

    def recognize(self, image_bytes: bytes, lang: str = "eng") -> list[OcrResult]:
        try:
            from PIL import Image
            import pytesseract
        except ImportError as e:
            logger.error(f"OCR deps missing: {e}")
            return []

        try:
            image = Image.open(io.BytesIO(image_bytes))
            # Get bounding boxes: TSV format
            config = (
                f'--tessdata-dir "{self._tessdata_dir}"'
                if self._tessdata_dir
                else ""
            )
            data = pytesseract.image_to_data(
                image, lang=lang, config=config,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as e:
            logger.error(f"OCR recognize failed: {e}")
            return []

        results: list[OcrResult] = []
        n = len(data["text"])
        for i in range(n):
            text = data["text"][i].strip()
            # Confidence can be int or float string; parse robustly.
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                conf = -1.0
            # Skip empty text and low-confidence (< 60) results.
            if not text or conf < self._min_confidence:
                continue
            # Only keep alphabetic English tokens.
            if not text.isalpha():
                continue
            results.append(
                OcrResult(
                    text=text,
                    x=int(data["left"][i]),
                    y=int(data["top"][i]),
                    w=int(data["width"][i]),
                    h=int(data["height"][i]),
                )
            )
        return results


class FakeOcrEngine(OcrEngine):
    """In-memory OCR engine for testing.

    Returns pre-registered words for any image.
    """

    def __init__(self, words: list[OcrResult] | None = None) -> None:
        self._words = words or []

    def recognize(self, image_bytes: bytes, lang: str = "eng") -> list[OcrResult]:
        return list(self._words)
