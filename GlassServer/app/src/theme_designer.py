# theme_designer.py — simpler Theme Designer (hex-validated, contrast-aware, no black-text toggles)
from __future__ import annotations
import json, os, re
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox, filedialog
from pathlib import Path
from typing import Callable, Dict, List

# Works with your theme module (no "force black text" needed anymore)
from theme import get_theme_tokens, register_theme, set_theme, available_themes

# --- configurable tokens shown in the editor ---------------------------------
TOKENS: List[tuple[str, str]] = [
    ("bg",        "Background"),
    ("fg",        "Text"),
    ("fg_subtle", "Subtle Text"),
    ("accent",    "Accent"),
    ("muted",     "Muted (controls)"),
    ("border",    "Border / Trough"),
    ("badge_bg",  "Badge BG"),
    ("badge_fg",  "Badge FG"),
    ("warn",      "Warn"),
    ("err",       "Error"),
]

# Small, friendly starting points the user can try from a dropdown
PRESETS: Dict[str, Dict[str, str]] = {
    "Light Clean": {
        "bg": "#ffffff", "fg": "#000000", "fg_subtle": "#1f2937", "accent": "#22e38a",
        "muted": "#f2f4f7", "border": "#d9dee6", "badge_bg": "#eff6ff", "badge_fg": "#0ea5e9",
        "warn": "#f59e0b", "err": "#ef4444",
    },
    "Dark Mint": {
        "bg": "#0b0f10", "fg": "#d1d5db", "fg_subtle": "#9ca3af", "accent": "#22e38a",
        "muted": "#0f1417", "border": "#14181b", "badge_bg": "#0f1512", "badge_fg": "#22e38a",
        "warn": "#f59e0b", "err": "#ef4444",
    },
}

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

def _themes_dir(base: Path) -> Path:
    p = base / "assets" / "themes"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p

def _norm_hex(s: str, fallback: str = "#000000") -> str:
    s = (s or "").strip()
    if not s.startswith("#"):
        s = "#" + s
    if _HEX_RE.fullmatch(s):
        if len(s) == 4:  # expand #abc → #aabbcc
            s = "#" + "".join(ch * 2 for ch in s[1:])
        return s.lower()
    return fallback

def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = _norm_hex(h, "#000000")
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore

def _rel_lum(rgb: tuple[float, float, float]) -> float:
    def f(c: float) -> float:
        return (c / 12.92) if c <= 0.03928 else (((c + 0.055) / 1.055) ** 2.4)
    r, g, b = (f(x) for x in rgb)
    return 0.2126*r + 0.7152*g + 0.0722*b

def _contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    L1 = _rel_lum(_hex_to_rgb(_norm_hex(fg_hex)))
    L2 = _rel_lum(_hex_to_rgb(_norm_hex(bg_hex)))
    lighter, darker = (max(L1, L2), min(L1, L2))
    return (lighter + 0.05) / (darker + 0.05)

