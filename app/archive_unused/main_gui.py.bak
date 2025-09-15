# main_gui.py — Glass (Free→Pro) with neat UI, Dark Mode + Follow System Theme,
# Pro-only: Pin on top, Ghost click-through, Lock (on-top+ghost)
from __future__ import annotations
import os, sys, json, time, atexit, platform, webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

import tkinter as tk
from tkinter import ttk, messagebox

# =============================== Config =======================================
APP_NAME    = "Glass"
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
DOMAIN      = (os.getenv("GLASS_DOMAIN") or os.getenv("DOMAIN") or "https://www.glassapp.me").rstrip("/")
GLASS_LOG   = os.getenv("GLASS_LOG", "0") in ("1","true","True")
PRO_BUY_URL = (os.getenv("PRO_BUY_URL") or "").strip()

TOKEN_PATH     = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME / "license.json"
SETTINGS_PATH  = TOKEN_PATH.parent / "settings.json"
CAPS           = {"free": 1, "starter": 2, "pro": 5}

LIVE_DEBOUNCE_MS   = 100
FOLLOW_POLL_MS     = 300
LIST_FILTER_MS     = 120
AUTO_REFRESH_MS    = 30_000
VALIDATE_EVERY_HRS = 24
SKIP_REFRESH_DURING_LIVE = True
AUTO_ELEVATE_ON_START = True

def log(*a): 
    if GLASS_LOG: print("[GLASS]", *a, flush=True)

# ============================== License client ================================
def _hwid() -> str:
    node = os.environ.get("COMPUTERNAME") or platform.node() or "HOST"
    return f"nt-{node}"

def _save_token(tok: str):
    try:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(json.dumps({"token": tok}), encoding="utf-8")
    except Exception: pass

def _load_token() -> Optional[str]:
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8")).get("token")
    except Exception:
        return None

