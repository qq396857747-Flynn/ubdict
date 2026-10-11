import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

from ubdict.config import AppConfig
from ubdict.core.capture.text import TextCapture
from ubdict.core.models import Definition, Example, PhraseGroup, Translation
from ubdict.platform.base import PlatformBackend
from ubdict.storage.db import get_db
from ubdict.storage.wordbook import WordbookStore
from ubdict.ui.dict_window import DictWindow
from ubdict.ui.main_window import MainWindow
from ubdict.ui.pronunciation import PronunciationPlayer
from ubdict.ui.settings import SettingsDialog
from ubdict.ui.wordbook_window import WordbookWindow


_APP = QApplication.instance() or QApplication([])


class History:
    def recent(self, limit):
        return []


class Wordbook:
    def __init__(self):
        self.words = set()

    def contains(self, word):
        return word.casefold() in self.words

    def add(self, word):
        key = word.casefold()
        if key in self.words:
            return False
        self.words.add(key)
        return True


def _translation(word="hello"):
    return Translation(
        word=word,
        phonetic_us="həˈloʊ",
        definitions=[
            Definition(pos=f"n.{index}", meaning=f"meaning {index}")
            for index in range(5)
        ],
        examples=[
            Example(en=f"Example {index}.", zh=f"例句 {index}。")
            for index in range(4)
        ],
        source="local",
    )


def test_popup_actions_forward_result_and_add_wordbook_entry():
    window = DictWindow()
    wordbook = Wordbook()
    shown = []
    window.set_wordbook_store(wordbook)
    window.set_main_window_callback(shown.append)
    result = _translation()
    window.show_result(result)

    window._on_show_main()
    window._on_star()

    assert shown == [result]
    assert wordbook.contains("hello")
    assert window._action_status.text() == "已加入生词本。"
    assert window._defs_layout.count() == 3
    assert window._examples_layout.count() == 2
    window.close()


def test_main_window_renders_details_from_popup_result():
    wordbook = Wordbook()
    window = MainWindow(History(), wordbook)
    result = _translation()

    window.show_translation(result)

    assert window._word_label.text() == "hello"
    assert window._phonetic_label.text() == "美音 /həˈloʊ/"
    labels = [
        window._details_layout.itemAt(index).widget().text()
        for index in range(window._details_layout.count())
        if isinstance(window._details_layout.itemAt(index).widget(), QLabel)
    ]
    assert "n.0  meaning 0" in labels
    assert "n.4  meaning 4" in labels
    assert "Example 0." in labels
    assert "Example 3." in labels
    assert "例句 3。" in labels
    assert window._source_label.text() == "词典来源：local"

    window._add_current_word()
    assert wordbook.contains("hello")
    assert window._wordbook_status.text() == "已加入生词本。"

    spoken = []
    window.set_pronunciation_callback(spoken.append)
    window._pronounce_btn.click()
    assert spoken == ["hello"]
    window.close()


def test_main_window_renders_bing_dictionary_sections():
    window = MainWindow(History(), Wordbook())
    result = Translation(
        word="presence",
        definitions=[Definition(pos="n.", meaning="在场；出席")],
        detailed_definitions=[
            Definition(
                pos="n.",
                meaning="在场；出席",
                usage="[u]",
                english_meaning="the fact of being in a particular place",
                examples=[Example(en="He was present.", zh="他当时在场。")],
            )
        ],
        word_forms=["复数：presences"],
        collocations=[
            PhraseGroup(label="adj.+n.", phrases=["strong presence", "physical presence"])
        ],
        antonyms=["absence"],
        bing_details_loaded=True,
        source="bing",
    )

    window.show_translation(result)

    labels = [
        window._details_layout.itemAt(index).widget().text()
        for index in range(window._details_layout.count())
        if isinstance(window._details_layout.itemAt(index).widget(), QLabel)
    ]
    assert "词形变化" in labels
    assert "复数：presences" in labels
    assert "常用搭配" in labels
    assert "adj.+n.  strong presence、physical presence" in labels
    assert "反义词" in labels
    assert "absence" in labels
    assert "详细释义" in labels
    assert "n.  在场；出席  [u]" in labels
    assert "the fact of being in a particular place" in labels
    assert "He was present." in labels
    assert "他当时在场。" in labels
    window.close()


