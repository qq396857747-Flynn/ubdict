"""M3+M4 integration verification.

Run as a script:  python tests/integration/test_m3_m4.py
"""
import pytest


def test_placeholder():
    """Placeholder for pytest collection; run as a script for the full check."""
    pass


if __name__ == "__main__":
    import sys, os, time, asyncio, tempfile
    from pathlib import Path
    sys.path.insert(0, 'src')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

    from PyQt6.QtWidgets import QApplication
    app = QApplication([])

    results = []
    def check(name, fn):
        try:
            fn()
            results.append((name, 'OK', ''))
        except Exception as e:
            results.append((name, 'FAIL', f'{type(e).__name__}: {e}'))

    # 1. ConfigManager
    from ubdict.config import ConfigManager, AppConfig
    def t1():
        cm = ConfigManager()
        assert isinstance(cm.config, AppConfig)
        assert cm.config.capture.text_enabled is True
        assert cm.config.capture.image_hover_delay == 3.0
    check('ConfigManager 默认值', t1)

    def t2():
        p = Path(tempfile.mktemp(suffix='.toml'))
        cm = ConfigManager(p)
        cm.config.capture.image_hover_delay = 5.0
        cm.config.ui.window_opacity = 0.8
        cm.save()
        assert p.exists()
        cm2 = ConfigManager(p)
        assert cm2.config.capture.image_hover_delay == 5.0
        assert cm2.config.ui.window_opacity == 0.8
        p.unlink()
    check('ConfigManager 保存/加载', t2)

    # 2. WordbookStore
    from ubdict.storage.db import get_db
    from ubdict.storage.wordbook import WordbookStore
    db = get_db(Path(tempfile.mktemp(suffix='.db')))
    wb = WordbookStore(db)
    def t3():
        assert wb.add('hello') is True
        assert wb.add('hello') is False  # duplicate
        assert wb.contains('hello') is True
        assert wb.count() == 1
        wb.add('world')
        assert wb.count() == 2
        words = wb.list_all()
        assert len(words) == 2
        assert words[0]['word'] in ('hello', 'world')
    check('WordbookStore 增删查', t3)

    def t4():
        p = tempfile.mktemp(suffix='.csv')
        count = wb.export_csv(p)
        assert count == 2
        os.unlink(p)
    check('WordbookStore CSV 导出', t4)

    def t5():
        wb.remove('hello')
        assert not wb.contains('hello')
        assert wb.count() == 1
    check('WordbookStore 删除', t5)

    # 3. SettingsDialog
    from ubdict.ui.settings import SettingsDialog
    from ubdict.config import AppConfig
    def t6():
        cfg = AppConfig()
        saved = []
        dlg = SettingsDialog(cfg, on_save=lambda c: saved.append(c))
        assert dlg._text_enabled.isChecked() is True
        dlg._image_enabled.setChecked(True)
        dlg._hover_delay.setValue(5.0)
        dlg._save()
        assert saved[0].capture.image_enabled is True
        assert saved[0].capture.image_hover_delay == 5.0
    check('SettingsDialog 保存', t6)

    # 4. PdfDocument (用 PyMuPDF 创建一个测试 PDF)
    from ubdict.core.capture.pdf import PdfDocument
    def t7():
        import fitz
        p = tempfile.mktemp(suffix='.pdf')
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "hello world convolutional", fontsize=12)
        doc.save(p)
        doc.close()
        pdf = PdfDocument(p)
        assert pdf.page_count == 1
        assert pdf.has_text_layer(0) is True
        word = pdf.extract_word_at(0, 108, 108, zoom=1.5)
        assert word is not None, "should find a word at the text position"
        pdf.close()
        os.unlink(p)
    check('PdfDocument 文本层提取', t7)

    # 5. PdfViewer
    from ubdict.core.capture.pdf import PdfViewer
    def t8():
        import fitz
        p = tempfile.mktemp(suffix='.pdf')
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "ubiquitous", fontsize=12)
        doc.save(p)
        doc.close()
        pdf = PdfDocument(p)
        viewer = PdfViewer(pdf)
        assert viewer.page_count == 1
        assert viewer.current_page == 0
        pdf.close()
        os.unlink(p)
    check('PdfViewer 实例化', t8)

    # 6. PdfWindow
    from ubdict.ui.pdf_window import PdfWindow
    def t9():
        win = PdfWindow()
        assert win.windowTitle().startswith('UbDict')
    check('PdfWindow 实例化', t9)

    # 7. WordbookWindow
    from ubdict.ui.wordbook_window import WordbookWindow
    def t10():
        win = WordbookWindow(wb)
        assert '生词本' in win.windowTitle()
    check('WordbookWindow 实例化', t10)

    # 8. HotkeyManager (Wayland 下应为 no-op)
    from ubdict.platform.hotkey import HotkeyManager
    from ubdict.platform.factory import detect_backend
    backend = detect_backend()
    def t11():
        hm = HotkeyManager(backend)
        called = []
        result = hm.register('Ctrl+Shift+D', lambda: called.append(1))
        assert result == (backend.name == 'x11')
        hm.start()
        hm.stop()
    check(f'HotkeyManager ({backend.name})', t11)

    # 9. DictWindow 生词本按钮
    from ubdict.ui.dict_window import DictWindow
    from ubdict.core.models import Translation, Definition
    def t12():
        dw = DictWindow()
        dw.set_wordbook_store(wb)
        t = Translation(word='test', definitions=[Definition(pos='n.', meaning='测试')])
        dw.show_result(t)
        assert dw._current_word == 'test'
        assert dw._wordbook is wb
    check('DictWindow 生词本集成', t12)

    # 10. 完整应用装配（仅验证可导入与接口，避免在已有 QApplication 下创建第二个实例）
    from ubdict.app import UbDictApp
    def t13():
        import inspect
        assert inspect.isclass(UbDictApp)
        assert hasattr(UbDictApp, "run") and hasattr(UbDictApp, "quit")
    check('UbDictApp 可导入且接口完整', t13)

    # Output
    for i, (name, status, err) in enumerate(results, 1):
        line = f'[{i:2d}] {name}: {status}'
        if err:
            line += f'  ({err})'
        print(line)
    ok = sum(1 for _, s, _ in results if s == 'OK')
    print(f'\n=== M3+M4 验证: {ok}/{len(results)} 通过 ===')
    db.close()
