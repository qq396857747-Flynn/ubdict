"""Base class for capture engines."""
from __future__ import annotations

from abc import ABC, abstractmethod


class CaptureEngine(ABC):
    """Abstract capture engine."""

    name: str = "base"

    @abstractmethod
    def start(self) -> None:
        """Begin capturing."""

    @abstractmethod
    def stop(self) -> None:
        """Stop capturing."""
