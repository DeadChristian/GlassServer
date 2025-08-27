# globe_widget.py — Minimal solid-color wireframe globe (Tk 8.6 / Py3.9+)
from __future__ import annotations
import math, time
from typing import Optional, Tuple, List
import tkinter as tk

def _deg2rad(d: float) -> float: return d * math.pi / 180.0

class GlobeWidget:
    """
    Minimal, theme-controlled wireframe globe:
      • Solid color (from theme accent) for all lines
      • Orthographic projection with tilt + spin
      • Rim + evenly spaced meridians/parallels
    """
    def __init__(
        self,
        parent,
        size: int = 64,
        speed: float = 1.0,
        accent_color: str = "#22e38a",
        assets_dir=None,          # kept for API compatibility
        tilt_deg: float = 23.0,
        fps: int = 30,
        meridian_step: int = 15,  # degrees between meridians
        parallel_step: int = 15,  # degrees between parallels
        line_width: int = 1,
        **_ignore,                # swallow any extra kwargs (enable_land, dust, etc.)
    ):
        self.parent = parent
        self.size = max(48, int(size))
        self.speed = float(speed)
        self.color = str(accent_color)
        self.tilt = _deg2rad(float(tilt_deg))
        self.fps  = max(12, min(60, int(fps)))
        self.line_width = max(1, int(line_width))

        bg = getattr(parent, "cget", lambda _:"white")("bg")
        self.widget = tk.Canvas(parent, width=self.size, height=self.size,
                                highlightthickness=0, bd=0, relief="flat", bg=bg)

        # geometry
        self.cx = self.size / 2.0
        self.cy = self.size / 2.0
        self.R  = self.size / 2.0 - 2.0

        # animation
        self._theta = 0.0
        self._last_ts = time.time()
        self._job: Optional[str] = None

        # grid
        self._meridians = list(range(-180, 180, int(meridian_step)))
        self._parallels = [p for p in range(-90 + parallel_step, 90, int(parallel_step))]  # skip poles

    # ---- public API ----------------------------------------------------------
    def start(self):
        if self._job is None:
            self._last_ts = time.time()
            self._tick()

    def stop(self):
        if self._job:
            try: self.widget.after_cancel(self._job)
            except Exception: pass
            self._job = None

    def set_accent(self, color: str):
        """Update solid color on the fly (theme change)."""
        self.color = str(color)

    # ---- math / projection ---------------------------------------------------
    def _project_point(self, lat_deg: float, lon_deg: float, theta: float) -> Optional[Tuple[float, float]]:
        φ = _deg2rad(lat_deg)
        λ = _deg2rad(lon_deg) - theta
        # unit sphere (before tilt)
        x = math.cos(φ) * math.cos(λ)
        y = math.sin(φ)
        z = math.cos(φ) * math.sin(λ)
        # axial tilt around X
        ca, sa = math.cos(self.tilt), math.sin(self.tilt)
        y2 = y * ca - z * sa
        z2 = y * sa + z * ca
        if z2 <= 0.0:
            return None  # back side (not visible in orthographic)
        return (self.cx + x * self.R, self.cy - y2 * self.R)

    # ---- drawing -------------------------------------------------------------
    def _draw_rim(self):
        self.widget.create_oval(self.cx - self.R, self.cy - self.R,
                                self.cx + self.R, self.cy + self.R,
                                outline=self.color, width=self.line_width)

    def _draw_graticule(self, theta: float):
        lw = self.line_width
        # meridians
        for lon in self._meridians:
            pts: List[Tuple[float, float]] = []
            for lat in range(-85, 86, 4):
                p = self._project_point(lat, lon, theta)
                if p: pts.append(p)
            if len(pts) >= 2:
                self.widget.create_line(pts, fill=self.color, width=lw, smooth=True)
        # parallels
        for lat in self._parallels:
            pts: List[Tuple[float, float]] = []
            for lon in range(-180, 181, 6):
                p = self._project_point(lat, lon, theta)
                if p: pts.append(p)
            if len(pts) >= 2:
                self.widget.create_line(pts, fill=self.color, width=lw, smooth=True)
        # equator slightly thicker to read as a “belt”
        pts: List[Tuple[float, float]] = []
        for lon in range(-180, 181, 4):
            p = self._project_point(0, lon, theta)
            if p: pts.append(p)
        if len(pts) >= 2:
            self.widget.create_line(pts, fill=self.color, width=lw+0, smooth=True)

    # ---- animation -----------------------------------------------------------
    def _tick(self):
        now = time.time()
        dt = now - self._last_ts
        self._last_ts = now
        self._theta += 0.9 * dt * self.speed  # radians per second scaled

        self.widget.delete("all")
        self._draw_rim()
        self._draw_graticule(self._theta)

        delay = int(1000 / self.fps)
        self._job = self.widget.after(delay, self._tick)

# ---- public constructor (keeps your existing imports) ------------------------
def create_globe(parent, **kwargs) -> GlobeWidget:
    """
    Usage:
        globe = create_globe(frame, size=56, speed=1.0, accent_color="#22e38a", tilt_deg=23.0)
        globe.widget.grid(...)
        globe.start()
    """
    return GlobeWidget(
        parent,
        size=kwargs.get("size", 56),
        speed=kwargs.get("speed", 1.0),
        accent_color=kwargs.get("accent_color", "#22e38a"),
        assets_dir=kwargs.get("assets_dir", None),
        tilt_deg=kwargs.get("tilt_deg", 23.0),
        fps=kwargs.get("fps", 30),
        meridian_step=kwargs.get("meridian_step", 15),
        parallel_step=kwargs.get("parallel_step", 15),
        line_width=kwargs.get("line_width", 1),
        **{k: v for k, v in kwargs.items() if k not in {
            "size","speed","accent_color","assets_dir","tilt_deg","fps",
            "meridian_step","parallel_step","line_width"
        }}
    )