# --- UI ----------------------------------------------------------------------
class ThemeDesigner(ttk.Frame):
    """
    Simple, friendly theme editor:
      • Validates hex values (#rrggbb or #rgb)
      • One-click color pickers
      • Live preview (header/body/button)
      • Contrast ratio readout (WCAG-ish)
      • Quick presets dropdown
    """
    def __init__(
        self,
        parent,
        current_theme: str,
        on_saved: Callable[[str, List[str]], None] | None = None,
        on_apply: Callable[[Dict], None] | None = None
    ):
        super().__init__(parent)
        self.on_saved = on_saved
        self.on_apply = on_apply
        self.current = current_theme

        # model
        self.vars: Dict[str, tk.StringVar] = {}
        self.name_var = tk.StringVar(value=f"{current_theme}")
        self.preset_var = tk.StringVar(value="Light Clean")

        tokens = get_theme_tokens(current_theme)

        # layout
        self.columnconfigure(0, weight=1)

        # Header row (Name + Preset)
        head = ttk.Frame(self)
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="Theme name:", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(head, textvariable=self.name_var, width=24).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(head, text="Preset:", style="Subtle.TLabel").grid(row=0, column=2, sticky="e", padx=(8, 0))
        preset_dd = ttk.Combobox(head, state="readonly", width=16, values=list(PRESETS.keys()), textvariable=self.preset_var)
        preset_dd.grid(row=0, column=3, sticky="e")
        ttk.Button(head, text="Apply Preset", command=self._apply_preset).grid(row=0, column=4, padx=(8, 0))

        # Grid of token editors
        grid = ttk.Frame(self)
        grid.grid(row=1, column=0, sticky="ew", padx=10)
        for i, (key, label) in enumerate(TOKENS):
            ttk.Label(grid, text=label + ":", style="Subtle.TLabel").grid(row=i, column=0, sticky="w", pady=3)
            sv = tk.StringVar(value=tokens.get(key, ""))
            self.vars[key] = sv

            entry = ttk.Entry(grid, textvariable=sv, width=14)
            entry.grid(row=i, column=1, sticky="w")
            entry.bind("<FocusOut>", lambda _e, k=key: self._sanitize(k))
            entry.bind("<Return>",  lambda _e, k=key: (self._sanitize(k), self._apply_live()))
            ttk.Button(grid, text="Pick", command=lambda k=key: self._pick(k)).grid(row=i, column=2, padx=(6,0), sticky="w")

        # Preview / contrast
        self.preview = ttk.Labelframe(self, text="Preview")
        self.preview.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        self.preview.columnconfigure(0, weight=1)
        ttk.Label(self.preview, text="Header", style="Header.TLabel").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        ttk.Label(self.preview, text="Body text", style="TLabel").grid(row=1, column=0, sticky="w", padx=8)
        ttk.Button(self.preview, text="Accent Button", style="Accent.TButton").grid(row=2, column=0, sticky="w", padx=8, pady=8)

        ctr = ttk.Frame(self.preview)
        ctr.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 8))
        ctr.columnconfigure(1, weight=1)
        ttk.Label(ctr, text="Contrast (fg/bg):", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")
        self.contrast_val = ttk.Label(ctr, text="—", style="TLabel")
        self.contrast_val.grid(row=0, column=1, sticky="w", padx=(6, 0))

        # Actions
        row = ttk.Frame(self)
        row.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        ttk.Button(row, text="Apply (Live)", command=self._apply_live).pack(side="left")
        ttk.Button(row, text="Save", command=self._save).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Load…", command=self._load_from_file).pack(side="left", padx=(8, 0))

        self._apply_live()  # initial preview

    # ---- helpers -------------------------------------------------------------
    def _sanitize(self, key: str):
        self.vars[key].set(_norm_hex(self.vars[key].get(), self.vars[key].get() or "#000000"))
        self._update_contrast_label()

    def _collect(self) -> Dict:
        d = {k: _norm_hex(self.vars[k].get()) for k, _ in TOKENS}
        d["name"] = (self.name_var.get().strip() or "Custom")
        return d

    def _update_contrast_label(self):
        fg = self.vars.get("fg", tk.StringVar(value="#000000")).get()
        bg = self.vars.get("bg", tk.StringVar(value="#ffffff")).get()
        ratio = _contrast_ratio(fg, bg)
        txt = f"{ratio:.2f} : 1"
        self.contrast_val.config(text=txt)
        try:
            ok = ratio >= 4.5
            self.contrast_val.configure(style="TLabel" if ok else "Badge.TLabel")
        except Exception:
            pass

    # ---- actions -------------------------------------------------------------
    def _pick(self, key: str):
        initial = _norm_hex(self.vars[key].get() or ("#ffffff" if key == "bg" else "#000000"))
        _rgb, hexv = colorchooser.askcolor(color=initial, title=f"Pick {key}")
        if hexv:
            self.vars[key].set(_norm_hex(hexv))
            self._apply_live()

    def _apply_preset(self):
        preset = PRESETS.get(self.preset_var.get(), {})
        if not preset:
            return
        for k, v in preset.items():
            if k in self.vars:
                self.vars[k].set(_norm_hex(v))
        # keep the current name but apply colors, then live-apply
        self._apply_live()

    def _apply_live(self):
        tokens = self._collect()
        try:
            register_theme(tokens["name"], tokens)
            root = self.winfo_toplevel()
            set_theme(root, tokens["name"])
            if self.on_apply:
                self.on_apply(tokens)
        except Exception:
            pass
        self._update_contrast_label()

    def _save(self):
        tokens = self._collect()
        try:
            base = Path(os.path.dirname(__file__) or ".").resolve()
            out = _themes_dir(base) / (tokens["name"].lower().replace(" ", "_") + ".json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(tokens, f, indent=2)
            if self.on_saved:
                self.on_saved(tokens["name"], available_themes())
            messagebox.showinfo("Saved", f"Saved theme to\n{out}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save theme:\n{e}")

    def _load_from_file(self):
        try:
            path = filedialog.askopenfilename(
                title="Load theme JSON",
                filetypes=[("JSON", "*.json")]
            )
            if not path:
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            for k, _ in TOKENS:
                if k in data:
                    self.vars[k].set(_norm_hex(str(data[k])))
            name = (data.get("name") or Path(path).stem).strip() or "Custom"
            self.name_var.set(name)
            self._apply_live()
        except Exception as e:
            messagebox.showerror("Error", f"Could not load theme:\n{e}")

    def _reset(self):
        t = get_theme_tokens(self.current)
        for k, _ in TOKENS:
            self.vars[k].set(t.get(k, ""))
        self._apply_live()

# Factory for embedding in tabs
def create_theme_designer_tab(parent, current_theme: str, on_saved=None, on_apply=None):
    return ThemeDesigner(parent, current_theme=current_theme, on_saved=on_saved, on_apply=on_apply)

# Modal dialog launcher (keeps the old import/usage working)
def open_theme_designer_dialog(parent, current_theme: str, on_saved=None, on_apply=None):
    win = tk.Toplevel(parent)
    win.title("Theme Designer")
    try:
        win.transient(parent)
        win.grab_set()
    except Exception:
        pass
    frm = ThemeDesigner(win, current_theme=current_theme, on_saved=on_saved, on_apply=on_apply)
    frm.pack(fill="both", expand=True)
    btns = ttk.Frame(win); btns.pack(fill="x", padx=10, pady=10)
    ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")
    return win
