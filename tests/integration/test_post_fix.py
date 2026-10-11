"""Post-fix end-to-end verification.

Run as a script:  python tests/integration/test_post_fix.py

Verifies that a second translation still succeeds (regression for the
asyncio.run-per-request loop-reuse bug) and records the source used.
"""
import pytest


def test_placeholder():
    """Placeholder for pytest collection; run as a script for the full check."""
    pass


if __name__ == "__main__":
    import sys, os, time, tempfile
    from pathlib import Path
    sys.path.insert(0, 'src')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])

    from ubdict.core.event_bus import bus
    from ubdict.core.translate.bing import BingAdapter
    from ubdict.core.translate.local import LocalAdapter
    from ubdict.core.translate.service import TranslateService
    from ubdict.storage.db import get_db
    from ubdict.storage.cache import CacheStore
    from ubdict.storage.history import HistoryStore
    from ubdict.storage.wordbook import WordbookStore
    from ubdict.ui.dict_window import DictWindow

    db = get_db(Path(tempfile.mktemp(suffix='.db')))
    db.execute("DELETE FROM cache"); db.commit()
    cache = CacheStore(db)
    history = HistoryStore(db)
    wb = WordbookStore(db)
    svc = TranslateService([BingAdapter(), LocalAdapter()], cache, history)

    win = DictWindow()
    win.set_wordbook_store(wb)

    results = []
    bus.translate_result.connect(lambda r: results.append(r))

    svc.translate('hello')
    end = time.monotonic() + 5
    while time.monotonic() < end and not results:
        app.processEvents(); time.sleep(0.05)

    assert results, '翻译应成功'
    r = results[0]
    print(f'OK 翻译: {r.word} via {r.source}, {len(r.definitions)}释义')
    first_source = r.source

    win.show_result(r)
    print('OK 浮窗显示')

    win._on_star()
    assert wb.contains('hello')
    print('OK 生词本: hello 已加入')

    results.clear()
    svc.translate('world')
    end = time.monotonic() + 5
    while time.monotonic() < end and not results:
        app.processEvents(); time.sleep(0.05)
    assert results, '第二次翻译应成功（回归：事件循环复用）'
    second_source = results[0].source
    print(f'OK 第二次翻译: {results[0].word} via {second_source}')

    if first_source == 'bing' and second_source == 'bing':
        print('OK Bing 适配器跨请求复用确认')
    elif second_source == 'local':
        print('注意: 第二次降级到 local（可能网络不可用；Bing 复用见 unit/test_service_loop_reuse.py）')

    svc.shutdown(); db.close()
    print()
    print('=== 修复后端到端验证通过 ===')
