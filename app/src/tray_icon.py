# tray_icon.py — system tray with Overlay Lock toggle (Py 3.9+)
from __future__ import annotations
import os, threading
from typing import Optional

# Optional deps
try:
    import pystray
    from PIL import Image, ImageDraw
    HAVE_TRAY = True
except Exception:
    HAVE_TRAY = False
    pystray = None  # type: ignore
    Image = None    # type: ignore
    ImageDraw = None  # type: ignore

# Optional resource resolver
try:
    from paths import resource_path
except Exception:
    def resource_path(rel: str) -> str:
        base = getattr(__import__("sys"), "_MEIPASS", os.path.dirname(__file__))
        return os.path.join(base, rel)


class GlassTray:
    """Tray icon wrapper that safely talks to the Tk thread via app.after()."""
    def __init__(self, app):
        self.app = app
        self.icon: Optional[pystray.Icon] = None  # type: ignore
        self._thread: Optional[threading.Thread] = None

    # ---------- public API ----------
    def start(self):
        if not HAVE_TRAY or self.icon:
            return
        self._thread = threading.Thread(target=self._run_icon, name="GlassTray", daemon=True)
        self._thread.start()

    def stop(self):
        try:
            if self.icon:
                self.icon.stop()
                self.icon = None
        except Exception:
            pass

    def refresh(self):
        """Ask pystray to re-read the menu 'checked' state."""
        try:
            if self.icon:
                self.icon.update_menu()
        except Exception:
            pass

    # ---------- internals ----------
    def _run_icon(self):
        try:
            image = self._build_image()
            self.icon = pystray.Icon(
                "Glass",
                image,
                "Glass",
                self._build_menu()
            )
            self.icon.run()
        except Exception:
            self.icon = None

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                "Overlay Lock",
                self._on_toggle_overlay,
                checked=lambda item: bool(getattr(self.app, "overlay_on", False)),
                default=True,
            ),
            pystray.MenuItem(
                "Open Glass",
                self._on_open_app
            ),
            pystray.MenuItem.separator(),
            pystray.MenuItem(
                "Quit",
                self._on_quit
            ),
        )

    def _on_toggle_overlay(self, _=None):
        # hop to Tk thread
        try:
            self.app.after(0, self._toggle_in_tk)
        except Exception:
            pass

    def _toggle_in_tk(self):
        try:
            self.app.var_overlay_lock.set(not self.app.var_overlay_lock.get())
            self.app._on_overlay_toggle()
            self.refresh()
        except Exception:
            pass

    def _on_open_app(self, _=None):
        try:
            self.app.after(0, self._open_in_tk)
        except Exception:
            pass

    def _open_in_tk(self):
        try:
            self.app.deiconify()
            self.app.lift()
            self.app.focus_force()
        except Exception:
            pass

    def _on_quit(self, _=None):
        try:
            self.app.after(0, self.app._on_close)
        except Exception:
            pass

    def _build_image(self):
        # Try assets/icon.ico first; otherwise draw a simple green dot badge
        try:
            ico_path = resource_path("assets/icon.ico")
            if os.path.exists(ico_path) and Image:
                # pystray accepts a PIL.Image
                return Image.open(ico_path)
        except Exception:
            pass

        # Fallback: draw 64x64 white circle w/ green ring
        size = 64
        img = Image.new("RGBA", (size, size), (255, 255, 255, 0)) if Image else None
        if not img:
            return None
        draw = ImageDraw.Draw(img)
        draw.ellipse((6, 6, size-6, size-6), outline=(34, 227, 138, 255), width=5)  # #22e38a
        draw.ellipse((16, 16, size-16, size-16), fill=(34, 227, 138, 220))
        return img