def test_main_window_displays_query_errors_for_current_word():
    window = MainWindow(History(), Wordbook())
    requests = []
    window.query_requested.connect(
        lambda word, request_id: requests.append((word, request_id))
    )
    window._input.setText("missing")
    window._on_query()
    request_id = requests[-1][1]

    window.show_translation_error(request_id - 1, "missing", "not found")
    assert window._detail_status.text() != "查询失败：not found"
    window.show_translation_error(request_id, "missing", "未找到释义")

    assert window._detail_status.text() == "查询失败：未找到释义"
    assert not window._add_word_button.isEnabled()
    assert not window._pronounce_btn.isEnabled()
    window.close()


def test_main_window_ignores_stale_results_even_for_the_same_word():
    window = MainWindow(History(), Wordbook())
    window._input.setText("same")
    window._on_query()
    old_request_id = window._request_id
    window._input.setText("same")
    window._on_query()
    current_request_id = window._request_id

    window.show_query_translation(old_request_id, _translation("same"))
    assert window._detail_status.text() == "正在查询…"
    assert window._current_translation is None

    window.show_query_translation(current_request_id, _translation("same"))
    assert window._current_translation.word == "same"
    assert window._detail_status.text().startswith("已显示词典返回")
    window.close()


def test_wordbook_export_includes_entries_beyond_interactive_list_limit(tmp_path):
    connection = get_db(tmp_path / "ubdict.db")
    connection.executemany(
        "INSERT INTO wordbook(word, added_at, note) VALUES (?, ?, ?)",
        (
            (f"word-{index:05}", index, f"note-{index}")
            for index in range(5005)
        ),
    )
    connection.commit()
    store = WordbookStore(connection)
    export_path = tmp_path / "wordbook.csv"

    exported = store.export_csv(str(export_path))
    lines = export_path.read_text(encoding="utf-8").splitlines()

    assert store.count() == 5005
    assert exported == 5005
    assert len(lines) == 5006
    assert lines[1].startswith("word-05004,")
    assert lines[-1].startswith("word-00000,")
    connection.close()


def test_csv_export_neutralizes_formulas_after_leading_space_and_controls():
    from ubdict.storage.wordbook import _csv_safe

    assert _csv_safe(" =1+1") == "' =1+1"
    assert _csv_safe("\t=1+1") == "'\t=1+1"
    assert _csv_safe(" \r\n@SUM(A1)") == "' \r\n@SUM(A1)"
    assert _csv_safe("\x00=1+1") == "'\x00=1+1"
    assert _csv_safe("\u00a0+1") == "'\u00a0+1"
    assert _csv_safe("\ufeff=1+1") == "'\ufeff=1+1"
    assert _csv_safe("\u200b@SUM(A1)") == "'\u200b@SUM(A1)"
    assert _csv_safe("ordinary word") == "ordinary word"


def test_popup_add_is_persisted_and_wordbook_refreshes_when_opened(tmp_path):
    connection = get_db(tmp_path / "ubdict.db")
    store = WordbookStore(connection)
    wordbook_window = WordbookWindow(store)
    popup = DictWindow()
    popup.set_wordbook_store(store)
    popup.show_result(_translation("persistent"))

    popup._on_star()

    assert store.list_all()[0]["word"] == "persistent"
    wordbook_window.show()
    _APP.processEvents()
    assert wordbook_window._list.count() == 1
    assert wordbook_window._list.item(0).text() == "persistent"

    popup.close()
    wordbook_window.close()
    connection.close()
    reopened = get_db(tmp_path / "ubdict.db")
    assert WordbookStore(reopened).contains("persistent")
    reopened.close()


def test_popup_speaker_uses_current_word():
    popup = DictWindow()
    spoken = []
    popup.set_pronunciation_callback(spoken.append)
    popup.show_result(_translation("pronounce"))

    popup._pronounce_btn.click()

    assert spoken == ["pronounce"]
    popup.close()


