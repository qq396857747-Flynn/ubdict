"""Base class for translation adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ubdict.core.models import Translation


class TranslateAdapter(ABC):
    """Abstract translation source adapter."""

    name: str = "base"

    @abstractmethod
    async def translate(self, word: str) -> Translation | None:
        """Query the source for `word`.

        Returns a Translation on success, None if the word is not found
        or the source is unavailable. Raises on transient errors so the
        service can fall back to the next adapter.
        """
