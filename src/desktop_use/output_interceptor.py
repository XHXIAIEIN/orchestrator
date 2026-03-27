"""Output Interceptor — extract structured data before it becomes pixels.

Instead of: screenshot → OCR → text
Do: Win32 API → control text / DOM → structured elements → fallback to OCR

Inspired by Carbonyl's renderer hijacking pattern.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InterceptedContent:
    """Content extracted by interception (not OCR)."""
    text: str
    source: str  # "win32_control", "dom_text", "clipboard", "accessibility"
    element_type: str = ""  # "button", "textbox", "label", "menu", etc.
    bbox: tuple[int, int, int, int] | None = None  # x, y, w, h
    confidence: float = 1.0  # Intercepted = high confidence
    metadata: dict = field(default_factory=dict)


class OutputInterceptor:
    """Extract text/structure from apps without screenshots.

    Priority order (cheapest/most reliable first):
    1. Win32 control text (EnumChildWindows + GetWindowText)
    2. UI Automation (Windows accessibility API)
    3. DOM extraction (for browser tabs via CDP)
    4. Clipboard monitoring
    5. Fallback: screenshot + OCR (most expensive)
    """

    def __init__(self):
        self._strategies: list[tuple[str, callable]] = []
        self._register_default_strategies()

    def _register_default_strategies(self):
        """Register extraction strategies in priority order."""
        self._strategies = [
            ("win32_control", self._extract_win32),
            ("ui_automation", self._extract_uia),
            ("clipboard", self._extract_clipboard),
        ]

    def extract(self, hwnd: int | None = None, **kwargs) -> list[InterceptedContent]:
        """Try all strategies in order. Return first successful result."""
        for name, strategy in self._strategies:
            try:
                results = strategy(hwnd=hwnd, **kwargs)
                if results:
                    logger.debug(f"OutputInterceptor: {name} found {len(results)} elements")
                    return results
            except Exception as e:
                logger.debug(f"OutputInterceptor: {name} failed: {e}")
                continue
        return []

    def extract_all(self, hwnd: int | None = None, **kwargs) -> dict[str, list[InterceptedContent]]:
        """Run ALL strategies, return results keyed by strategy name."""
        all_results = {}
        for name, strategy in self._strategies:
            try:
                results = strategy(hwnd=hwnd, **kwargs)
                if results:
                    all_results[name] = results
            except Exception:
                continue
        return all_results

    def _extract_win32(self, hwnd: int | None = None, **kwargs) -> list[InterceptedContent]:
        """Extract text from Win32 controls using EnumChildWindows."""
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return []

        if not hwnd:
            hwnd = ctypes.windll.user32.GetForegroundWindow()

        results = []

        def _enum_callback(child_hwnd, _):
            length = ctypes.windll.user32.GetWindowTextLengthW(child_hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(child_hwnd, buf, length + 1)
                text = buf.value.strip()
                if text:
                    # Get class name for element type
                    class_buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetClassNameW(child_hwnd, class_buf, 256)

                    # Get position
                    rect = wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(child_hwnd, ctypes.byref(rect))

                    results.append(InterceptedContent(
                        text=text,
                        source="win32_control",
                        element_type=class_buf.value,
                        bbox=(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                        confidence=0.95,
                        metadata={"hwnd": child_hwnd, "class": class_buf.value},
                    ))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        ctypes.windll.user32.EnumChildWindows(hwnd, WNDENUMPROC(_enum_callback), 0)

        return results

    def _extract_uia(self, hwnd: int | None = None, **kwargs) -> list[InterceptedContent]:
        """Extract via Windows UI Automation (placeholder — needs comtypes/uiautomation)."""
        # UI Automation requires comtypes or uiautomation package
        # Placeholder for future implementation
        return []

    def _extract_clipboard(self, **kwargs) -> list[InterceptedContent]:
        """Read current clipboard content."""
        try:
            import ctypes
            ctypes.windll.user32.OpenClipboard(0)
            try:
                if ctypes.windll.user32.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
                    data = ctypes.windll.user32.GetClipboardData(13)
                    text = ctypes.wstring_at(data)
                    if text:
                        return [InterceptedContent(
                            text=text, source="clipboard", confidence=1.0,
                        )]
            finally:
                ctypes.windll.user32.CloseClipboard()
        except Exception:
            pass
        return []


def should_intercept_first(window_class: str) -> bool:
    """Heuristic: should we try interception before screenshot+OCR?

    Win32 native apps → yes (controls have text)
    Browsers → yes (CDP DOM extraction)
    Games/media → no (pixel rendering, no text controls)
    """
    # Apps with good Win32 control text
    native_classes = {"Notepad", "CabinetWClass", "Shell_TrayWnd", "#32770",
                      "ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}
    # Browsers (use CDP instead)
    browser_classes = {"Chrome_WidgetWin_1", "MozillaWindowClass"}
    # Games/media (don't bother)
    skip_classes = {"UnrealWindow", "UnityWndClass", "SDL_app"}

    if window_class in skip_classes:
        return False
    return window_class in native_classes or window_class in browser_classes
