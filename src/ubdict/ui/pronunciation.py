"""Online natural pronunciation with an offline espeak-ng fallback."""
from __future__ import annotations

import threading
import sys
from urllib.parse import quote, urljoin

import httpx
from PyQt6.QtCore import (
    QByteArray,
    QIODevice,
    QObject,
    QProcess,
    QBuffer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

from loguru import logger

_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
_MAX_AUDIO_BYTES = 10 * 1024 * 1024


class PronunciationPlayer(QObject):
    """Fetch direct HTTPS pronunciation audio and fall back to local speech."""

    failed = pyqtSignal(str)
    _audio_ready = pyqtSignal(int, object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request_id = 0
        self._pending_word = ""
        self._reported_error = False
        self._replacing_process = False
        self._online_playing = False
        self._audio_buffer: QBuffer | None = None
        self._pending_speech = ""

        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.errorOccurred.connect(self._on_media_error)

        self._process = QProcess(self)
        self._process.errorOccurred.connect(self._on_error)
        self._process.finished.connect(self._on_finished)
        self._process.started.connect(self._on_speech_process_started)
        self._audio_ready.connect(self._on_audio_ready)

    def play(self, word: str) -> None:
        text = word.strip()
        if not text:
            return

        self._request_id += 1
        request_id = self._request_id
        self._pending_word = text
        self._reported_error = False
        self._online_playing = False
        self._player.stop()
        self._stop_offline_process()

        threading.Thread(
            target=self._fetch_audio,
            args=(request_id, text),
            name="pronunciation-fetch",
            daemon=True,
        ).start()

    def _fetch_audio(self, request_id: int, word: str) -> None:
        audio: bytes | None = None
        message = ""
        try:
            with httpx.Client(
                timeout=httpx.Timeout(2.5, connect=1.5),
                trust_env=False,
            ) as client:
                response = self._get_direct(
                    client, _API_URL.format(word=quote(word, safe=""))
                )
                response.raise_for_status()
                entries = response.json()
                audio_url = PronunciationPlayer._select_audio_url(entries)
                if not audio_url:
                    message = "在线词典没有提供发音音频"
                else:
                    audio = self._download_audio(client, audio_url)
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            message = str(exc) or "在线发音暂不可用"
        self._audio_ready.emit(request_id, audio, message)

    @staticmethod
    def _get_direct(client: httpx.Client, url: str) -> httpx.Response:
        """Follow only HTTPS redirects and never use configured proxies."""
        for _ in range(4):
            if not url.startswith("https://"):
                raise httpx.HTTPError("拒绝非 HTTPS 在线发音地址")
            response = client.get(url, follow_redirects=False)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            url = urljoin(url, location)
        raise httpx.TooManyRedirects("在线发音重定向次数过多")

    @staticmethod
    def _download_audio(client: httpx.Client, url: str) -> bytes:
        """Stream an HTTPS audio response while enforcing a hard byte limit."""
        for _ in range(4):
            if not url.startswith("https://"):
                raise httpx.HTTPError("拒绝非 HTTPS 在线发音地址")
            with client.stream("GET", url, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        response.raise_for_status()
                        raise httpx.HTTPError("在线发音重定向缺少地址")
                    url = urljoin(url, location)
                    continue

                response.raise_for_status()
                if response.url.scheme != "https":
                    raise httpx.HTTPError("在线发音地址重定向到了不安全的 HTTP")
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        declared_length = 0
                    if declared_length > _MAX_AUDIO_BYTES:
                        raise ValueError("在线发音文件过大")

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_AUDIO_BYTES:
                        raise ValueError("在线发音文件过大")
                    chunks.append(chunk)
                return b"".join(chunks)
        raise httpx.TooManyRedirects("在线发音重定向次数过多")

    @staticmethod
    def _select_audio_url(entries: object) -> str | None:
        if not isinstance(entries, list):
            return None
        candidates: list[tuple[int, str]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            phonetics = entry.get("phonetics", [])
            if not isinstance(phonetics, list):
                continue
            for phonetic in phonetics:
                if not isinstance(phonetic, dict):
                    continue
                audio_url = phonetic.get("audio")
                if not isinstance(audio_url, str) or not audio_url.strip():
                    continue
                audio_url = urljoin("https://api.dictionaryapi.dev", audio_url)
                if not audio_url.startswith("https://"):
                    continue
                url_lower = audio_url.lower()
                rank = 0 if "-us." in url_lower or "_us." in url_lower else 1
                candidates.append((rank, audio_url))
        if not candidates:
            return None
        return min(candidates, key=lambda candidate: candidate[0])[1]

    def _start_online_audio(self, audio: bytes) -> None:
        self._audio_buffer = QBuffer(self)
        self._audio_buffer.setData(QByteArray(audio))
        if not self._audio_buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            logger.warning("Could not open online pronunciation audio buffer")
            self._start_offline()
            return
        self._online_playing = True
        self._player.setSourceDevice(self._audio_buffer)
        self._player.play()

    def _on_audio_ready(self, request_id: int, audio: object, message: str) -> None:
        if request_id != self._request_id:
            return
        if isinstance(audio, bytes) and audio:
            logger.info(f"Playing online pronunciation for {self._pending_word!r}")
            self._start_online_audio(audio)
            return
        logger.info(
            f"Online pronunciation unavailable for {self._pending_word!r}: "
            f"{message}; using offline speech"
        )
        self._start_offline()

    def _on_media_error(self, _error, message: str) -> None:
        if not self._online_playing:
            return
        logger.warning(f"Online pronunciation playback failed: {message}")
        self._online_playing = False
        self._player.stop()
        if self._audio_buffer:
            self._audio_buffer.close()
            self._audio_buffer.deleteLater()
            self._audio_buffer = None
        self._start_offline()

    def _start_offline(self) -> None:
        self._online_playing = False
        self._reported_error = False
        if sys.platform == "win32":
            self._pending_speech = self._pending_word
            self._process.start(
                "powershell.exe",
                [
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Sta",
                    "-Command",
                    "$text = [Console]::In.ReadToEnd(); "
                    "$voice = New-Object -ComObject SAPI.SpVoice; "
                    "[void]$voice.Speak($text)",
                ],
            )
            return
        self._process.start("espeak-ng", ["-v", "en-us", self._pending_word])

    def _on_speech_process_started(self) -> None:
        if sys.platform != "win32" or not self._pending_speech:
            return
        self._process.write((self._pending_speech + "\n").encode("utf-8"))
        self._process.closeWriteChannel()
        self._pending_speech = ""

    def _stop_offline_process(self) -> None:
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        self._replacing_process = True
        self._process.kill()
        self._process.waitForFinished(1000)
        self._replacing_process = False

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            message = (
                "无法启动 Windows PowerShell 离线语音"
                if sys.platform == "win32"
                else "找不到 espeak-ng，请安装该程序"
            )
        else:
            message = self._process.errorString()
        logger.error(f"Pronunciation playback failed: {message}")
        self._reported_error = True
        self.failed.emit(message)

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        if exit_code and not self._reported_error and not self._replacing_process:
            message = self._process.readAllStandardError().data().decode(
                "utf-8", errors="replace"
            ).strip()
            message = message or f"离线语音程序退出代码 {exit_code}"
            logger.error(f"Pronunciation playback failed: {message}")
            self.failed.emit(message)
