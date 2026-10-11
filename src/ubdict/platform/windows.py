"""Windows platform backend for clipboard-based text and screen capture."""
from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes

from loguru import logger

from ubdict.platform.base import PlatformBackend

_CF_UNICODETEXT = 13
_MAX_CLIPBOARD_CHARS = 4096


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class WindowsBackend(PlatformBackend):
    name = "windows"

    def __init__(self) -> None:
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None

    @staticmethod
    def _user32():
        return ctypes.WinDLL("user32", use_last_error=True)

    @staticmethod
    def get_clipboard_sequence() -> int:
        user32 = WindowsBackend._user32()
        user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
        return int(user32.GetClipboardSequenceNumber())

    def get_mouse_position(self) -> tuple[int, int] | None:
        point = _Point()
        user32 = self._user32()
        user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
        user32.GetCursorPos.restype = wintypes.BOOL
        if not user32.GetCursorPos(ctypes.byref(point)):
            error = ctypes.get_last_error()
            logger.warning(f"GetCursorPos failed with Windows error {error}")
            return None
        return point.x, point.y

    def get_selection_text(self) -> str | None:
        user32 = self._user32()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalSize.restype = ctypes.c_size_t

        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(_CF_UNICODETEXT)
            if not handle:
                return ""
            size = kernel32.GlobalSize(handle)
            if not size or size > (_MAX_CLIPBOARD_CHARS + 1) * ctypes.sizeof(
                ctypes.c_wchar
            ):
                return ""
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return ""
            try:
                return ctypes.wstring_at(
                    pointer,
                    min(
                        size // ctypes.sizeof(ctypes.c_wchar),
                        _MAX_CLIPBOARD_CHARS,
                    ),
                ).split("\x00", 1)[0]
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def capture_region(self, x: int, y: int, w: int, h: int) -> bytes:
        import mss
        import mss.tools

        with mss.mss() as screen:
            shot = screen.grab({"left": x, "top": y, "width": w, "height": h})
            return mss.tools.to_png(shot.rgb, shot.size)

    def start_selection_watch(self, on_change: Callable[[str], None]) -> None:
        self._watch_stop.clear()

        def _loop() -> None:
            try:
                sequence = self.get_clipboard_sequence()
                while not self._watch_stop.wait(0.2):
                    current = self.get_clipboard_sequence()
                    if current == sequence:
                        continue
                    text = self.get_selection_text()
                    if text is None:
                        continue
                    sequence = self.get_clipboard_sequence()
                    if text:
                        try:
                            on_change(text)
                        except Exception as e:
                            logger.error(f"clipboard callback error: {e}")
            except Exception:
                logger.exception("Windows clipboard monitoring failed")

        self._watch_thread = threading.Thread(
            target=_loop, name="windows-clipboard-watch", daemon=True
        )
        self._watch_thread.start()
        logger.info("Windows clipboard watch started (copy selected text to look it up)")

    def stop_selection_watch(self) -> None:
        self._watch_stop.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=2)
            if self._watch_thread.is_alive():
                logger.error("Timed out waiting for Windows clipboard watcher to stop")
        self._watch_thread = None
        logger.info("Windows clipboard watch stopped")
