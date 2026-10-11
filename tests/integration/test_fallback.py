"""Test fallback: Bing fails -> local ECDICT serves the result.

Run as a script:  python tests/integration/test_fallback.py
(PyQt6 + local ECDICT required.)
"""
import pytest


def test_placeholder():
    """Placeholder so pytest can collect this module without executing the
    script body (which needs a display and the local ECDICT database)."""
    pass


if __name__ == "__main__":
    import sys, asyncio, time
    sys.path.insert(0, 'src')

    from PyQt6.QtCore import QCoreApplication
    app = QCoreApplication([])

    import httpx
    from ubdict.core.translate.bing import BingAdapter
    from ubdict.core.translate.local import LocalAdapter
    from ubdict.core.translate.service import TranslateService
    from ubdict.core.event_bus import bus
    from ubdict.storage.db import get_db
    from ubdict.storage.cache import CacheStore
    from ubdict.storage.history import HistoryStore

    class FailingBing(BingAdapter):
        async def translate(self, word):
            raise httpx.ConnectError("simulated network down")

    db = get_db()
    cache = CacheStore(db)
    history = HistoryStore(db)
    db.execute("DELETE FROM cache")
    db.commit()
    svc = TranslateService([FailingBing(), LocalAdapter()], cache, history)

    results = []
    errors = []
    bus.translate_result.connect(lambda r: results.append(r))
    bus.translate_error.connect(lambda w, m: errors.append((w, m)))

    svc.translate("hello")
    end = time.monotonic() + 5
    while time.monotonic() < end and not results:
        app.processEvents()
        time.sleep(0.05)

    print(f"结果数: {len(results)}, 错误数: {len(errors)}")
    if results:
        r = results[0]
        print(f"  word: {r.word}, source: {r.source}")
        if r.definitions:
            print(f"  首条释义: {r.definitions[0].pos} {r.definitions[0].meaning[:60]}")
        assert r.source == "local", f"应降级到local, 实际{r.source}"
        print("  降级链: 必应失败 -> 本地词典 OK")

    svc.shutdown()
    db.close()
