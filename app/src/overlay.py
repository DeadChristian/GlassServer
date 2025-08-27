# overlay.py — fullscreen translucent overlay with click-through + topmost lock (Win-friendly)
from __future__ import annotations
import sys
import tkinter as tk
from typing import Optional

# ---- Windows constants (no-ops elsewhere) -----------------------------------
try:
    import ctypes
    GWL_EXSTYLE       = -20
    WS_EX_LAYERED     = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    LWA_ALPHA         = 0x2

    HWND_TOPMOST   = -1
    SWP_NOSIZE     = 0x0001
    SWP_NOMOVE     = 0x0002
    SWP_NOACTIVATE = 0x0010

    SM_XVIRTUALSCREEN  = 76
    SM_YVIRTUALSCREEN  = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    _HAVE_WIN = sys.platform.startswith("win")
except Exception:  # pragma: no cover
    ctypes = None  # type: ignore
    _HAVE_WIN = False


class TraceOverlay:
    """
    A borderless, always-on-top Toplevel stretched to the screen (or monitor).
      • Optional click-through on Windows (UI underneath remains interactive)
      • Topmost *lock* that periodically reasserts 'always on top'
      • Debounced resizing for smoothness on DPI/monitor changes
      • Live setters for alpha, color, bounds
      • Optional multi-monitor coverage

    monitor:
      - "primary" (default) -> uses Tk's primary screen metrics
      - "virtual"           -> (Windows) entire virtual desktop (all monitors)
    """
    def __init__(
        self,
        master: tk.Misc,
        *,
        alpha: float = 0.30,
        color: str = "#000000",
        click_through: bool = True,
        monitor: str = "primary",
        topmost_lock: bool = True,
        lock_interval_ms: int = 1500,
    ):
        self.master = master
        self.visible = False

        self._alpha = float(max(0.0, min(1.0, alpha)))
        self._color = str(color)
        self._click_through = bool(click_through)
        self._monitor_mode = "virtual" if (monitor == "virtual" and _HAVE_WIN) else "primary"

        # Topmost lock
        self._topmost_lock = bool(topmost_lock)
        self._lock_interval_ms = max(500, int(lock_interval_ms))
        self._lock_job: Optional[str] = None

        # Debounce id for refits
        self._refit_job: Optional[str] = None

        # Create overlay window
        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", self._alpha)
        self.win.configure(bg=self._color)

        # First fit
        self._fit_to_target()

        # Refit hooks
        self.win.bind("<Map>",        lambda _e: self._fit_to_target())
        self.win.bind("<Configure>",  lambda _e: self._schedule_refit())
        self.master.bind("<Configure>", lambda _e: self._schedule_refit())

        # Convenience: ESC hides overlay
        self.win.bind("<Escape>", lambda _e: self.hide())

    # ---- public controls -----------------------------------------------------
    @property
    def click_through(self) -> bool:
        return self._click_through

    def set_click_through(self, enabled: bool) -> None:
        self._click_through = bool(enabled)
        if self.visible:
            self._apply_click_through()

    def toggle_click_through(self) -> None:
        self.set_click_through(not self._click_through)

    @property
    def topmost_lock(self) -> bool:
        return self._topmost_lock

    def set_topmost_lock(self, enabled: bool) -> None:
        self._topmost_lock = bool(enabled)
        self._ensure_topmost_loop(enabled)

    def set_alpha(self, alpha: float) -> None:
        self._alpha = float(max(0.0, min(1.0, alpha)))
        try:
            self.win.attributes("-alpha", self._alpha)
        except Exception:
            pass
        if self.visible:
            self._apply_click_through()  # refresh layered alpha on Windows

    def set_color(self, color: str) -> None:
        self._color = str(color)
        try:
            self.win.configure(bg=self._color)
        except Exception:
            pass

    def set_bounds(self, x: int, y: int, w: int, h: int) -> None:
        """Constrain overlay to a rectangle instead of the full screen."""
        w = max(1, int(w))
        h = max(1, int(h))
        self.win.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        self._last_geom = (int(x), int(y), w, h)

    def use_virtual_desktop(self, on: bool = True) -> None:
        """Switch between primary screen and (Windows) virtual desktop."""
        self._monitor_mode = "virtual" if (on and _HAVE_WIN) else "primary"
        if self.visible:
            self._fit_to_target()
            self._apply_click_through()

    def fit_to_screen(self) -> None:
        """Force-fit to the current target area."""
        self._fit_to_target()

    # ---- visibility ----------------------------------------------------------
    def show(self) -> None:
        self._fit_to_target()
        self.win.deiconify()
        self.visible = True
        self._apply_click_through()
        self._ensure_topmost_loop(True)

    def hide(self) -> None:
        self._ensure_topmost_loop(False)
        self.win.withdraw()
        self.visible = False

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()

    def destroy(self) -> None:
        self._ensure_topmost_loop(False)
        if self._refit_job:
            try: self.win.after_cancel(self._refit_job)
            except Exception: pass
            self._refit_job = None
        try:
            self.win.destroy()
        except Exception:
            pass

    # ---- internals -----------------------------------------------------------
    def _schedule_refit(self, delay_ms: int = 120) -> None:
        """Debounce geometry refits for smoother behavior."""
        if self._refit_job:
            try: self.win.after_cancel(self._refit_job)
            except Exception: pass
        self._refit_job = self.win.after(max(16, delay_ms), self._maybe_refit_now)

    def _maybe_refit_now(self) -> None:
        self._refit_job = None
        tgt = self._current_target_rect()
        if getattr(self, "_last_geom", None) != tgt:
            self._apply_geometry(*tgt)
            if self.visible:
                self._apply_click_through()

    def _fit_to_target(self) -> None:
        self._apply_geometry(*self._current_target_rect())

    def _apply_geometry(self, x: int, y: int, w: int, h: int) -> None:
        self._last_geom = (x, y, w, h)
        self.win.geometry(f"{max(1,w)}x{max(1,h)}+{x}+{y}")

    def _current_target_rect(self) -> tuple[int, int, int, int]:
        if self._monitor_mode == "virtual" and _HAVE_WIN:
            try:
                user32 = ctypes.windll.user32  # type: ignore
                x = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
                y = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
                w = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
                h = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
                # Tk geometry supports negative origins on Windows; keep as-is.
                return (x, y, max(1, w), max(1, h))
            except Exception:
                pass
        # Fallback: primary screen reported by Tk
        sw, sh = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        return (0, 0, int(sw), int(sh))

    def _apply_click_through(self) -> None:
        """Windows: make overlay mouse-click transparent while keeping visuals."""
        if not _HAVE_WIN:
            # Non-Windows Tk doesn't have reliable global click-through.
            return
        try:
            hwnd = self.win.winfo_id()
            user32 = ctypes.windll.user32  # type: ignore

            get_ex = user32.GetWindowLongW
            set_ex = user32.SetWindowLongW

            ex = int(get_ex(hwnd, GWL_EXSTYLE)) | WS_EX_LAYERED
            if self._click_through:
                ex |= WS_EX_TRANSPARENT
            else:
                ex &= ~WS_EX_TRANSPARENT
            set_ex(hwnd, GWL_EXSTYLE, ex)

            # Refresh the layered alpha so the OS uses the same opacity
            alpha_byte = int(self._alpha * 255)
            user32.SetLayeredWindowAttributes(hwnd, 0, alpha_byte, LWA_ALPHA)
        except Exception:
            # Keep overlay usable even if toggling fails
            pass

    def _ensure_topmost_loop(self, enable: bool) -> None:
        """Keep the window pinned above others (works around certain apps stealing Z order)."""
        if not enable:
            if self._lock_job:
                try: self.win.after_cancel(self._lock_job)
                except Exception: pass
                self._lock_job = None
            return

        def _bump_topmost():
            try:
                # Tk attribute first (portable)
                self.win.attributes("-topmost", True)
                if _HAVE_WIN:
                    # On Windows, be explicit
                    hwnd = self.win.winfo_id()
                    ctypes.windll.user32.SetWindowPos(  # type: ignore
                        hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                    )
            except Exception:
                pass
            # reschedule
            self._lock_job = self.win.after(self._lock_interval_ms, _bump_topmost)

        # (Re)start loop
        if self._lock_job:
            try: self.win.after_cancel(self._lock_job)
            except Exception: pass
        _bump_topmost()
