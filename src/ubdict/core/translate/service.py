"""Translation service: orchestrates adapters with fallback and caching."""
from __future__ import annotations

import asyncio
import threading

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot

from loguru import logger

from ubdict.core.event_bus import bus
from ubdict.core.models import Translation
from ubdict.core.translate.base import TranslateAdapter
from ubdict.storage.cache import CacheStore
from ubdict.storage.history import HistoryStore


class _Worker(QObject):
    """Runs the async translation in a worker thread.

    A single long-lived event loop is created on the worker thread and reused
    across requests so that adapters (e.g. httpx.AsyncClient) keep their
    connections bound to a live loop. The loop is closed only on shutdown.
    """

    request = pyqtSignal(str, int)
    cleanup = pyqtSignal()
    timeout_changed = pyqtSignal(float)
    cleanup_done = pyqtSignal()
    result_ready = pyqtSignal(object)  # Translation
    error_ready = pyqtSignal(str, str)  # word, message
    main_result_ready = pyqtSignal(int, object)  # request_id, Translation
    main_error_ready = pyqtSignal(int, str, str)  # request_id, word, message

    def __init__(
        self,
        adapters: list[TranslateAdapter],
        cache: CacheStore,
        history: HistoryStore,
    ) -> None:
        super().__init__()
        self._adapters = adapters
        self._cache = cache
        self._history = history
        self._loop: asyncio.AbstractEventLoop | None = None
        self.request.connect(self._run)
        self.cleanup.connect(self._do_cleanup)
        self.timeout_changed.connect(self._set_bing_timeout)

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        return self._loop

    @pyqtSlot(str, int)
    def _run(self, word: str, request_id: int) -> None:
        loop = self._ensure_loop()
        try:
            result = loop.run_until_complete(self._translate(word))
        except Exception as e:
            logger.exception("Translation worker crashed")
            if request_id:
                self.main_error_ready.emit(request_id, word, str(e))
            else:
                self.error_ready.emit(word, str(e))
            return
        if result and not result.is_empty:
            self._history.add(word, result.source)
            if request_id:
                self.main_result_ready.emit(request_id, result)
            else:
                self.result_ready.emit(result)
        else:
            if request_id:
                self.main_error_ready.emit(request_id, word, "未找到释义")
            else:
                self.error_ready.emit(word, "未找到释义")

    @pyqtSlot(float)
    def _set_bing_timeout(self, timeout: float) -> None:
        adapter = next(
            (
                item
                for item in self._adapters
                if getattr(item, "name", None) == "bing"
                and hasattr(item, "set_timeout")
            ),
            None,
        )
        if adapter is not None:
            loop = self._ensure_loop()
            try:
                loop.run_until_complete(adapter.set_timeout(timeout))
            except Exception:
                logger.exception("Failed to update Bing request timeout")

    async def _translate(self, word: str) -> Translation:
        # 1. Cache
        if cached := self._cache.get(word):
            logger.debug(f"Cache hit: {word}")
            if cached.source != "bing" or cached.bing_details_loaded:
                return cached
            bing_adapter = next(
                (adapter for adapter in self._adapters if adapter.name == "bing"),
                None,
            )
            if bing_adapter is None:
                return cached
            try:
                refreshed = await bing_adapter.translate(word)
            except Exception as e:
                logger.warning(
                    f"Could not refresh legacy Bing cache for {word!r}: {e}"
                )
                return cached
            if (
                refreshed
                and not refreshed.is_empty
                and refreshed.bing_details_loaded
            ):
                self._cache.set(word, refreshed)
                logger.info(f"Refreshed legacy Bing cache for {word!r}")
                return refreshed
            return cached
        # 2. Adapters in priority order
        for adapter in self._adapters:
            try:
                result = await adapter.translate(word)
                if result and not result.is_empty:
                    self._cache.set(word, result)
                    logger.info(f"Translated {word!r} via {adapter.name}")
                    return result
            except Exception as e:
                logger.warning(f"Adapter {adapter.name} failed for {word!r}: {e}")
                continue
        return Translation.empty(word)

    @pyqtSlot()
    def _do_cleanup(self) -> None:
        """Close adapters and the event loop (runs on the worker thread)."""
        try:
            loop = self._loop
            if loop is None or loop.is_closed():
                return
            try:
                loop.run_until_complete(self._close_adapters())
            except Exception as e:
                logger.error(f"adapter cleanup error: {e}")
            try:
                loop.close()
            except Exception as e:
                logger.error(f"event loop cleanup error: {e}")
            self._loop = None
        finally:
            self.cleanup_done.emit()

    async def _close_adapters(self) -> None:
        for adapter in self._adapters:
            aclose = getattr(adapter, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception as e:
                    logger.error(f"aclose {adapter.name} failed: {e}")
                continue
            sync_close = getattr(adapter, "close", None)
            if sync_close is not None:
                try:
                    sync_close()
                except Exception as e:
                    logger.error(f"close {adapter.name} failed: {e}")


class TranslateService(QObject):
    """Translation service running queries off the GUI thread."""

    main_query_result = pyqtSignal(int, object)
    main_query_error = pyqtSignal(int, str, str)

    def __init__(
        self,
        adapters: list[TranslateAdapter],
        cache: CacheStore,
        history: HistoryStore,
    ) -> None:
        super().__init__()
        self._adapters = adapters
        self._thread = QThread()
        self._worker = _Worker(adapters, cache, history)
        self._cleanup_complete = threading.Event()
        self._worker.moveToThread(self._thread)
        self._thread.start()
        self._worker.cleanup_done.connect(
            self._cleanup_complete.set, Qt.ConnectionType.DirectConnection
        )

        # Wire worker output signals to the event bus.
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_ready.connect(self._on_error)
        self._worker.main_result_ready.connect(self._on_main_result)
        self._worker.main_error_ready.connect(self._on_main_error)

        # Listen for capture events on the GUI thread.
        bus.word_captured.connect(self.translate)

    def translate(self, word: str) -> None:
        bus.translate_started.emit(word)
        # Emitting a signal connected to a worker in another thread is
        # automatically queued by Qt — no QMetaObject needed.
        self._worker.request.emit(word, 0)

    def translate_for_main(self, word: str, request_id: int) -> None:
        bus.translate_started.emit(word)
        self._worker.request.emit(word, request_id)

    def set_bing_timeout(self, timeout: float) -> None:
        self._worker.timeout_changed.emit(timeout)

    @pyqtSlot(object)
    def _on_result(self, result: Translation) -> None:
        bus.translate_result.emit(result)

    @pyqtSlot(str, str)
    def _on_error(self, word: str, message: str) -> None:
        bus.translate_error.emit(word, message)

    @pyqtSlot(int, object)
    def _on_main_result(self, request_id: int, result: Translation) -> None:
        self.main_query_result.emit(request_id, result)

    @pyqtSlot(int, str, str)
    def _on_main_error(self, request_id: int, word: str, message: str) -> None:
        self.main_query_error.emit(request_id, word, message)

    def shutdown(self) -> None:
        # Ask the worker (on its own thread) to close adapters/loop, then quit.
        self._cleanup_complete.clear()
        self._worker.cleanup.emit()
        if not self._cleanup_complete.wait(3):
            logger.error("Timed out waiting for translation worker cleanup")
        self._thread.quit()
        if not self._thread.wait(3000):
            logger.error("Timed out waiting for translation worker thread to stop")
