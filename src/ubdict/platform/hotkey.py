"""Global hotkey registration.

X11 uses python-xlib, Windows uses RegisterHotKey, and Wayland hotkeys are
unavailable unless the compositor provides an out-of-process shortcut.

Thread-safety: X11 and Windows listeners run on background threads but only
emit a Qt signal when a key is pressed; callbacks are dispatched on the GUI
thread via a queued connection, so QWidget operations stay safe.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from loguru import logger

from ubdict.platform.base import PlatformBackend


class HotkeyManager(QObject):
    """Register global hotkeys.

    Signals
    -------
    triggered(str)
        Emitted with the hotkey string when it is pressed.
    """

    triggered = pyqtSignal(str)
    _fired = pyqtSignal(str)

    def __init__(self, backend: PlatformBackend) -> None:
        super().__init__()
        self._backend = backend
        self._registrations: dict[str, Callable[[], None]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._supported = backend.name in {"x11", "windows"}
        self._windows_thread_id: int | None = None
        # Bridge background-thread key events to the GUI thread.
        self._fired.connect(self._dispatch)

    def _dispatch(self, hotkey: str) -> None:
        """Run the hotkey callback on the GUI thread (queued from _loop)."""
        cb = self._registrations.get(hotkey)
        if cb:
            try:
                cb()
            except Exception as e:
                logger.error(f"Hotkey callback error: {e}")
        self.triggered.emit(hotkey)

    def reregister(self, registrations: dict[str, Callable[[], None]]) -> None:
        """Replace all hotkey registrations at runtime (call from GUI thread)."""
        was_running = self._thread is not None and self._thread.is_alive()
        if was_running:
            self.stop()
        self._registrations = dict(registrations)
        if was_running and self._supported and self._registrations:
            self.start()

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        """Register a hotkey like 'Ctrl+Shift+D'. Returns True if supported."""
        if not self._supported:
            logger.debug(
                f"Hotkeys not supported on {self._backend.name}; skipping {hotkey}"
            )
            return False
        self._registrations[hotkey] = callback
        return True

    def start(self) -> None:
        if not self._supported or not self._registrations:
            if not self._supported:
                logger.info("HotkeyManager: unsupported on this backend (no-op)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="hotkey-listener", daemon=True
        )
        self._thread.start()
        logger.info(f"HotkeyManager started ({len(self._registrations)} keys)")

    def stop(self) -> None:
        self._stop.set()
        if self._backend.name == "windows" and self._windows_thread_id:
            import ctypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostThreadMessageW.argtypes = [
                ctypes.c_ulong, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t
            ]
            user32.PostThreadMessageW.restype = ctypes.c_int
            if not user32.PostThreadMessageW(
                self._windows_thread_id, 0x0012, 0, 0
            ):
                logger.error(
                    f"Could not stop Windows hotkey thread; "
                    f"Windows error {ctypes.get_last_error()}"
                )
        if self._thread:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                logger.error("Timed out waiting for hotkey listener to stop")
            else:
                self._thread = None

    def _loop(self) -> None:
        """Run the platform-specific global hotkey listener."""
        if self._backend.name == "windows":
            self._windows_loop()
            return
        self._x11_loop()

    def _windows_loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class _Point(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class _Message(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", _Point),
                ("lPrivate", wintypes.DWORD),
            ]

        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(_Message),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(_Message), wintypes.HWND, wintypes.UINT, wintypes.UINT
        ]
        user32.RegisterHotKey.argtypes = [
            wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
        ]
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._windows_thread_id = kernel32.GetCurrentThreadId()
        message = _Message()
        user32.PeekMessageW(
            ctypes.byref(message), None, 0, 0, 0
        )
        if self._stop.is_set():
            self._windows_thread_id = None
            return

        registered: dict[int, str] = {}
        for hotkey_id, hotkey in enumerate(self._registrations, start=1):
            parsed = self._parse_windows(hotkey)
            if parsed is None:
                logger.error(f"Invalid Windows hotkey: {hotkey}")
                continue
            modifier_bits, virtual_key = parsed
            modifier_bits |= 0x4000
            if user32.RegisterHotKey(None, hotkey_id, modifier_bits, virtual_key):
                registered[hotkey_id] = hotkey
            else:
                logger.error(
                    f"Could not register Windows hotkey {hotkey}; "
                    f"Windows error {ctypes.get_last_error()}"
                )

        try:
            while True:
                status = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if status <= 0:
                    if status < 0:
                        logger.error(
                            f"Windows hotkey message loop failed with "
                            f"error {ctypes.get_last_error()}"
                        )
                    break
                if message.message == 0x0312:
                    hotkey = registered.get(int(message.wParam))
                    if hotkey:
                        self._fired.emit(hotkey)
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)
            self._windows_thread_id = None

    @staticmethod
    def _parse_windows(hotkey: str) -> tuple[int, int] | None:
        modifiers = {
            "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004,
            "alt": 0x0001, "win": 0x0008, "meta": 0x0008,
        }
        virtual_keys = {
            "SPACE": 0x20, "ENTER": 0x0D, "RETURN": 0x0D,
            "TAB": 0x09, "ESC": 0x1B, "ESCAPE": 0x1B,
            "DELETE": 0x2E, "INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
            "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
        }
        parts = hotkey.split("+")
        if not parts or not parts[-1].strip():
            return None
        modifier_bits = 0
        for modifier in parts[:-1]:
            bit = modifiers.get(modifier.strip().casefold())
            if bit is None or modifier_bits & bit:
                return None
            modifier_bits |= bit

        key_name = parts[-1].strip()
        upper_key = key_name.upper()
        if len(key_name) == 1 and key_name.isascii() and key_name.isalnum():
            virtual_key = ord(upper_key)
        elif upper_key.startswith("F") and upper_key[1:].isdigit():
            function_number = int(upper_key[1:])
            if not 1 <= function_number <= 24:
                return None
            virtual_key = 0x70 + function_number - 1
        else:
            virtual_key = virtual_keys.get(upper_key, 0)
        return (modifier_bits, virtual_key) if virtual_key else None

    def _x11_loop(self) -> None:
        """X11 global hotkey listener loop."""
        try:
            import Xlib.display
            import Xlib.X
            import Xlib.XK
        except ImportError:
            logger.warning("python-xlib not available; hotkeys disabled")
            return

        display = Xlib.display.Display()
        root = display.screen().root

        # Parse and grab each hotkey.
        grabbed: list[tuple] = []
        for hotkey in self._registrations:
            parsed = self._parse(hotkey, display, Xlib.X, Xlib.XK)
            if parsed:
                keycode, modifiers = parsed
                try:
                    root.grab_key(
                        keycode, modifiers, True,
                        Xlib.X.GrabModeAsync, Xlib.X.GrabModeAsync,
                    )
                    grabbed.append((keycode, modifiers, hotkey))
                except Exception as e:
                    logger.error(f"Failed to grab {hotkey}: {e}")

        if not grabbed:
            display.close()
            return

        root.change_attributes(event_mask=Xlib.X.KeyPressMask)

        while not self._stop.is_set():
            if display.pending_events() == 0:
                time.sleep(0.05)
                continue
            event = display.next_event()
            if event.type == Xlib.X.KeyPress:
                # Bridge to the GUI thread; never call callbacks here directly.
                for keycode, modifiers, hotkey in grabbed:
                    if event.detail == keycode:
                        self._fired.emit(hotkey)
                        break

        # Ungrab.
        for keycode, modifiers, _ in grabbed:
            try:
                root.ungrab_key(keycode, modifiers)
            except Exception:
                pass
        display.close()

    @staticmethod
    def _parse(hotkey: str, display, X, XK) -> tuple[int, int] | None:
        """Parse 'Ctrl+Shift+D' into (keycode, modifier_mask)."""
        parts = hotkey.split("+")
        key_name = parts[-1]
        modifiers = 0
        for mod in parts[:-1]:
            if mod == "Ctrl":
                modifiers |= X.ControlMask
            elif mod == "Shift":
                modifiers |= X.ShiftMask
            elif mod == "Alt":
                modifiers |= X.Mod1Mask
        keysym = XK.string_to_keysym(key_name)
        if not keysym:
            return None
        keycode = display.keysym_to_keycode(keysym)
        if not keycode:
            return None
        return keycode, modifiers
