"""WindowManager — find, focus, capture, and send input to specific windows.

Two operating modes:
- Foreground: focus the window, then use pyautogui (existing behavior)
- Background: use Win32 SendMessage / pywinauto to interact without focusing

Background mode works for most standard Win32 apps (Notepad, Explorer, Office).
Some apps (DirectX, UWP, Electron) may need foreground mode.
"""
import ctypes
import ctypes.wintypes
import logging
import subprocess
import time
from dataclasses import dataclass, field
from io import BytesIO

try:
    from PIL import Image
except ImportError:
    Image = None

log = logging.getLogger(__name__)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    class_name: str
    rect: tuple[int, int, int, int]  # (left, top, right, bottom)

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


class WindowManager:
    """Find and interact with specific windows by title, PID, or HWND."""

    def __init__(self):
        self._target: WindowInfo | None = None

    @property
    def target(self) -> WindowInfo | None:
        """Currently locked target window."""
        return self._target

    # ------------------------------------------------------------------
    # Window discovery
    # ------------------------------------------------------------------

    @staticmethod
    def find_windows(title_contains: str = "", process_name: str = "",
                     class_name: str = "") -> list[WindowInfo]:
        """Find all visible windows matching the given criteria."""
        results: list[WindowInfo] = []
        title_lower = title_contains.lower()
        proc_lower = process_name.lower()

        # Get PID→process name mapping if needed
        pid_map: dict[int, str] = {}
        if proc_lower:
            pid_map = WindowManager._build_pid_map()

        def enum_callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True

            # Get title
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            win_title = buf.value
            if not win_title:
                return True

            # Title filter
            if title_lower and title_lower not in win_title.lower():
                return True

            # Get PID
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pid_val = pid.value

            # Process name filter
            if proc_lower:
                pname = pid_map.get(pid_val, "").lower()
                if proc_lower not in pname:
                    return True

            # Class name filter
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buf, 256)
            cls = cls_buf.value
            if class_name and class_name.lower() not in cls.lower():
                return True

            # Get window rect
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

            results.append(WindowInfo(
                hwnd=hwnd,
                title=win_title,
                pid=pid_val,
                class_name=cls,
                rect=(rect.left, rect.top, rect.right, rect.bottom),
            ))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong, ctypes.c_ulong)
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
        return results

    def lock(self, title_contains: str = "", process_name: str = "",
             hwnd: int = 0) -> WindowInfo | None:
        """Lock onto a target window. Returns WindowInfo or None if not found."""
        if hwnd:
            self._target = self._info_from_hwnd(hwnd)
            if self._target:
                log.info(f"WindowManager: locked onto hwnd={hwnd} '{self._target.title}'")
            return self._target

        wins = self.find_windows(title_contains=title_contains,
                                 process_name=process_name)
        if not wins:
            log.warning(f"WindowManager: no window found "
                        f"(title='{title_contains}', process='{process_name}')")
            return None

        self._target = wins[0]
        log.info(f"WindowManager: locked onto '{self._target.title}' "
                 f"(hwnd={self._target.hwnd}, pid={self._target.pid})")
        return self._target

    def unlock(self):
        """Release window lock."""
        self._target = None

    def refresh(self) -> WindowInfo | None:
        """Refresh the target window's rect (in case it moved/resized)."""
        if not self._target:
            return None
        self._target = self._info_from_hwnd(self._target.hwnd)
        return self._target

    def is_alive(self) -> bool:
        """Check if the target window still exists."""
        if not self._target:
            return False
        return bool(user32.IsWindow(self._target.hwnd))

    # ------------------------------------------------------------------
    # Foreground control
    # ------------------------------------------------------------------

    def focus(self) -> bool:
        """Bring target window to foreground. Returns True on success."""
        if not self._target:
            return False
        hwnd = self._target.hwnd

        # If minimized, restore first
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            time.sleep(0.2)

        # SetForegroundWindow sometimes fails if calling process isn't foreground.
        # Workaround: attach to target thread temporarily.
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        if current_thread != target_thread:
            user32.AttachThreadInput(current_thread, target_thread, True)

        result = user32.SetForegroundWindow(hwnd)

        if current_thread != target_thread:
            user32.AttachThreadInput(current_thread, target_thread, False)

        if result:
            time.sleep(0.15)
        return bool(result)

    # ------------------------------------------------------------------
    # Window-specific screenshot (works even if window is behind others)
    # ------------------------------------------------------------------

    def capture_window(self) -> bytes | None:
        """Capture the target window using Win32 PrintWindow.
        Works even if the window is partially or fully occluded."""
        if not self._target or Image is None:
            return None

        hwnd = self._target.hwnd
        self.refresh()
        if not self._target:
            return None

        w = self._target.width
        h = self._target.height
        if w <= 0 or h <= 0:
            return None

        # Create compatible DC and bitmap
        hwnd_dc = user32.GetWindowDC(hwnd)
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
        old_bmp = gdi32.SelectObject(mem_dc, bitmap)

        # PrintWindow with PW_RENDERFULLCONTENT (flag 2) for modern apps
        PW_RENDERFULLCONTENT = 2
        user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)

        # Read bitmap bits
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32),
                ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB

        buf_size = w * h * 4
        buf = ctypes.create_string_buffer(buf_size)
        gdi32.GetDIBits(mem_dc, bitmap, 0, h, buf, ctypes.byref(bmi), 0)

        # Cleanup GDI resources
        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)

        # Convert BGRA → RGB PIL Image → PNG bytes
        img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
        img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    # ------------------------------------------------------------------
    # Background input (no foreground focus needed)
    # ------------------------------------------------------------------

    def send_text(self, text: str) -> bool:
        """Send text to target window via clipboard + WM_PASTE. No focus required.

        Uses clipboard because:
        - WM_CHAR doesn't work on modern controls (RichEditD2DPT, DirectWrite)
        - Bypasses IME interference (CJK input methods)
        - Works on virtually all editable controls

        Automatically finds the deepest editable child control (Edit, RichEdit,
        RichEditD2DPT, NotepadTextBox, etc.) to send WM_PASTE to.
        """
        if not self._target:
            return False

        # Find the actual editable control (may be a child of the main window)
        edit_hwnd = self._find_edit_control(self._target.hwnd)
        target_hwnd = edit_hwnd or self._target.hwnd
        if edit_hwnd:
            log.debug(f"WindowManager: send_text to edit control hwnd={edit_hwnd}")

        # Set clipboard via Win32 API (faster than PowerShell subprocess)
        if not self._set_clipboard(text):
            return False

        # Send WM_PASTE to the editable control
        WM_PASTE = 0x0302
        user32.SendMessageW(target_hwnd, WM_PASTE, 0, 0)
        time.sleep(0.05)
        return True

    @staticmethod
    def _find_edit_control(parent_hwnd: int) -> int | None:
        """Recursively find the deepest editable child control.
        Handles Win11 Notepad (RichEditD2DPT), classic Notepad (Edit),
        and other common editable controls."""
        EDIT_CLASSES = {"edit", "richedit", "richedit20w", "richeditd2dpt",
                        "notepadtextbox", "scintilla", "textbox"}
        found = []

        def callback(child_hwnd, _):
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(child_hwnd, cls_buf, 256)
            cls = cls_buf.value.lower()
            if cls in EDIT_CLASSES:
                found.append((child_hwnd, cls))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong, ctypes.c_ulong)
        user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(callback), 0)

        if not found:
            return None

        # Prefer the most specific control (RichEditD2DPT > Edit > NotepadTextBox)
        priority = ["richeditd2dpt", "richedit20w", "richedit", "edit",
                     "scintilla", "notepadtextbox", "textbox"]
        for pclass in priority:
            for hwnd, cls in found:
                if cls == pclass:
                    return hwnd
        return found[0][0]

    @staticmethod
    def _set_clipboard(text: str) -> bool:
        """Set clipboard content using Win32 API."""
        CF_UNICODETEXT = 13
        GHND = 0x0042  # GMEM_MOVEABLE | GMEM_ZEROINIT

        kernel32 = ctypes.windll.kernel32
        # Set argtypes for proper 64-bit pointer handling
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        if not user32.OpenClipboard(0):
            return False
        try:
            user32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            h = kernel32.GlobalAlloc(GHND, len(data))
            if not h:
                log.error("WindowManager: GlobalAlloc failed")
                return False
            p = kernel32.GlobalLock(h)
            if not p:
                log.error("WindowManager: GlobalLock failed")
                return False
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            user32.SetClipboardData(CF_UNICODETEXT, h)
            return True
        finally:
            user32.CloseClipboard()

    def send_click(self, x: int, y: int, button: str = "left") -> bool:
        """Send a click at window-local coords via PostMessage. No focus required."""
        if not self._target:
            return False
        hwnd = self._target.hwnd
        lparam = y << 16 | (x & 0xFFFF)

        if button == "left":
            WM_DOWN, WM_UP = 0x0201, 0x0202  # WM_LBUTTONDOWN, WM_LBUTTONUP
        elif button == "right":
            WM_DOWN, WM_UP = 0x0204, 0x0205  # WM_RBUTTONDOWN, WM_RBUTTONUP
        else:
            WM_DOWN, WM_UP = 0x0201, 0x0202

        user32.PostMessageW(hwnd, WM_DOWN, 1, lparam)
        time.sleep(0.02)
        user32.PostMessageW(hwnd, WM_UP, 0, lparam)
        return True

    def send_hotkey(self, *keys: str) -> bool:
        """Send a hotkey combination via PostMessage. No focus required."""
        if not self._target:
            return False
        hwnd = self._target.hwnd
        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101

        vk_map = self._vk_map()
        vk_codes = []
        for key in keys:
            vk = vk_map.get(key.lower())
            if vk is None:
                # Single character
                vk = ord(key.upper()) if len(key) == 1 else 0
            vk_codes.append(vk)

        # Key down in order
        for vk in vk_codes:
            user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
            time.sleep(0.01)
        # Key up in reverse order
        for vk in reversed(vk_codes):
            user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)
            time.sleep(0.01)
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _info_from_hwnd(hwnd: int) -> WindowInfo | None:
        """Build WindowInfo from an HWND. Returns None if window is gone."""
        if not user32.IsWindow(hwnd):
            return None
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value

        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)

        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        return WindowInfo(
            hwnd=hwnd, title=title, pid=pid.value,
            class_name=cls_buf.value,
            rect=(rect.left, rect.top, rect.right, rect.bottom),
        )

    @staticmethod
    def _build_pid_map() -> dict[int, str]:
        """Build PID → process name mapping via tasklist."""
        try:
            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            mapping = {}
            for line in out.strip().split("\n"):
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    try:
                        mapping[int(parts[1])] = parts[0]
                    except ValueError:
                        pass
            return mapping
        except Exception:
            return {}

    @staticmethod
    def _vk_map() -> dict[str, int]:
        """Common key name → Win32 virtual key code."""
        return {
            "ctrl": 0x11, "control": 0x11,
            "alt": 0x12, "menu": 0x12,
            "shift": 0x10,
            "win": 0x5B, "lwin": 0x5B,
            "enter": 0x0D, "return": 0x0D,
            "tab": 0x09,
            "esc": 0x1B, "escape": 0x1B,
            "backspace": 0x08, "back": 0x08,
            "delete": 0x2E, "del": 0x2E,
            "space": 0x20,
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
            "home": 0x24, "end": 0x23,
            "pageup": 0x21, "pagedown": 0x22,
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
            "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
            "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
            "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44,
            "e": 0x45, "f": 0x46, "g": 0x47, "h": 0x48,
            "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
            "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50,
            "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
            "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
            "y": 0x59, "z": 0x5A,
        }
