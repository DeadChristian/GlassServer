# paths.py — robust PyInstaller-safe resource helpers
from __future__ import annotations
import sys
from pathlib import Path
from typing import BinaryIO, Optional

def _bases() -> list[Path]:
    """
    Return candidate base directories to search for bundled resources, ordered by priority.
    1) PyInstaller temp dir (_MEIPASS) when frozen
    2) The directory containing this file
    3) The project root (one level up from this file)
    """
    here = Path(__file__).resolve().parent
    bases: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            bases.append(Path(meipass).resolve())
        except Exception:
            pass
    bases.append(here)
    bases.append(here.parent)
    # de-duplicate while preserving order
    seen = set()
    uniq: list[Path] = []
    for b in bases:
        if b not in seen:
            uniq.append(b); seen.add(b)
    return uniq

def _sanitize(relative: str) -> str:
    """
    Normalize a relative resource path; strip leading separators so joins
    don't discard the base, but preserve internal subfolders.
    """
    if not isinstance(relative, str):
        raise TypeError("relative must be a string path")
    # Allow absolute paths unchanged (user knows what they're doing)
    if Path(relative).is_absolute():
        return relative
    # Remove leading slashes/backslashes to keep it relative
    return relative.lstrip("/\\").replace("\\", "/")

def resource_path(relative: str, *, must_exist: bool = False) -> str:
    """
    Resolve a resource path in a way that works both in development and when frozen
    with PyInstaller. Returns a string path (absolute). If must_exist=True and the
    file cannot be found in any of the candidate bases, raises FileNotFoundError.

    Usage:
        icon = resource_path("assets/icon.ico")
        css  = resource_path("assets/ui.css", must_exist=True)
    """
    rel = _sanitize(relative)
    p = Path(rel)

    # If caller passed an absolute path, just return it (optionally verify existence).
    if p.is_absolute():
        if must_exist and not p.exists():
            raise FileNotFoundError(p)
        return str(p)

    for base in _bases():
        cand = (base / rel).resolve()
        # Prevent traversal out of base when not absolute input (safety)
        try:
            cand.relative_to(base.resolve())
        except Exception:
            # If it can't be made relative to base, skip (would escape the base)
            continue
        if cand.exists():
            return str(cand)

    # Fallback: return first base joined (or the relative itself) per must_exist
    fallback = (_bases()[0] / rel).resolve()
    if must_exist:
        raise FileNotFoundError(fallback)
    return str(fallback)

def resource_bytes(relative: str) -> bytes:
    """Convenience: read a resource as bytes. Raises FileNotFoundError if missing."""
    path = Path(resource_path(relative, must_exist=True))
    return path.read_bytes()

def resource_text(relative: str, *, encoding: str = "utf-8", errors: str = "strict") -> str:
    """Convenience: read a resource as text."""
    path = Path(resource_path(relative, must_exist=True))
    return path.read_text(encoding=encoding, errors=errors)

def resource_stream(relative: str, mode: str = "rb") -> BinaryIO:
    """
    Convenience: open a resource as a file object.
    Remember to close the stream when done.
    """
    path = Path(resource_path(relative, must_exist=True))
    return path.open(mode)
