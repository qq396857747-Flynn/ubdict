"""Bing Dictionary adapter (cn.bing.com/dict).

Bing has no official public API; we parse the HTML response. The page
structure is stable enough for v1; we degrade gracefully on layout changes.
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx
from loguru import logger
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ubdict.core.models import Definition, Example, PhraseGroup, Translation
from ubdict.core.translate.base import TranslateAdapter

_BING_URL = "https://cn.bing.com/dict/search?q={word}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}
_TIMEOUT = 5.0


class BingAdapter(TranslateAdapter):
    name = "bing"

    def __init__(self, timeout: float = _TIMEOUT) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def set_timeout(self, timeout: float) -> None:
        """Update the timeout and close the previous client on its event loop."""
        self._timeout = timeout
        client = self._client
        self._client = None
        if client and not client.is_closed:
            await client.aclose()

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the HTTP client bound to the current event loop."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_HEADERS,
                timeout=self._timeout,
                follow_redirects=True,
                max_redirects=3,
            )
        return self._client

    async def translate(self, word: str) -> Translation | None:
        url = _BING_URL.format(word=quote(word))
        client = self._get_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"Bing request failed for {word!r}: {e}")
            raise

        html = resp.text
        if not self._has_result(html):
            logger.debug(f"Bing: no result for {word!r}")
            return None

        phonetic_us = self._extract_phonetic(html, "美")
        phonetic_uk = self._extract_phonetic(html, "英")
        definitions = self._extract_definitions(html)
        detailed_definitions = self._extract_detailed_definitions(html)
        examples = self._extract_examples(html)
        word_forms = self._extract_word_forms(html)
        collocations = self._extract_collocations(html)
        antonyms = self._extract_antonyms(html)

        if not (
            definitions
            or detailed_definitions
            or examples
            or word_forms
            or collocations
            or antonyms
        ):
            return None

        return Translation(
            word=word,
            phonetic_us=phonetic_us,
            phonetic_uk=phonetic_uk,
            definitions=definitions,
            detailed_definitions=detailed_definitions,
            examples=examples,
            word_forms=word_forms,
            collocations=collocations,
            antonyms=antonyms,
            bing_details_loaded=bool(detailed_definitions),
            source=self.name,
        )

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ---- HTML parsing helpers -------------------------------------------------

    @staticmethod
    def _has_result(html: str) -> bool:
        # Bing shows "没有找到" when no entry exists.
        return "def_fl" in html or "qdef" in html

    @staticmethod
    def _extract_phonetic(html: str, label: str) -> str | None:
        """Extract phonetic transcription from Bing HTML.

        Actual Bing structure:
            <div class="hd_prUS b_primtxt">美&#160;[heˈləʊ] </div>
            <div class="hd_pr b_primtxt">英国&#160;[həˈləʊ] </div>
        `label` is "美" (US) or "英" (UK).
        """
        # hd_prUS = 美音, hd_pr (without US) = 英音
        if label == "美":
            cls = "hd_prUS"
        else:
            cls = r"hd_pr\b(?!US)"  # hd_pr but not hd_prUS
        pattern = (
            rf'class="[^"]*{cls}[^"]*"[^>]*>\s*[^<]*?&#160;\[([^\]]+)\]'
        )
        m = re.search(pattern, html)
        if m:
            return m.group(1).strip()
        # Fallback: some pages use /.../  instead of [...]
        pattern2 = (
            rf'class="[^"]*{cls}[^"]*"[^>]*>\s*[^<]*?&#160;/([^/<]+)/'
        )
        m = re.search(pattern2, html)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _extract_definitions(html: str) -> list[Definition]:
        """Extract part-of-speech + meaning entries from the def list."""
        defs: list[Definition] = []
        tree = HTMLParser(html)
        # Bing structure: <div class="qdef"> <ul> <li> <span class="pos">n.</span>
        # <span class="def">meaning</span> </li> ... </ul> </div>
        for li in tree.css("div.qdef ul li"):
            pos_node = li.css_first("span.pos")
            def_node = li.css_first("span.def")
            pos = pos_node.text(strip=True) if pos_node else ""
            meaning = def_node.text(strip=True) if def_node else ""
            if meaning:
                defs.append(Definition(pos=pos, meaning=meaning))
        return defs

    @staticmethod
    def _extract_examples(html: str) -> list[Example]:
        """Extract example sentence pairs for the full translation view."""
        examples: list[Example] = []
        tree = HTMLParser(html)
        for node in tree.css("#authid .li_ex"):
            en_node = node.css_first(".val_ex")
            zh_node = node.css_first(".bil_ex")
            en_text = BingAdapter._read_text(en_node, preserve_english_spacing=True)
            zh_text = zh_node.text(strip=True) if zh_node else ""
            if en_text and zh_text:
                examples.append(Example(en=en_text, zh=zh_text))
            if len(examples) >= 10:
                return examples

        if examples:
            return examples

        # Older Bing layouts used dedicated sentence classes.
        en_nodes = tree.css("div.senEn")
        zh_nodes = tree.css("div.SenS")
        for en, zh in zip(en_nodes, zh_nodes):
            en_text = BingAdapter._read_text(en, preserve_english_spacing=True)
            zh_text = zh.text(strip=True)
            if en_text and zh_text:
                examples.append(Example(en=en_text, zh=zh_text))
            if len(examples) >= 10:
                break
        return examples

    @staticmethod
    def _extract_detailed_definitions(html: str) -> list[Definition]:
        """Extract detailed senses and their examples from Bing's word entry."""
        tree = HTMLParser(html)
        definitions: list[Definition] = []
        example_count = 0
        for pos_group in tree.css("#authid .li_pos"):
            pos_node = pos_group.css_first(".pos")
            pos = pos_node.text(strip=True) if pos_node else ""
            for row in pos_group.css(".def_row"):
                definition_node = row.css_first(".de_co")
                if definition_node:
                    meaning_node = definition_node.css_first(".bil")
                    english_node = definition_node.css_first(".val")
                    usage_node = definition_node.css_first(".gra")
                    meaning = meaning_node.text(strip=True) if meaning_node else ""
                    english_meaning = (
                        BingAdapter._read_text(
                            english_node, preserve_english_spacing=True
                        )
                    )
                    if meaning or english_meaning:
                        definitions.append(
                            Definition(
                                pos=pos,
                                meaning=meaning,
                                usage=usage_node.text(strip=True) if usage_node else "",
                                english_meaning=english_meaning,
                            )
                        )
                example_node = row.css_first(".li_ex")
                if example_node and definitions and example_count < 10:
                    en_node = example_node.css_first(".val_ex")
                    zh_node = example_node.css_first(".bil_ex")
                    en = BingAdapter._read_text(
                        en_node, preserve_english_spacing=True
                    )
                    zh = zh_node.text(strip=True) if zh_node else ""
                    if en and zh:
                        definitions[-1].examples.append(Example(en=en, zh=zh))
                        example_count += 1
        return definitions

    @staticmethod
    def _read_text(node, *, preserve_english_spacing: bool = False) -> str:
        if node is None:
            return ""
        separator = " " if preserve_english_spacing else ""
        text = " ".join(node.text(separator=separator, strip=True).split())
        if preserve_english_spacing:
            text = re.sub(r"\s+([,.;:!?])", r"\1", text)
            text = re.sub(r"([\(\[\{])\s+", r"\1", text)
        return text

    @staticmethod
    def _extract_word_forms(html: str) -> list[str]:
        tree = HTMLParser(html)
        return [
            text
            for node in tree.css(".qdef .hd_div1")
            if (text := node.text(strip=True))
        ]

    @staticmethod
    def _extract_collocations(html: str) -> list[PhraseGroup]:
        tree = HTMLParser(html)
        groups: list[PhraseGroup] = []
        for node in tree.css("#colid .df_div2"):
            title_node = node.css_first(".de_title2")
            label = title_node.text(strip=True) if title_node else ""
            phrases = [
                phrase
                for link in node.css(".col_fl a")
                if (phrase := link.text(strip=True))
            ]
            if phrases:
                groups.append(PhraseGroup(label=label, phrases=phrases))
        return groups

    @staticmethod
    def _extract_antonyms(html: str) -> list[str]:
        tree = HTMLParser(html)
        return [
            text
            for node in tree.css("#antoid .col_fl a")
            if (text := node.text(strip=True))
        ]
