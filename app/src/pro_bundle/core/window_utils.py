# window_utils.py — enumerate visible top-level windows (Windows),
# with process/class fallback for untitled & optional UIA tab peek
from __future__ import annotations
import os, sys, time
from typing import Iterable, List, Optional

__all__ = ["refresh_window_list"]

# ---------------------------- Windows implementation -------------------------
if sys.platform.startswith("win"):
    import ctypes
    import ctypes.wintypes as wt

    USER32   = ctypes.windll.user32    # type: ignore[attr-defined]
    KERNEL32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    PSAPI    = ctypes.windll.psapi     # type: ignore[attr-defined]
    DWMAPI   = getattr(ctypes.windll, "dwmapi", None)

    # Win32 APIs
    EnumWindows               = USER32.EnumWindows
    GetWindowTextW            = USER32.GetWindowTextW
    GetWindowTextLengthW      = USER32.GetWindowTextLengthW
    IsWindowVisible           = USER32.IsWindowVisible
    GetWindowLongW            = USER32.GetWindowLongW
    GetClassNameW             = USER32.GetClassNameW
    GetParent                 = USER32.GetParent
    GetWindowThreadProcessId  = USER32.GetWindowThreadProcessId

    OpenProcess               = KERNEL32.OpenProcess
    CloseHandle               = KERNEL32.CloseHandle
    QueryFullProcessImageNameW= getattr(KERNEL32, "QueryFullProcessImageNameW", None)
    GetModuleBaseNameW        = getattr(PSAPI, "GetModuleBaseNameW", None)

    # DWM attribute for "cloaked" (hidden/UWP/tabbed shells)
    DWMWA_CLOAKED = 14

    # Constants
    GWL_EXSTYLE        = -20
    WS_EX_TOOLWINDOW   = 0x00000080
    WS_EX_APPWINDOW    = 0x00040000

    PROCESS_QUERY_INFORMATION          = 0x0400
    PROCESS_VM_READ                    = 0x0010
    PROCESS_QUERY_LIMITED_INFORMATION  = 0x1000

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    # ---------------------------- helpers ------------------------------------
    def _is_top_level(hwnd: wt.HWND) -> bool:
        return GetParent(hwnd) == 0

    def _is_tool_window(hwnd: wt.HWND) -> bool:
        try:
            ex = int(GetWindowLongW(hwnd, GWL_EXSTYLE))
            return bool(ex & WS_EX_TOOLWINDOW) and not bool(ex & WS_EX_APPWINDOW)
        except Exception:
            return False

    def _is_cloaked(hwnd: wt.HWND) -> bool:
        if not DWMAPI:
            return False
        try:
            val = wt.DWORD()
            DWMAPI.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
            return val.value != 0
        except Exception:
            return False

    def _title(hwnd: wt.HWND) -> str:
        try:
            n = int(GetWindowTextLengthW(hwnd))
            if n <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(n + 1)
            GetWindowTextW(hwnd, buf, n + 1)
            return (buf.value or "").strip()
        except Exception:
            return ""

    def _wclass(hwnd: wt.HWND) -> str:
        try:
            buf = ctypes.create_unicode_buffer(256)
            GetClassNameW(hwnd, buf, 255)
            return (buf.value or "").strip()
        except Exception:
            return ""

    def _pid(hwnd: wt.HWND) -> Optional[int]:
        try:
            pid = wt.DWORD()
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return int(pid.value) if pid.value else None
        except Exception:
            return None

    def _basename_from_handle(hproc) -> Optional[str]:
        # Prefer modern API
        try:
            if QueryFullProcessImageNameW is not None:
                size = wt.DWORD(32768)
                buf = ctypes.create_unicode_buffer(size.value)
                if QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                    return os.path.basename(buf.value).lower()
        except Exception:
            pass
        # Fallback
        try:
            if GetModuleBaseNameW is not None:
                buf = ctypes.create_unicode_buffer(260)
                if GetModuleBaseNameW(hproc, None, buf, 259) > 0:
                    return (buf.value or "").strip().lower()
        except Exception:
            pass
        return None

    def _proc_name(pid: int) -> Optional[str]:
        for access in (PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_QUERY_INFORMATION | PROCESS_VM_READ):
            try:
                h = OpenProcess(access, False, pid)
                if h:
                    try:
                        return _basename_from_handle(h)
                    finally:
                        CloseHandle(h)
            except Exception:
                continue
        return None

    def _normalize_excludes(extras: Optional[Iterable[str]]) -> set[str]:
        s = {x.strip().lower() for x in (extras or []) if x and x.strip()}
        env = os.getenv("GLASS_EXCLUDE_PROCESSES", "")
        if env:
            for part in env.split(","):
                part = part.strip().lower()
                if part:
                    s.add(part)
        return s

    def _self_names() -> set[str]:
        out: set[str] = set()
        try:
            me = os.path.basename(sys.executable).lower()
            if me:
                out.add(me)
        except Exception:
            pass
        if getattr(sys, "frozen", False):
            try:
                out.add(os.path.basename(sys.executable).lower())
            except Exception:
                pass
        return out

    # -------------------- (optional) UI Automation tabs -----------------------
    # Best-effort: try to enumerate browser tab names without breaking callers.
    # Disabled by default; enable with include_tabs=True or env GLASS_INCLUDE_TABS=1
    try:
        import comtypes  # type: ignore
        from comtypes.client import CreateObject  # type: ignore
        from comtypes.gen import UIAutomationClient as UIA  # type: ignore
        _HAVE_UIA = True
    except Exception:
        _HAVE_UIA = False

    _BROWSER_EXES = {
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "opera_gx.exe", "vivaldi.exe"
    }

    def _try_list_browser_tabs(hwnd: wt.HWND, timeout_ms: int = 80) -> List[str]:
        """
        Return tab names under a browser window, or [] if unsupported/unavailable.
        Time-boxed for snappy UX.
        """
        if not _HAVE_UIA:
            return []
        t0 = time.perf_counter()
        try:
            # Quick process gate
            p = _pid(hwnd)
            if p is None:
                return []
            pname = (_proc_name(p) or "")
            if pname not in _BROWSER_EXES:
                return []

            # Spin up UIA (cheap, but keep an eye on time)
            uia = CreateObject(UIA.CUIAutomation)  # type: ignore

            # Root from this hwnd
            elem = uia.ElementFromHandle(hwnd)     # IUIAutomationElement

            # Find all TabItems in subtree
            cond = uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_TabItemControlTypeId)
            coll = elem.FindAll(UIA.TreeScope_Subtree, cond)

            names: List[str] = []
            # Iterate with short-circuit if we exceed our time budget
            for i in range(coll.Length):  # type: ignore[attr-defined]
                if (time.perf_counter() - t0) * 1000.0 > timeout_ms:
                    break
                e = coll.GetElement(i)  # type: ignore[attr-defined]
                # Prefer cached CurrentName; fallback to property fetch
                try:
                    n = e.CurrentName  # type: ignore[attr-defined]
                except Exception:
                    try:
                        n = e.GetCurrentPropertyValue(UIA.UIA_NamePropertyId)
                    except Exception:
                        n = ""
                n = (n or "").strip()
                if n:
                    names.append(n)

            # De-dup while preserving order
            seen = set()
            out = []
            for n in names:
                k = n.lower()
                if k in seen:
                    continue
                seen.add(k)
                out.append(n)
            return out
        except Exception:
            return []

    # ---------------------------- public API ----------------------------------
    def refresh_window_list(
        *,
        exclude_self: bool = True,
        exclude_processes: Optional[Iterable[str]] = None,
        order: str = "z",                  # "z" (top→bottom) or "alpha"
        include_tabs: bool = False,        # experimental: include browser tab *names* (for preview)
        include_untitled: bool = True      # show untitled as [process.exe] / [class]
    ) -> List[str]:
        """
        Return a list of unique, visible top-level window titles.

        • Excludes tool & cloaked windows and the shell tray.
        • Optionally excludes our own process and/or additional processes.
        • Z-order by default; pass order='alpha' for alphabetical.
        • If include_tabs=True (or env GLASS_INCLUDE_TABS=1), we *peek* tab names
          for possible future UI preview, but we do NOT add them to the returned list
          (so title-based targeting remains stable).
        • If include_untitled=True, we surface untitled windows as [process.exe] or [ClassName].
        """
        want_tabs = include_tabs or os.getenv("GLASS_INCLUDE_TABS", "").strip() in {"1", "true", "yes"}

        excludes = _normalize_excludes(exclude_processes)
        if exclude_self:
            excludes |= _self_names()

        titles: List[str] = []
        seen_titles = set()

        @WNDENUMPROC
        def _cb(hwnd, _lparam):
            try:
                if not IsWindowVisible(hwnd): return True
                if not _is_top_level(hwnd):   return True
                if _is_tool_window(hwnd):     return True
                if _is_cloaked(hwnd):         return True

                cls = _wclass(hwnd)
                if cls in {"Shell_TrayWnd", "Button"}:
                    return True

                t = _title(hwnd)
                pid = _pid(hwnd)

                # Process-based exclude
                if pid is not None and excludes:
                    pname = (_proc_name(pid) or "")
                    if pname in excludes:
                        return True

                # Build a surrogate title if untitled and allowed
                if not t:
                    if include_untitled:
                        surrogate = (_proc_name(pid) if pid is not None else None) or cls or "window"
                        t = f"[{surrogate}]"
                    else:
                        return True

                # De-dup by case-insensitive title
                key = t.lower()
                if key in seen_titles:
                    return True
                seen_titles.add(key)
                titles.append(t)

                # Optional: collect tab names (for UI preview only)
                if want_tabs:
                    for _tab in _try_list_browser_tabs(hwnd):
                        # Not appended to titles; keep API stable.
                        pass
            except Exception:
                return True
            return True

        try:
            EnumWindows(_cb, 0)
        except Exception:
            pass

        if order.lower().startswith("a"):
            titles.sort(key=str.lower)

        return titles

# ---------------------------- Non-Windows stub --------------------------------
else:
    def refresh_window_list(
        *, exclude_self: bool = True, exclude_processes: Optional[Iterable[str]] = None,
        order: str = "z", include_tabs: bool = False, include_untitled: bool = True
    ) -> List[str]:
        # Other platforms: let caller fall back safely.
        return []
