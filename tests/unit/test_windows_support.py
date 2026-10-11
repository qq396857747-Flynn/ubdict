import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ubdict.paths import resource_path, user_config_dir, user_data_dir
from ubdict.platform.factory import detect_backend
from ubdict.platform.hotkey import HotkeyManager
from ubdict.platform.windows import WindowsBackend


def test_windows_session_selects_windows_backend(monkeypatch):
    monkeypatch.setattr("ubdict.platform.factory.sys.platform", "win32")

    assert isinstance(detect_backend(), WindowsBackend)


def test_windows_user_paths_use_standard_profile_directories(monkeypatch, tmp_path):
    monkeypatch.setattr("ubdict.paths.sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert user_config_dir() == tmp_path / "roaming" / "UbDict"
    assert user_data_dir() == tmp_path / "local" / "UbDict"


def test_bundled_resource_path_uses_pyinstaller_root(monkeypatch, tmp_path):
    monkeypatch.setattr("ubdict.paths.sys._MEIPASS", str(tmp_path), raising=False)

    assert resource_path("config/ecdict.db") == tmp_path / "config/ecdict.db"


def test_windows_backend_emits_each_clipboard_copy_even_for_same_text():
    backend = WindowsBackend()
    sequence = iter([10, 11, 11, 12])
    backend.get_clipboard_sequence = lambda: next(sequence, 12)
    backend.get_selection_text = lambda: "repeat"
    captured = []
    reached_twice = threading.Event()

    def on_change(text):
        captured.append(text)
        if len(captured) == 2:
            reached_twice.set()

    backend.start_selection_watch(on_change)
    try:
        assert reached_twice.wait(2)
        assert captured == ["repeat", "repeat"]
    finally:
        backend.stop_selection_watch()


def test_windows_backend_retries_clipboard_read_when_temporarily_unavailable():
    backend = WindowsBackend()
    sequence = iter([10, 11])
    clipboard_text = iter([None, "retry"])
    backend.get_clipboard_sequence = lambda: next(sequence, 11)
    backend.get_selection_text = lambda: next(clipboard_text)
    captured = []
    reached = threading.Event()

    def on_change(text):
        captured.append(text)
        reached.set()

    backend.start_selection_watch(on_change)
    try:
        assert reached.wait(2)
        assert captured == ["retry"]
    finally:
        backend.stop_selection_watch()


def test_windows_global_hotkey_parser_supports_modifiers_and_function_keys():
    assert HotkeyManager._parse_windows("Ctrl+Shift+T") == (0x0006, ord("T"))
    assert HotkeyManager._parse_windows("Alt+F12") == (0x0001, 0x7B)
    assert HotkeyManager._parse_windows("Win+Space") == (0x0008, 0x20)
    assert HotkeyManager._parse_windows("Ctrl+Ctrl+D") is None
    assert HotkeyManager._parse_windows("Ctrl+F25") is None