def test_pronunciation_player_sends_word_to_offline_synthesizer(
    tmp_path, monkeypatch
):
    executable = tmp_path / "espeak-ng"
    recorded = tmp_path / "spoken.txt"
    executable.write_text(
        "#!/usr/bin/python3\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['UBDICT_SPEECH_CAPTURE']).write_text(' '.join(sys.argv[1:]))\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UBDICT_SPEECH_CAPTURE", str(recorded))

    player = PronunciationPlayer()
    monkeypatch.setattr(
        player,
        "_fetch_audio",
        lambda request_id, _word: player._audio_ready.emit(
            request_id, None, "network unavailable"
        ),
    )
    finished = []
    player._process.finished.connect(lambda code, _status: finished.append(code))
    player.play("pronunciation test")

    deadline = time.monotonic() + 3
    while not finished and time.monotonic() < deadline:
        _APP.processEvents()
        time.sleep(0.01)

    assert finished == [0]
    assert recorded.read_text().strip() == "-v en-us pronunciation test"


def test_online_audio_lookup_is_direct_and_prefers_us_pronunciation(monkeypatch):
    from ubdict.ui import pronunciation

    class Response:
        status_code = 200
        url = type("URL", (), {"scheme": "https"})()
        content = b"recorded voice"
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return [
                {
                    "phonetics": [
                        {"audio": "//cdn.example/word-uk.mp3"},
                        {"audio": "//cdn.example/word-us.mp3"},
                    ]
                }
            ]

        def iter_bytes(self):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            self.urls = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, url, **kwargs):
            self.urls.append(url)
            if "api/v2/entries" in url:
                return Response()
            assert url == "https://cdn.example/word-us.mp3"
            return Response()

        def stream(self, method, url, **kwargs):
            self.urls.append(url)
            assert method == "GET"
            return Response()

    monkeypatch.setattr(pronunciation.httpx, "Client", Client)
    player = PronunciationPlayer()
    results = []
    player._audio_ready.connect(
        lambda request_id, audio, message: results.append(
            (request_id, audio, message)
        )
    )

    player._fetch_audio(7, "hello world")

    assert results == [(7, b"recorded voice", "")]


def test_online_audio_rejects_insecure_redirects():
    import httpx

    from ubdict.ui.pronunciation import PronunciationPlayer

    class Client:
        def get(self, _url, **_kwargs):
            return httpx.Response(
                302, headers={"location": "http://audio.example/word.mp3"}
            )

    try:
        PronunciationPlayer._get_direct(
            Client(), "https://api.dictionaryapi.dev/api/v2/entries/en/word"
        )
    except httpx.HTTPError as error:
        assert "非 HTTPS" in str(error)
    else:
        raise AssertionError("HTTP downgrade should be rejected")


def test_online_audio_stream_enforces_byte_limit(monkeypatch):
    from ubdict.ui import pronunciation

    class Response:
        status_code = 200
        url = type("URL", (), {"scheme": "https"})()
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"1234"
            yield b"5678"

    class Client:
        def stream(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(pronunciation, "_MAX_AUDIO_BYTES", 6)
    try:
        pronunciation.PronunciationPlayer._download_audio(
            Client(), "https://cdn.example/audio.mp3"
        )
    except ValueError as error:
        assert "过大" in str(error)
    else:
        raise AssertionError("oversized streamed audio must be rejected")


def test_settings_keep_image_and_pdf_ocr_modes_exclusive():
    saved = []
    dialog = SettingsDialog(AppConfig(), on_save=saved.append)

    dialog._pdf_enabled.setChecked(True)
    assert not dialog._image_enabled.isChecked()
    dialog._image_enabled.setChecked(True)
    assert not dialog._pdf_enabled.isChecked()

    dialog._save()

    assert saved[0].capture.image_enabled
    assert not saved[0].capture.pdf_enabled
    dialog.close()


def test_text_capture_debounce_setting_updates_active_timer():
    class Backend(PlatformBackend):
        name = "test"

        def get_mouse_position(self):
            return None

        def get_selection_text(self):
            return None

        def capture_region(self, x, y, w, h):
            return b""

        def start_selection_watch(self, on_change):
            pass

        def stop_selection_watch(self):
            pass

    capture = TextCapture(Backend(), debounce_ms=100)
    capture._on_selection_change("hello")

    assert capture._timer.isActive()
    capture.set_debounce_ms(500)

    assert capture._debounce_ms == 500
    assert capture._timer.interval() == 500
    assert capture._timer.isActive()
