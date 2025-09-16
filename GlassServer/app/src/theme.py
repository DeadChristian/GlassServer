# theme.py — modular ttk theme tokens + cached JSON loader + richer widget styles
from __future__ import annotations
import json, os
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Dict, List

# ---------------- built-ins ---------------------------------------------------
_BUILTINS: Dict[str, Dict[str, str]] = {
    # Light: white UI with black text everywhere
    "Light": {
        "bg": "#FFFFFF", "fg": "#000000", "fg_subtle": "#000000", "accent": "#22e38a",
        "muted": "#F4F6FA", "border": "#D9DEE6", "badge_bg": "#EEF5F0", "badge_fg": "#22e38a",
        "warn": "#b45309", "err": "#b91c1c",
    },
    # Original darks
    "Mint Recall": {
        "bg": "#0b0f10", "fg": "#d1d5db", "fg_subtle": "#9ca3af", "accent": "#22e38a",
        "muted": "#0f1417", "border": "#14181b", "badge_bg": "#0f1512", "badge_fg": "#22e38a",
        "warn": "#f59e0b", "err": "#ef4444",
    },
    "Neon": {
        "bg": "#0a0a0f", "fg": "#e5e7eb", "fg_subtle": "#94a3b8", "accent": "#00e5ff",
        "muted": "#0e0e15", "border": "#141426", "badge_bg": "#0d1216", "badge_fg": "#00e5ff",
        "warn": "#f59e0b", "err": "#ef4444",
    },
    "Matrix": {
        "bg": "#070b08", "fg": "#c7f9cc", "fg_subtle": "#86efac", "accent": "#00ff7f",
        "muted": "#09110b", "border": "#0f1a12", "badge_bg": "#0a130d", "badge_fg": "#00ff7f",
        "warn": "#f59e0b", "err": "#ef4444",
    },
    "Slate": {
        "bg": "#0b1020", "fg": "#dbeafe", "fg_subtle": "#93c5fd", "accent": "#60a5fa",
        "muted": "#0f1426", "border": "#1b2238", "badge_bg": "#0d1326", "badge_fg": "#60a5fa",
        "warn": "#f59e0b", "err": "#ef4444",
    },
}

_THEME_DEFS: Dict[str, Dict[str, str]] = dict(_BUILTINS)
_LOADED_EXTERNAL = False  # one-shot cache for disk themes

# ---------------- helpers -----------------------------------------------------
def _themes_dir(base: Path) -> Path:
    p = base / "assets" / "themes"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p

def _merge_tokens(base: Dict[str, str], over: Dict[str, str]) -> Dict[str, str]:
    merged = dict(base)
    merged.update(over or {})
    # ensure required keys always exist
    for k, v in {
        "bg": "#0b0f10",
        "fg": "#d1d5db",
        "fg_subtle": "#9ca3af",
        "accent": "#22e38a",
        "muted": "#0f1417",
        "border": "#14181b",
        "badge_bg": "#0f1512",
        "badge_fg": "#22e38a",
        "warn": "#f59e0b",
        "err": "#ef4444",
    }.items():
        merged.setdefault(k, v)
    return merged

def _load_external_jsons() -> None:
    global _LOADED_EXTERNAL
    if _LOADED_EXTERNAL:
        return
    _LOADED_EXTERNAL = True
    try:
        base = Path(os.path.dirname(__file__) or ".").resolve()
        folder = _themes_dir(base)
        for p in folder.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                name = (data.get("name") or p.stem).strip() or p.stem
                _THEME_DEFS[name] = _merge_tokens(_THEME_DEFS.get("Mint Recall", {}), data)
            except Exception:
                # ignore malformed files; keep app running
                pass
    except Exception:
        pass

# ---------------- public API --------------------------------------------------
def available_themes() -> List[str]:
    _load_external_jsons()
    return sorted(_THEME_DEFS.keys())

def register_theme(name: str, tokens: dict) -> None:
    """Register or overwrite a theme at runtime (merged over Mint Recall)."""
    _load_external_jsons()
    _THEME_DEFS[name] = _merge_tokens(_THEME_DEFS.get("Mint Recall", {}), dict(tokens or {}))

def get_theme_tokens(name: str) -> dict:
    _load_external_jsons()
    return dict(_THEME_DEFS.get(name) or _THEME_DEFS["Mint Recall"])

