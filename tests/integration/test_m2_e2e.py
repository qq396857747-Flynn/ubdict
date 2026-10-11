"""M2 end-to-end integration test: image capture -> Bing translate -> popup.

Run as a script:  python tests/integration/test_m2_e2e.py
"""
import pytest


def test_placeholder():
    """Placeholder for pytest collection; run as a script for the full check."""
    pass


if __name__ == "__main__":
    import sys, os, time
    sys.path.insert(0, 'src')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

    from PyQt6.QtWidgets import QApplication

    app = QApplication([])

    def wait_with_events(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)

    from ubdict.core.capture.image import ImageCapture
    from ubdict.core.capture.ocr import FakeOcrEngine, OcrResult
    from ubdict.core.event_bus import bus
    from ubdict.core.translate.bing import BingAdapter
    from ubdict.core.translate.local import LocalAdapter
    from ubdict.core.translate.service import TranslateService
    from ubdict.storage.db import get_db
    from ubdict.storage.cache import CacheStore
    from ubdict.storage.history import HistoryStore
    from ubdict.ui.dict_window import DictWindow

    db = get_db()
    cache = CacheStore(db)
    history = HistoryStore(db)
    bing = BingAdapter()
    local = LocalAdapter()
    svc = TranslateService([bing, local], cache, history)

    win = DictWindow()

    results = []
    errors = []
    bus.translate_result.connect(lambda r: results.append(r))
    bus.translate_error.connect(lambda w, m: errors.append((w, m)))

    class MockBackend:
        def get_mouse_position(self): return (400, 300)
        def get_selection_text(self): return None
        def capture_region(self, x, y, w, h): return b"fake-screenshot"
        def start_selection_watch(self, cb): pass
        def stop_selection_watch(self): pass

    backend = MockBackend()
    ocr = FakeOcrEngine([OcrResult("hello", 110, 45, 60, 20)])

    img_capture = ImageCapture(backend, ocr, hover_delay=0.5)
    img_capture.set_enabled(True)
    img_capture.start()

    print("等待图片取词 + 翻译...")
    wait_with_events(3.0)

    print(f"翻译结果数: {len(results)}")
    print(f"翻译错误数: {len(errors)}")

    if results:
        r = results[0]
        print(f"  word: {r.word}")
        print(f"  source: {r.source}")
        print(f"  phonetic_us: {r.phonetic_us}")
        print(f"  definitions: {len(r.definitions)}")
        for d in r.definitions[:2]:
            print(f"    {d.pos} {d.meaning[:40]}")
        win.show_result(r)
        print("  浮窗显示: OK")

    img_capture.stop()
    svc.shutdown()
    db.close()

    assert len(results) >= 1, "端到端翻译应成功"
    assert results[0].word == "hello"
    print()
    print("=== M2 端到端测试通过: 图片取词->必应翻译->浮窗显示 ===")
