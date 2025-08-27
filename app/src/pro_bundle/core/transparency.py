# transparency.py — apply per-window opacity + optional "pin to back" (Windows)
from __future__ import annotations
import sys

# --------------------------- Windows bindings --------------------------------
if sys.platform.startswith("win"):
    import ctypes
    import ctypes.wintypes as wt

    USER32 = ctypes.windll.user32  # type: ignore[attr-defined]
    DWMAPI = getattr(ctypes.windll, "dwmapi", None)

    # Prefer *Ptr variants on 64-bit
    _have_longptr = hasattr(USER32, "GetWindowLongPtrW") and hasattr(USER32, "SetWindowLongPtrW")
    if _have_longptr:
        GetWindowLongPtrW = USER32.GetWindowLongPtrW
        SetWindowLongPtrW = USER32.SetWindowLongPtrW
        GetWindowLongPtrW.restype = ctypes.c_longlong
        GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
        SetWindowLongPtrW.restype = ctypes.c_longlong
        SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_longlong]
    else:
        GetWindowLongW = USER32.GetWindowLongW
        SetWindowLongW = USER32.SetWindowLongW
        GetWindowLongW.restype = ctypes.c_long
        GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
        SetWindowLongW.restype = ctypes.c_long
        SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]

    EnumWindows = USER32.EnumWindows
    EnumWindows.restype = wt.BOOL
    EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM), wt.LPARAM]

    GetWindowTextLengthW = USER32.GetWindowTextLengthW
    GetWindowTextLengthW.restype = ctypes.c_int
    GetWindowTextLengthW.argtypes = [wt.HWND]

    GetWindowTextW = USER32.GetWindowTextW
    GetWindowTextW.restype = ctypes.c_int
    GetWindowTextW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]

    IsWindowVisible = USER32.IsWindowVisible
    IsWindowVisible.restype = wt.BOOL
    IsWindowVisible.argtypes = [wt.HWND]

    GetParent = USER32.GetParent
    GetParent.restype = wt.HWND
    GetParent.argtypes = [wt.HWND]

    GetClassNameW = USER32.GetClassNameW
    GetClassNameW.restype = ctypes.c_int
    GetClassNameW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]

    SetWindowPos = USER32.SetWindowPos
    SetWindowPos.restype = wt.BOOL
    SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]

    SetLayeredWindowAttributes = USER32.SetLayeredWindowAttributes
    SetLayeredWindowAttributes.restype = wt.BOOL
    SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.COLORREF, ctypes.c_ubyte, ctypes.c_uint]

    # DWM attribute for "cloaked" (hidden UWP/tabbed shells)
    DWMWA_CLOAKED = 14

    # Constants
    GWL_EXSTYLE         = -20
    WS_EX_LAYERED       = 0x00080000
    WS_EX_TOOLWINDOW    = 0x00000080
    WS_EX_APPWINDOW     = 0x00040000

    LWA_ALPHA           = 0x00000002

    HWND_BOTTOM         = wt.HWND(1)
    SWP_NOSIZE          = 0x0001
    SWP_NOMOVE          = 0x0002
    SWP_NOACTIVATE      = 0x0010
    SWP_NOOWNERZORDER   = 0x0200
    SWP_NOSENDCHANGING  = 0x0400
    SWP_ASYNCWINDOWPOS  = 0x4000

    # ----------------------- helpers -----------------------------------------
    def _get_exstyle(hwnd: wt.HWND) -> int:
        if _have_longptr:
            return int(GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
        return int(GetWindowLongW(hwnd, GWL_EXSTYLE))  # type: ignore[name-defined]

    def _set_exstyle(hwnd: wt.HWND, val: int) -> None:
        if _have_longptr:
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, int(val))
        else:
            SetWindowLongW(hwnd, GWL_EXSTYLE, int(val))  # type: ignore[name-defined]

    def _title_of(hwnd: wt.HWND) -> str:
        n = GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowTextW(hwnd, buf, n + 1)
        return (buf.value or "").strip()

    def _is_top_level(hwnd: wt.HWND) -> bool:
        return GetParent(hwnd) == 0

    def _is_tool_window(hwnd: wt.HWND) -> bool:
        try:
            ex = _get_exstyle(hwnd)
            return bool(ex & WS_EX_TOOLWINDOW) and not bool(ex & WS_EX_APPWINDOW)
        except Exception:
            return False

    def _is_cloaked(hwnd: wt.HWND) -> bool:
        if not DWMAPI:
            return False
        try:
            val = wt.DWORD()
            DWMAPI.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                         ctypes.byref(val), ctypes.sizeof(val))
            return val.value != 0
        except Exception:
            return False

    def _iter_visible_windows():
        # EnumWindows walks in Z-order top → bottom
        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def cb(hwnd, _lparam):
            try:
                if not IsWindowVisible(hwnd):
                    return True
                if not _is_top_level(hwnd):
                    return True
                if _is_tool_window(hwnd):
                    return True
                if _is_cloaked(hwnd):
                    return True
                # keep common shell windows out
                clsbuf = ctypes.create_unicode_buffer(256)
                GetClassNameW(hwnd, clsbuf, 255)
                cls = (clsbuf.value or "").strip()
                if cls in {"Shell_TrayWnd", "Button"}:
                    return True
                t = _title_of(hwnd).strip()
                if not t:
                    # untitled — present as bracketed process/class surrogate, so
                    # callers can still match e.g. "[msedge.exe]"
                    t = f"[{cls or 'window'}]"
                windows.append((hwnd, t))
            except Exception:
                return True
            return True

        windows: list[tuple[wt.HWND, str]] = []
        try:
            EnumWindows(cb, 0)
        except Exception:
            pass
        return windows  # Z-order preserved

    def _find_best_hwnd(title_query: str) -> tuple[wt.HWND | None, str]:
        """
        Prefer exact (case-insensitive) title match; then startswith; then substring.
        Also accept bracketed surrogates like "[msedge.exe]" created for untitled windows.
        """
        q = (title_query or "").strip().lower()
        if not q:
            return None, ""

        exact: tuple[wt.HWND | None, str] = (None, "")
        starts: tuple[wt.HWND | None, str] = (None, "")
        sub: tuple[wt.HWND | None, str] = (None, "")

        for hwnd, title in _iter_visible_windows():
            tl = title.lower()
            if tl == q and not exact[0]:
                exact = (hwnd, title)
                break  # earliest Z-order exact match wins
            if tl.startswith(q) and not starts[0]:
                starts = (hwnd, title)
            if (q in tl) and not sub[0]:
                sub = (hwnd, title)

        return exact if exact[0] else (starts if starts[0] else sub)

    def _clamp_opacity(percent: int) -> int:
        # UI uses 20–100; accept 0–100 from callers but coerce to 20–100
        try:
            p = int(percent)
        except Exception:
            p = 85
        if p <= 0:
            p = 20
        return max(20, min(100, p))

    def _apply_alpha(hwnd: wt.HWND, percent: int) -> None:
        alpha = int(_clamp_opacity(percent) * 255 / 100)
        ex = _get_exstyle(hwnd)
        if not (ex & WS_EX_LAYERED):
            _set_exstyle(hwnd, ex | WS_EX_LAYERED)
        # 0 color key, alpha byte, alpha flag
        SetLayeredWindowAttributes(hwnd, 0, ctypes.c_ubyte(alpha), LWA_ALPHA)

    def _pin_to_back(hwnd: wt.HWND) -> None:
        # Push to bottom of Z-order without stealing focus or moving/resizing.
        SetWindowPos(
            hwnd, HWND_BOTTOM, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOSENDCHANGING | SWP_ASYNCWINDOWPOS
        )

    # ----------------------- public API ---------------------------------------
    def apply_external(title_substring: str, opacity: int, pin: bool) -> bool:
        """
        Find a top-level visible window by exact, startswith, or substring title
        (case-insensitive), set its opacity (20–100%), and optionally pin it to
        the back of the Z-order.

        Returns True on success; raises RuntimeError if the window cannot be found.
        """
        hwnd, resolved_title = _find_best_hwnd(title_substring)
        if not hwnd:
            raise RuntimeError(f"Window not found: {title_substring!r}")
        try:
            _apply_alpha(hwnd, opacity)
            if pin:
                _pin_to_back(hwnd)
            return True
        except Exception:
            return False

else:
    # ------------------------ non-Windows stub --------------------------------
    def apply_external(title_substring: str, opacity: int, pin: bool) -> bool:
        # Keep API shape but do nothing on non-Windows platforms
        return False