def _post_json(url: str, payload: Dict[str, Any], timeout: float = 8.0) -> Dict[str, Any]:
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            url, data=_json.dumps(payload, separators=(",",":")).encode("utf-8"),
            headers={"Content-Type":"application/json","User-Agent":"Glass/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            return _json.loads(body) if body else {}
    except Exception as e:
        log("POST fail", url, type(e).__name__)
        return {}

def license_activate(key: str) -> Dict[str, Any]:
    data = {"hwid": _hwid(), "key": key.strip(), "app_version": APP_VERSION}
    r = _post_json(f"{DOMAIN}/license/activate", data, timeout=8.0)
    if r.get("ok") and r.get("token"): _save_token(r["token"])
    return r

def license_validate() -> Dict[str, Any]:
    tok = _load_token()
    if not tok: return {"ok": False, "reason": "no_token"}
    data = {"hwid": _hwid(), "token": tok, "app_version": APP_VERSION}
    return _post_json(f"{DOMAIN}/license/validate", data, timeout=6.0)

# ============================= Win32 primitives ===============================
IS_WIN = (os.name == "nt")
if IS_WIN:
    import ctypes
    from ctypes import wintypes
    user32  = ctypes.windll.user32
    kernel32= ctypes.windll.kernel32
    dwmapi  = getattr(ctypes.windll, "dwmapi", None)

    GetWindowText       = user32.GetWindowTextW
    GetWindowTextLength = user32.GetWindowTextLengthW
    GetClassNameW       = user32.GetClassNameW
    EnumWindows         = user32.EnumWindows
    EnumWindowsProc     = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    GetAncestor         = user32.GetAncestor
    GetWindow           = user32.GetWindow
    GetForegroundWindow = user32.GetForegroundWindow
    IsWindowVisible     = user32.IsWindowVisible
    GetWindowLongPtr    = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    SetWindowLongPtr    = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    SetLayeredWindowAttributes = user32.SetLayeredWindowAttributes
    SetWindowPos        = user32.SetWindowPos
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId

    OpenProcess = kernel32.OpenProcess
    CloseHandle = kernel32.CloseHandle
    QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW

    GWL_EXSTYLE   = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    LWA_ALPHA     = 0x00000002

    GA_ROOT = 2
    GW_OWNER = 4

    HWND_BOTTOM     = 1
    HWND_TOPMOST    = -1
    HWND_NOTOPMOST  = -2
    SWP_NOSIZE      = 0x0001
    SWP_NOMOVE      = 0x0002
    SWP_NOACTIVATE  = 0x0010
    SWP_SHOWWINDOW  = 0x0040

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    DWMWA_CLOAKED = 14

def is_admin() -> bool:
    if not IS_WIN: return True
    try: return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception: return False

def restart_as_admin():
    if not IS_WIN: return
    try:
        params = " ".join(f'"{a}"' if " " in a else a for a in sys.argv)
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        os._exit(0)
    except Exception: pass

def _is_cloaked(hwnd) -> bool:
    if not dwmapi: return False
    try:
        cloaked = wintypes.DWORD()
        dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        return cloaked.value != 0
    except Exception:
        return False

def _proc_name(hwnd) -> str:
    try:
        pid = wintypes.DWORD(0)
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value: return ""
        h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h: return ""
        try:
            size = wintypes.DWORD(32768)
            buf  = ctypes.create_unicode_buffer(size.value)
            if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            CloseHandle(h)
    except Exception: pass
    return ""

def _class_name(hwnd) -> str:
    try:
        buf = ctypes.create_unicode_buffer(256)
        if GetClassNameW(hwnd, buf, 256): return buf.value
    except Exception: pass
    return ""

def _title_of(hwnd) -> str:
    try:
        n = GetWindowTextLength(hwnd)
        if n <= 0: return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowText(hwnd, buf, n + 1)
        return (buf.value or "").strip()
    except Exception:
        return ""

def enum_app_windows(show_all: bool=False) -> List[Tuple[str,int]]:
    if not IS_WIN: return [("Desktop", 0)]
    out: List[Tuple[str,int]] = []
    def include(hwnd) -> bool:
        if GetAncestor(hwnd, GA_ROOT) != hwnd: return False
        if not IsWindowVisible(hwnd): return False
        if not show_all:
            if _is_cloaked(hwnd): return False
            ex = GetWindowLongPtr(hwnd, GWL_EXSTYLE)
            owner = GetWindow(hwnd, GW_OWNER)
            if (owner == 0 and not (ex & 0x80)) or (ex & 0x00040000): return True
            return False
        return True

    def cb(hwnd, _l):
        if include(hwnd):
            t = _title_of(hwnd) or f"[{_proc_name(hwnd) or _class_name(hwnd) or 'window'}]"
            out.append((t, int(hwnd)))
        return True

    EnumWindows(EnumWindowsProc(cb), 0)

    uniq: List[Tuple[str,int]] = []
    seen = set()
    for t,h in out:
        if t not in seen:
            seen.add(t); uniq.append((t,h))
    try:
        fg = GetForegroundWindow()
        if fg:
            fgt = next((t for t,h in uniq if h == fg), None)
            if fgt:
                uniq = [(t,h) for t,h in uniq if h != fg]
                uniq.insert(0, (fgt, fg))
    except Exception: pass
    return uniq or [("Desktop", 0)]

def apply_opacity(hwnd: int, opacity_pct: int,
                  pin_to_back: bool=False,  # kept for compatibility (unused)
                  topmost: Optional[bool]=None, ghost: Optional[bool]=None) -> bool:
    if not IS_WIN: return False
    try:
        ex = GetWindowLongPtr(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_LAYERED == 0:
            SetWindowLongPtr(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)

        if ghost is not None:
            ex = GetWindowLongPtr(hwnd, GWL_EXSTYLE)
            if ghost and (ex & WS_EX_TRANSPARENT) == 0:
                SetWindowLongPtr(hwnd, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT | WS_EX_LAYERED)
            if not ghost and (ex & WS_EX_TRANSPARENT) != 0:
                SetWindowLongPtr(hwnd, GWL_EXSTYLE, (ex & ~WS_EX_TRANSPARENT) | WS_EX_LAYERED)

        alpha = max(51, min(255, int(opacity_pct * 255 / 100)))  # 20..100%
        if not SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA):
            return False

        if topmost is True:
            SetWindowPos(hwnd, HWND_TOPMOST, 0,0,0,0, SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE|SWP_SHOWWINDOW)
        elif topmost is False:
            SetWindowPos(hwnd, HWND_NOTOPMOST, 0,0,0,0, SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE|SWP_SHOWWINDOW)

        return True
    except Exception as e:
        log("apply_opacity err", type(e).__name__)
        return False

def revert_window(hwnd: int):
    if not IS_WIN: return
    try:
        ex = GetWindowLongPtr(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TRANSPARENT:
            SetWindowLongPtr(hwnd, GWL_EXSTYLE, ex & ~WS_EX_TRANSPARENT)
        if ex & WS_EX_LAYERED:
            SetWindowLongPtr(hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)
        SetWindowPos(hwnd, 0, 0,0,0,0, SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE|SWP_SHOWWINDOW)
    except Exception: pass

# ----------------------- System Theme (Windows) helpers -----------------------
def _system_theme_is_dark() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as k:
            v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")  # 0=Dark,1=Light
            return int(v) == 0
    except Exception:
        return False

# ================================= GUI =======================================
class GlassApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("760x480+120+90")
        self.minsize(560, 360)
        self._try_icon()

        # state
        self.is_pro = False
        self.tier = "free"
        self.max_concurrent = CAPS["free"]
        self.pro_download_url = ""
        self.per_window: Dict[str, Dict[str, Any]] = {}
        self.hwnd_by_title: Dict[str,int] = {}
        self.window_cache: List[Tuple[str,int]] = []
        self.follow_enabled = tk.BooleanVar(value=False)
        self._last_validate = 0.0
        self._live_pending = False
        self._filter_job = None
        self._auto_job = None
        self._follow_job = None
        self._toast_job = None

        # theme state
        self.dark_mode = tk.BooleanVar(value=False)
        self.follow_system = tk.BooleanVar(value=False)
        self._theme_job = None
        self._theme_dark_current = None

        # admin hint
        if IS_WIN and not is_admin() and AUTO_ELEVATE_ON_START:
            if messagebox.askyesno("Administrator needed",
                                   "Some apps may require Administrator to change opacity.\n\n"
                                   "Restart Glass as Administrator now?"):
                restart_as_admin()

        self._build_ui()
        self._bind_hotkeys()
        self._load_last_state()
        self._apply_theme_from_prefs()
        self._start_theme_watcher()

        self._refresh_windows()
        self._validate_token_silent(startup=True)
        self._schedule_periodic()

    def _try_icon(self):
        try:
            here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
            for p in [here / "assets" / "glass.ico",
                      Path(__file__).resolve().parent / "assets" / "glass.ico"]:
                if p.exists():
                    self.iconbitmap(default=str(p)); break
        except Exception: pass

    # ----------------------------- Theme ---------------------------------
    def _apply_theme(self, dark: bool):
        self.dark_mode.set(bool(dark))
        bg   = "#111418" if dark else "#ffffff"
        fg   = "#e9eef5" if dark else "#0f141a"
        mut  = "#9fb0c0" if dark else "#637182"
        acc  = "#2563eb" if dark else "#1f4bdd"

        style = ttk.Style(self)
        try: style.theme_use("clam")
        except Exception: pass

        for k in (".","TFrame","TLabelframe","TLabel"):
            style.configure(k, background=bg, foreground=fg)
        style.configure("Muted.TLabel", foreground=mut, background=bg)
        style.configure("Header.TLabel", font=("Segoe UI", 15, "bold"), foreground=fg, background=bg)

        style.configure("TEntry", fieldbackground=("#1a1f24" if dark else "#ffffff"),
                        foreground=fg, background=bg, borderwidth=1, relief="solid")
        style.map("TButton", foreground=[("disabled", mut)],
                  background=[("!disabled", acc)])

        self.configure(background=bg)

    def _apply_theme_from_prefs(self):
        dark = self.dark_mode.get()
        if self.follow_system.get():
            dark = _system_theme_is_dark()
        self._apply_theme(dark)
        self._theme_dark_current = dark

    def _start_theme_watcher(self):
        if self._theme_job:
            try: self.after_cancel(self._theme_job)
            except Exception: pass
        def tick():
            if self.follow_system.get():
                desired = _system_theme_is_dark()
                if desired != self._theme_dark_current:
                    self._apply_theme(desired)
                    self._theme_dark_current = desired
            self._theme_job = self.after(3000, tick)
        tick()

    # ------------------------------ UI -----------------------------------
    def _build_ui(self):
        # Header
        top = ttk.Frame(self); top.pack(fill="x", padx=12, pady=(12,6))
        self.title_link = ttk.Label(top, text=APP_NAME, style="Header.TLabel", cursor="hand2")
        self.title_link.pack(side="left"); self.title_link.bind("<Button-1>", lambda _e: self._open_url(DOMAIN))
        ttk.Label(top, text=f"v{APP_VERSION}", style="Muted.TLabel").pack(side="left", padx=(8,0))
        self.badge = ttk.Label(top, text=self._badge_text(), style="Muted.TLabel", cursor="hand2")
        self.badge.pack(side="right"); self.badge.bind("<Button-1>", lambda _e: self._badge_click())

        # Body
        body = ttk.Frame(self); body.pack(fill="both", expand=True, padx=12, pady=(6,8))
        left = ttk.Labelframe(body, text="Windows"); left.pack(side="left", fill="both", expand=True)
        right = ttk.Labelframe(body, text="Controls"); right.pack(side="left", fill="both", expand=True, padx=(8,0))

        # Left
        lf = ttk.Frame(left); lf.pack(fill="x", padx=10, pady=(10,6))
        self.var_filter = tk.StringVar()
        ent = ttk.Entry(lf, textvariable=self.var_filter); ent.pack(side="left", fill="x", expand=True)
        ttk.Button(lf, text="Clear", command=lambda:(self.var_filter.set(""), self._update_list())).pack(side="left", padx=(8,0))
        self.var_show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(lf, text="Show all", variable=self.var_show_all,
                        command=lambda:self._refresh_windows(user=True)).pack(side="left", padx=(10,0))

        self.listbox = tk.Listbox(left, activestyle="none", exportselection=False)
        self.listbox.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_select())

        row = ttk.Frame(left); row.pack(fill="x", padx=10, pady=(0,10))
        ttk.Button(row, text="Refresh (F5)", command=lambda:self._refresh_windows(user=True)).pack(side="left")
        ttk.Button(row, text="Revert all", command=self._revert_all).pack(side="left", padx=(8,0))
        ttk.Checkbutton(row, text="Follow active window", variable=self.follow_enabled,
                        command=self._toggle_follow).pack(side="right")

        # Right
        self.lbl_sel = ttk.Label(right, text="(no window selected)", style="Muted.TLabel")
        self.lbl_sel.pack(anchor="w", padx=10, pady=(10,2))

        self.var_opacity = tk.IntVar(value=85)
        row2 = ttk.Frame(right); row2.pack(fill="x", padx=10)
        ttk.Label(row2, text="Opacity").pack(side="left")
        self.lbl_pct = ttk.Label(row2, text="85%"); self.lbl_pct.pack(side="right")
        self.scale = ttk.Scale(right, from_=20, to=100, value=85, orient="horizontal",
                               command=lambda _v: self._on_slider())
        self.scale.pack(fill="x", padx=10)

        opts = ttk.Frame(right); opts.pack(anchor="w", padx=10, pady=(8,4))
        self.var_on_top = tk.BooleanVar(value=False)   # Pro
        self.var_ghost  = tk.BooleanVar(value=False)   # Pro
        self.var_live   = tk.BooleanVar(value=False)

        ttk.Checkbutton(opts, text="Live apply", variable=self.var_live).pack(side="left")
        ttk.Checkbutton(opts, text="Pin on top (Pro, Ctrl+P)", variable=self.var_on_top,
                        command=lambda:self._maybe_live()).pack(side="left", padx=(12,0))
        ttk.Checkbutton(opts, text="Ghost (Pro, Ctrl+G)", variable=self.var_ghost,
                        command=lambda:self._maybe_live()).pack(side="left", padx=(12,0))

        preset = ttk.Frame(right); preset.pack(anchor="w", padx=10, pady=(8,4))
        self.var_preset = tk.IntVar(value=75)
        ttk.Label(preset, text="Preset %").pack(side="left")
        ttk.Entry(preset, textvariable=self.var_preset, width=4).pack(side="left", padx=(6,10))
        ttk.Button(preset, text="Apply preset", command=self._apply_preset).pack(side="left")

        lockrow = ttk.Frame(right); lockrow.pack(anchor="w", padx=10, pady=(6,4))
        ttk.Label(lockrow, text="Lock (on-top+ghost)  Ctrl+L").pack(side="left")

        act = ttk.Frame(right); act.pack(fill="x", padx=10, pady=(8,12))
        ttk.Button(act, text="Apply  Ctrl+Enter", command=self._apply_selected).pack(side="left")
        ttk.Button(act, text="Reset to 100%  Ctrl+0", command=self._reset_selected).pack(side="left", padx=(8,0))

        # Footer status
        self.status = ttk.Label(self, text="", style="Muted.TLabel")
        self.status.pack(fill="x", padx=12, pady=(0,10))
        self._build_status_bar()
        self.bind("<F5>", lambda _e: self._refresh_windows(user=True))
        ent.bind("<KeyRelease>", lambda _e: self._debounce_filter())

        # Menu
        menubar = tk.Menu(self); self.config(menu=menubar)

        mview = tk.Menu(menubar, tearoff=0)
        mview.add_checkbutton(label="Dark mode", onvalue=True, offvalue=False,
                              variable=self.dark_mode, command=self._toggle_dark)
        mview.add_checkbutton(label="Follow system theme", onvalue=True, offvalue=False,
                              variable=self.follow_system, command=self._toggle_follow_system)
        menubar.add_cascade(label="View", menu=mview)

        mpro = tk.Menu(menubar, tearoff=0)
        mpro.add_command(label="Enter license…", command=self._prompt_license)
        mpro.add_command(label="Buy Pro – $5", command=lambda: self._open_url(self._buy_url()))
        mpro.add_command(label="Download Pro installer",
                         command=lambda: self._open_url(self.pro_download_url or f"{DOMAIN}/static/GlassSetup.exe"))
        menubar.add_cascade(label="Pro", menu=mpro)

        mhelp = tk.Menu(menubar, tearoff=0)
        mhelp.add_command(label="Keyboard shortcuts…", command=self._show_shortcuts)
        mhelp.add_command(label="Glass Website", command=lambda: self._open_url(DOMAIN))
        menubar.add_cascade(label="Help", menu=mhelp)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        atexit.register(self._persist)

    # -------------------------- Hotkeys ----------------------------------
    def _bind_hotkeys(self):
        self.bind_all("<Control-Return>",   lambda e: self._apply_selected())
        self.bind_all("<Control-KP_Enter>", lambda e: self._apply_selected())
        self.bind_all("<Control-Key-0>",    lambda e: self._reset_selected())

        self.bind_all("<Control-Key-l>", lambda e: self._lock_selected())
        self.bind_all("<Control-Key-p>", lambda e: self._toggle_on_top())
        self.bind_all("<Control-Key-g>", lambda e: self._toggle_ghost())

        self.bind_all("<Control-Up>",   lambda e: self._nudge_opacity(+5))
        self.bind_all("<Control-Down>", lambda e: self._nudge_opacity(-5))

    def _toggle_on_top(self):
        if not self.is_pro: self._toast("Pin on top requires Pro."); return
        self.var_on_top.set(not self.var_on_top.get()); self._maybe_live()

    def _toggle_ghost(self):
        if not self.is_pro: self._toast("Ghost requires Pro."); return
        self.var_ghost.set(not self.var_ghost.get()); self._maybe_live()

    # ----------------------- actions / helpers ---------------------------
    def _maybe_live(self):
        if self.var_live.get(): self._apply_selected(live=True)

    def _apply_preset(self):
        try: v = int(self.var_preset.get())
        except Exception: v = 75
        v = max(20, min(100, v))
        self.var_opacity.set(v); self.scale.set(v); self.lbl_pct.config(text=f"{v}%")
        self._apply_selected()

    def _lock_selected(self):
        if not self.is_pro: self._toast("Lock is a Pro feature."); return
        title, hwnd = self._current_title_and_hwnd()
        if not hwnd: self._toast("Pick a window."); return
        ok = apply_opacity(hwnd, int(self.var_opacity.get()), topmost=True, ghost=True)
        if ok:
            self.var_on_top.set(True); self.var_ghost.set(True)
            self._remember_current(); self._toast("Locked (on-top + ghost).")
            self.badge.config(text=self._badge_text())
        else: self._toast("Failed to lock.")

    def _apply_selected(self, live: bool=False):
        title, hwnd = self._current_title_and_hwnd()
        if not hwnd:
            if not live: self._toast("Pick a window.")
            return

        # local cap enforcement
        cap = int(self.max_concurrent or CAPS.get(self.tier, 1))
        already = self.per_window.get(title) or {}
        is_active = (int(already.get("opacity", 100)) < 100) or already.get("on_top") or already.get("ghost")
        if not is_active:
            if self._active_count() >= cap:
                if not live: self._toast(f"Limit reached ({self._active_count()}/{cap}).")
                return

        topmost = self.var_on_top.get() if self.is_pro else None
        ghost   = self.var_ghost.get()  if self.is_pro else None
        ok = apply_opacity(hwnd, int(self.var_opacity.get()), topmost=topmost, ghost=ghost)
        if ok:
            self._remember_current()
            if not live: self._toast("Applied.")
            self.badge.config(text=self._badge_text())
        else:
            if not live: self._toast("Failed to apply.")

    def _reset_selected(self):
        title, hwnd = self._current_title_and_hwnd()
        if not hwnd: self._toast("Pick a window."); return
        revert_window(hwnd)
        self.var_on_top.set(False); self.var_ghost.set(False)
        self.var_opacity.set(100); self.scale.set(100); self.lbl_pct.config(text="100%")
        self.per_window.pop(title, None)
        self._toast("Reset to 100%.")
        self.badge.config(text=self._badge_text())

    def _on_slider(self):
        v = int(float(self.scale.get()))
        self.var_opacity.set(v); self.lbl_pct.config(text=f"{v}%")
        if self.var_live.get() and not self._live_pending:
            self._live_pending = True
            self.after(LIVE_DEBOUNCE_MS, self._live_tick)

    def _live_tick(self):
        self._live_pending = False
        self._apply_selected(live=True)

    def _nudge_opacity(self, delta: int):
        v = int(self.var_opacity.get())
        v = max(20, min(100, v + delta))
        self.var_opacity.set(v); self.scale.set(v); self.lbl_pct.config(text=f"{v}%")
        if self.var_live.get(): self._apply_selected(live=True)

    def _debounce_filter(self):
        if self._filter_job: self.after_cancel(self._filter_job)
        self._filter_job = self.after(LIST_FILTER_MS, self._update_list)

    def _update_list(self):
        filt = (self.var_filter.get() or "").lower().strip()
        items = [t for (t, _h) in self.window_cache if not filt or filt in t.lower()]
        self.listbox.delete(0, "end")
        for t in items: self.listbox.insert("end", t)
        self._filter_job = None

    def _refresh_windows(self, user: bool=False):
        if SKIP_REFRESH_DURING_LIVE and self.var_live.get() and self._live_pending:
            self.after(800, lambda: self._refresh_windows(user=user)); return
        show_all = self.var_show_all.get()
        self.window_cache = enum_app_windows(show_all=show_all)
        self.hwnd_by_title = {t:h for (t,h) in self.window_cache}
        self._update_list()
        if user: self._toast("Window list refreshed.")
        self.badge.config(text=self._badge_text())

    def _on_select(self):
        title, hwnd = self._current_title_and_hwnd()
        if not title: self.lbl_sel.config(text="(no window selected)"); return
        self.lbl_sel.config(text=title)
        st = self.per_window.get(title) or {}
        op = int(st.get("opacity", 85))
        self.var_opacity.set(op); self.scale.set(op); self.lbl_pct.config(text=f"{op}%")
        self.var_on_top.set(bool(st.get("on_top", False)))
        self.var_ghost.set(bool(st.get("ghost", False)))

    def _current_title_and_hwnd(self) -> Tuple[str, int]:
        try:
            idx = self.listbox.curselection()
            if not idx: return ("", 0)
            title = self.listbox.get(idx[0])
            return (title, int(self.hwnd_by_title.get(title) or 0))
        except Exception:
            return ("", 0)

    def _remember_current(self):
        title, _ = self._current_title_and_hwnd()
        if not title: return
        self.per_window[title] = {
            "opacity": int(self.var_opacity.get()),
            "on_top": bool(self.var_on_top.get()),
            "ghost": bool(self.var_ghost.get()),
        }

    # ------------------------ Persistence / status ------------------------
    def _persist(self):
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "per_window": self.per_window,
                "tier": self.tier,
                "max_concurrent": self.max_concurrent,
                "pro_download_url": self.pro_download_url,
                "dark_mode": bool(self.dark_mode.get()),
                "follow_system": bool(self.follow_system.get()),
            }
            SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception: pass

    def _load_last_state(self):
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            self.per_window = dict(data.get("per_window") or {})
            self.tier = data.get("tier") or "free"
            self.is_pro = (self.tier.lower() == "pro")
            self.max_concurrent = int(data.get("max_concurrent") or CAPS.get(self.tier, 1))
            self.pro_download_url = data.get("pro_download_url") or ""
            self.dark_mode.set(bool(data.get("dark_mode", False)))
            self.follow_system.set(bool(data.get("follow_system", False)))
            self.badge.config(text=self._badge_text())
        except Exception: pass

    def _toggle_follow(self):
        if self.follow_enabled.get(): self._follow_tick()
        else:
            if self._follow_job: self.after_cancel(self._follow_job); self._follow_job=None

    def _follow_tick(self):
        try:
            self._refresh_windows(user=False)
            if self.window_cache:
                fg_title = self.window_cache[0][0]
                all_titles = [self.listbox.get(i) for i in range(self.listbox.size())]
                if fg_title in all_titles:
                    idx = all_titles.index(fg_title)
                    self.listbox.selection_clear(0, "end")
                    self.listbox.selection_set(idx)
                    self.listbox.see(idx)
                    self._on_select()
        except Exception: pass
        finally:
            if self.follow_enabled.get():
                self._follow_job = self.after(FOLLOW_POLL_MS, self._follow_tick)

    def _schedule_periodic(self):
        if self._auto_job:
            try: self.after_cancel(self._auto_job)
            except Exception: pass
        self._auto_job = self.after(AUTO_REFRESH_MS, self._auto_tick)

    def _auto_tick(self):
        self._refresh_windows()
        if (time.time() - self._last_validate) > (VALIDATE_EVERY_HRS * 3600):
            self._validate_token_silent()
        self._schedule_periodic()

    def _validate_token_silent(self, startup: bool=False):
        r = license_validate()
        if r.get("ok"):
            self.tier = r.get("tier", "free").lower()
            self.is_pro = (self.tier == "pro")
            cap = r.get("max_windows") or r.get("cap")
            self.max_concurrent = int(cap) if isinstance(cap, int) and cap > 0 else CAPS.get(self.tier, CAPS["free"])
            self.pro_download_url = r.get("download_url") or self.pro_download_url
            self.badge.config(text=self._badge_text())
            if startup and self.is_pro: self._toast("Pro activated.")
        else:
            self.tier = "free"; self.is_pro = False
            self.badge.config(text=self._badge_text())
        self._last_validate = time.time()

    def _badge_text(self) -> str:
        return self._status_persistent().split(" • ", 1)[0]

    def _status_persistent(self) -> str:
        active = self._active_count(); cap = int(self.max_concurrent or CAPS.get(self.tier, 1))
        host = DOMAIN.replace("https://","").replace("http://","")
        return f"{self.tier.title()} ({active}/{cap}) • Connected: {host} • v{APP_VERSION}"

    def _build_status_bar(self):
        self._status_default = tk.StringVar(value=self._status_persistent())
        self.status.config(textvariable=self._status_default)
        self.after(1000, self._status_tick)

    def _status_tick(self):
        self._status_default.set(self._status_persistent())
        self.after(1000, self._status_tick)

    def _active_count(self) -> int:
        n = 0
        try:
            for st in (self.per_window or {}).values():
                if int(st.get("opacity", 100)) < 100 or st.get("on_top") or st.get("ghost"):
                    n += 1
        except Exception: pass
        return n

    # ------------------------- Theme toggles --------------------------------
    def _toggle_dark(self):
        if not self.follow_system.get():
            self._apply_theme(self.dark_mode.get())
        else:
            self._apply_theme_from_prefs()

    def _toggle_follow_system(self):
        self._apply_theme_from_prefs()
        self._start_theme_watcher()

    # ---------------------- Misc UI helpers ---------------------------------
    def _open_url(self, url: str):
        try: webbrowser.open_new_tab(url)
        except Exception: pass

    def _buy_url(self) -> str:
        return PRO_BUY_URL or f"{DOMAIN}/buy?tier=pro"

    def _toast(self, text: str):
        self.status.config(text=text)
        if self._toast_job:
            try: self.after_cancel(self._toast_job)
            except Exception: pass
        self._toast_job = self.after(2200, lambda: self.status.config(text=self._status_default.get()))

    def _revert_all(self):
        try:
            for _t, h in self.window_cache:
                if h: revert_window(h)
            for t in list(self.per_window.keys()):
                if t in self.hwnd_by_title: self.per_window.pop(t, None)
            self._toast("Reverted all (current session).")
            self.badge.config(text=self._badge_text())
        except Exception:
            self._toast("Could not revert some windows.")

    def _on_close(self): self._persist(); self.destroy()

    def _prompt_license(self):
        win = tk.Toplevel(self); win.title("Enter license key"); win.resizable(False, False)
        ttk.Label(win, text="Paste your license key:").pack(anchor="w", padx=12, pady=(12,6))
        var = tk.StringVar(); ent = ttk.Entry(win, width=44, textvariable=var); ent.pack(padx=12, fill="x"); ent.focus_set()
        msg = ttk.Label(win, text="", style="Muted.TLabel"); msg.pack(anchor="w", padx=12, pady=6)
        btns = ttk.Frame(win); btns.pack(fill="x", padx=12, pady=(0,12))
        def on_ok():
            key = (var.get() or "").strip()
            if not key: msg.config(text="Enter a key."); return
            r = license_activate(key)
            if r.get("ok"):
                self.tier = r.get("tier","pro").lower(); self.is_pro = (self.tier=="pro")
                cap = r.get("max_windows") or r.get("cap")
                self.max_concurrent = int(cap) if isinstance(cap,int) and cap>0 else CAPS.get(self.tier, CAPS["free"])
                self.pro_download_url = r.get("download_url") or self.pro_download_url
                self.badge.config(text=self._badge_text()); self._toast("Pro activated. Thanks!"); win.destroy()
            else:
                msg.config(text=f"Activation failed: {r.get('reason','try again')}")
        ttk.Button(btns, text="Activate", command=on_ok).pack(side="left")
        ttk.Button(btns, text="Buy Pro – $5", command=lambda: self._open_url(self._buy_url())).pack(side="right")

    def _show_shortcuts(self):
        txt = (
            "Apply: Ctrl+Enter\n"
            "Reset to 100%: Ctrl+0\n"
            "Opacity up/down: Ctrl+↑ / Ctrl+↓\n"
            "Pin on top (Pro): Ctrl+P\n"
            "Ghost click-through (Pro): Ctrl+G\n"
            "Lock (on-top+ghost) (Pro): Ctrl+L\n"
            "Refresh list: F5\n"
        )
        messagebox.showinfo("Keyboard shortcuts", txt)

# ------------------------------ Entrypoint -----------------------------------
def main():
    app = GlassApp()
    app.mainloop()

if __name__ == "__main__":
    main()
