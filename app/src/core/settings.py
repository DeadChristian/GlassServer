# settings.py — cross-platform JSON settings with atomic writes (Py 3.9+)
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

APP_NAME = "Glass"

# ------------------------------- paths ---------------------------------------
def _default_app_dir() -> Path:
    # Allow explicit override first
    env_dir = os.getenv("GLASS_DIR") or os.getenv("GLASS_APP_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA") or str(Path.home())
        return Path(base) / APP_NAME
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.getenv("XDG_CONFIG_HOME") or (Path.home() / ".config")
        return Path(base) / APP_NAME

APP_DIR: Path = _default_app_dir()
APP_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE: Path = Path(os.getenv("GLASS_SETTINGS_FILE") or (APP_DIR / "settings.json"))
MEMORY_FILE:   Path = Path(os.getenv("GLASS_MEMORY_FILE")   or (APP_DIR / "memory.json"))

# ------------------------------ io helpers -----------------------------------
def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if not path.exists():
            return dict(default)
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if text.strip() else {}
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return dict(default)

def _atomic_write(path: Path, data: Dict[str, Any]) -> bool:
    """
    Write JSON atomically:
      tmp file -> fsync -> replace; keep a .bak of the previous file.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        # Write to a temp file in the same directory for atomic replace
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tf:
            tmp_name = tf.name
            tf.write(payload)
            tf.flush()
            os.fsync(tf.fileno())
        # Best-effort backup of existing file
        if path.exists():
            try:
                path.replace(path.with_suffix(path.suffix + ".bak"))
            except Exception:
                # If backup fails, continue with replace
                pass
        os.replace(tmp_name, path)  # atomic on the same filesystem
        return True
    except Exception:
        try:
            # Clean up orphaned tmp file if something went wrong
            if 'tmp_name' in locals() and os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass
        return False

# ------------------------------ public api -----------------------------------
def load_settings() -> Dict[str, Any]:
    """Load settings dict from SETTINGS_FILE ({} on first run or error)."""
    return _read_json(SETTINGS_FILE, {})

def save_settings(d: Dict[str, Any]) -> bool:
    """Save settings dict to SETTINGS_FILE atomically."""
    return _atomic_write(SETTINGS_FILE, dict(d or {}))

def load_memory() -> Dict[str, Any]:
    """Load auxiliary memory dict from MEMORY_FILE ({} on first run or error)."""
    return _read_json(MEMORY_FILE, {})

def save_memory(d: Dict[str, Any]) -> bool:
    """Save auxiliary memory dict to MEMORY_FILE atomically."""
    return _atomic_write(MEMORY_FILE, dict(d or {}))

# ---- compatibility aliases (used by main_gui via `core.settings`) -----------
def load() -> Dict[str, Any]:
    """Alias for load_settings()."""
    return load_settings()

def save(d: Dict[str, Any]) -> bool:
    """Alias for save_settings()."""
    return save_settings(d)

# ------------------------------ small extras ---------------------------------
def files() -> Tuple[Path, Path, Path]:
    """
    Return (APP_DIR, SETTINGS_FILE, MEMORY_FILE) — handy for diagnostics.
    """
    return APP_DIR, SETTINGS_FILE, MEMORY_FILE

if __name__ == "__main__":
    # Tiny smoke test
    s = load_settings()
    s["_ping"] = "ok"
    save_settings(s)
    print("settings at:", SETTINGS_FILE)
