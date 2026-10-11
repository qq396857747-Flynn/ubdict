"""Core data models for UbDict."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Example(BaseModel):
    """An example sentence pair."""

    en: str = ""
    zh: str = ""


class Definition(BaseModel):
    """A dictionary sense with optional English gloss and examples."""

    pos: str = ""
    meaning: str = ""
    usage: str = ""
    english_meaning: str = ""
    examples: list[Example] = Field(default_factory=list)


class PhraseGroup(BaseModel):
    """A named group of common collocations."""

    label: str = ""
    phrases: list[str] = Field(default_factory=list)


class Translation(BaseModel):
    """A complete translation result for a word."""

    word: str
    phonetic_us: str | None = None  # 美音音标
    phonetic_uk: str | None = None  # 英音音标
    definitions: list[Definition] = Field(default_factory=list)
    detailed_definitions: list[Definition] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    word_forms: list[str] = Field(default_factory=list)
    collocations: list[PhraseGroup] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)
    bing_details_loaded: bool = False
    source: str = ""  # 来源标识: bing / youdao / local
    audio_us_url: str | None = None
    audio_uk_url: str | None = None

    @property
    def is_empty(self) -> bool:
        """Whether this result contains no usable content."""
        return not (
            self.definitions
            or self.detailed_definitions
            or self.examples
            or self.word_forms
            or self.collocations
            or self.antonyms
        )

    @classmethod
    def empty(cls, word: str, source: str = "") -> Translation:
        return cls(word=word, source=source)