def set_theme(root: tk.Misc, name: str, *, force_black_text: bool = False) -> dict:
    """
    Apply a theme by name to the given root and return the tokens used.
    Emits the virtual event '<<ThemeChanged>>' on the root.

    If force_black_text=True (or env GLASS_FORCE_BLACK_TEXT=1), all label/control
    foregrounds become pure black (#000000). Accent colors are preserved.
    """
    _load_external_jsons()
    cfg = get_theme_tokens(name)

    # Env override for global behavior without touching callers
    env_force = (os.getenv("GLASS_FORCE_BLACK_TEXT", "").strip() in {"1", "true", "TRUE"})
    force_black_text = bool(force_black_text or env_force)

    bg    = cfg["bg"]
    fg    = "#000000" if force_black_text else cfg["fg"]
    fg2   = "#000000" if force_black_text else cfg["fg_subtle"]
    acc   = cfg["accent"]
    muted = cfg["muted"]
    border = cfg["border"]
    badge_bg = cfg["badge_bg"]
    badge_fg = cfg["badge_fg"]

    style = ttk.Style(root)
    try:
        style.theme_use("clam")  # modern, consistent ttk base
    except Exception:
        pass

    # Root background
    try:
        root.configure(bg=bg)
    except Exception:
        pass

    # --------- core labels / frames
    style.configure(".", background=bg, foreground=fg, borderwidth=0, relief="flat")
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("Subtle.TLabel", background=bg, foreground=fg2)
    style.configure("Header.TLabel", background=bg, foreground=fg, font=("Segoe UI", 14, "bold"))
    style.configure("Badge.TLabel", background=badge_bg, foreground=badge_fg, font=("Segoe UI", 10, "bold"))
    style.configure("Status.TLabel", background=bg, foreground=fg2)

    style.configure("TFrame", background=bg)
    style.configure("TLabelframe", background=bg, foreground=fg2)
    style.configure("TLabelframe.Label", background=bg, foreground=fg2)

    # --------- buttons
    style.configure("TButton", background=bg, foreground=fg, padding=(10, 6), relief="flat")
    style.map("TButton",
              background=[("active", bg), ("pressed", bg)],
              relief=[("pressed", "flat"), ("!pressed", "flat")],
              foreground=[("disabled", fg2)])

    # Accent button keeps accent color even when text is forced black
    style.configure("Accent.TButton", background=bg, foreground=acc, padding=(10, 6), relief="flat")
    style.map("Accent.TButton",
              foreground=[("!disabled", acc), ("disabled", fg2)],
              background=[("active", bg), ("pressed", bg)])

    # --------- inputs / selects / sliders
    style.configure("TEntry", fieldbackground=muted, foreground=fg, insertcolor=fg)
    style.configure("TCombobox", fieldbackground=muted, foreground=fg)
    style.map("TCombobox", fieldbackground=[("readonly", muted)], foreground=[("disabled", fg2)])
    style.configure("Horizontal.TScale", background=bg, troughcolor=border)

    # --------- complex widgets
    style.configure("Treeview", background=muted, fieldbackground=muted, foreground=fg, bordercolor=border)
    style.map("Treeview",
              background=[("selected", border)],
              foreground=[("selected", fg)])
    style.configure("Treeview.Heading", background=bg, foreground=fg2)

    style.configure("TNotebook", background=bg, borderwidth=0)
    style.configure("TNotebook.Tab", background=muted, foreground=fg2, padding=(10, 6))
    style.map("TNotebook.Tab",
              background=[("selected", border), ("active", muted)],
              foreground=[("selected", fg)])

    style.configure("TCheckbutton", background=bg, foreground=fg)
    style.configure("TRadiobutton", background=bg, foreground=fg)

    style.configure("Horizontal.TProgressbar", background=acc, troughcolor=muted)

    # Scrollbar theming varies by Tk build; best-effort only
    style.configure("TScrollbar", background=muted, troughcolor=bg)

    # Ensure child canvases match bg
    try:
        for child in root.winfo_children():
            if isinstance(child, tk.Canvas):
                child.configure(background=bg, highlightthickness=0)
    except Exception:
        pass

    # Notify listeners (e.g., globe widget updates)
    try:
        root.event_generate("<<ThemeChanged>>", when="tail")
    except Exception:
        pass

    # Return the actual tokens used (with forced blacks reflected in a copy)
    used = dict(cfg)
    if force_black_text:
        used["fg"] = "#000000"
        used["fg_subtle"] = "#000000"
    return used


