"""Unit test: TranslateService reuses one event loop across requests so that
adapters keeping state (e.g. httpx.AsyncClient) keep working on the 2nd+ call.

Regression for the asyncio.run-per-request bug where the BingAdapter's client
was bound to a closed loop and every request after the first failed with
"Event loop is closed".
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import asyncio
import threading

import pytest
from PyQt6.QtWidgets import QApplication

from ubdict.core.event_bus import bus
from ubdict.core.models import Definition, Translation
from ubdict.core.translate.base import TranslateAdapter
from ubdict.core.translate.service import TranslateService
from ubdict.storage.cache import CacheStore
from ubdict.storage.db import get_db
from ubdict.storage.history import HistoryStore


class CountingAdapter(TranslateAdapter):
    """Records the event loop used for each call."""

    name = "counting"

    def __init__(self) -> None:
        self.calls = 0
        self.loop_ids: list[int] = []
        self.thread_ids: list[int] = []
        self.close_thread: int | None = None

    async def translate(self, word: str) -> Translation | None:
        self.calls += 1
        self.loop_ids.append(id(asyncio.get_event_loop()))
        self.thread_ids.append(threading.get_ident())
        return Translation(
            word=word,
            definitions=[Definition(pos="n.", meaning="x")],
            source=self.name,
        )

    async def aclose(self) -> None:
        self.close_thread = threading.get_ident()


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_loop_reuse_across_requests(qapp):
    db = get_db(Path(tempfile.mktemp(suffix=".db")))
    db.execute("DELETE FROM cache")
    db.commit()
    cache = CacheStore(db)
    history = HistoryStore(db)
    adapter = CountingAdapter()
    svc = TranslateService([adapter], cache, history)

    results: list[Translation] = []
    result_threads: list[int] = []

    def on_result(result):
        results.append(result)
        result_threads.append(threading.get_ident())

    bus.translate_result.connect(on_result)
    main_results: list[tuple[int, Translation]] = []
    main_result_threads: list[int] = []

    def on_main_result(request_id, result):
        main_results.append((request_id, result))
        main_result_threads.append(threading.get_ident())

    svc.main_query_result.connect(on_main_result)

    try:
        for w in ("hello", "world", "again"):
            results.clear()
            svc.translate(w)
            end = time.monotonic() + 3
            while time.monotonic() < end and not results:
                qapp.processEvents()
                time.sleep(0.02)
            assert results, f"translation for {w!r} should succeed"
        results.clear()
        main_results.clear()
        svc.translate_for_main("hello", 37)
        end = time.monotonic() + 3
        while time.monotonic() < end and not main_results:
            qapp.processEvents()
            time.sleep(0.02)
        assert len(main_results) == 1
        assert main_results[0][0] == 37
        assert main_results[0][1].word == "hello"
        assert not results
    finally:
        svc.shutdown()
        bus.translate_result.disconnect(on_result)
        svc.main_query_result.disconnect(on_main_result)
        db.close()

    assert adapter.calls == 3
    assert all(thread_id != threading.get_ident() for thread_id in adapter.thread_ids)
    assert all(thread_id == threading.get_ident() for thread_id in result_threads)
    assert main_result_threads == [threading.get_ident()]
    assert adapter.close_thread in adapter.thread_ids
    # All requests must have run on the same event loop instance.
    assert len(set(adapter.loop_ids)) == 1, (
        f"expected a single reused loop, got {set(adapter.loop_ids)}"
    )


def test_bing_timeout_changes_are_applied_on_the_worker_thread(qapp, tmp_path):
    class TimeoutAdapter(CountingAdapter):
        name = "bing"

        def __init__(self):
            super().__init__()
            self.timeout_updates: list[tuple[float, int]] = []

        async def set_timeout(self, timeout):
            self.timeout_updates.append((timeout, threading.get_ident()))

    db = get_db(tmp_path / "timeout.db")
    adapter = TimeoutAdapter()
    service = TranslateService([adapter], CacheStore(db), HistoryStore(db))
    try:
        service.set_bing_timeout(12.5)
        end = time.monotonic() + 3
        while time.monotonic() < end and not adapter.timeout_updates:
            qapp.processEvents()
            time.sleep(0.02)

        assert len(adapter.timeout_updates) == 1
        assert adapter.timeout_updates[0][0] == 12.5
        assert adapter.timeout_updates[0][1] != threading.get_ident()
    finally:
        service.shutdown()
        db.close()
