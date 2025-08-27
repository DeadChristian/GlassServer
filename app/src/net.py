# net.py — tiny JSON HTTP helpers (stdlib only), hardened
from __future__ import annotations
import json
import time
import random
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

__all__ = ["get_json", "post_json"]

# Default headers; keep it minimal and explicit.
_DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",   # stdlib can handle gzip transparently
    "User-Agent": "Glass/1.0 (+net.py)",
}

def _decode_body(resp: urllib.response.addinfourl, raw: bytes) -> Dict[str, Any]:
    """Best-effort JSON decode with sensible fallbacks; empty -> {}."""
    if not raw:
        return {}
    # Try utf-8 first, then utf-8-sig (BOM), then latin-1 as a last resort.
    text: Optional[str] = None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc, errors="strict")
            break
        except Exception:
            continue
    if text is None:
        # If everything failed, ignore errors to salvage something.
        text = raw.decode("utf-8", errors="ignore")

    text = text.strip()
    if not text:
        return {}
    # If the server lied about content-type, still attempt JSON when it looks like JSON.
    if not (text.startswith("{") or text.startswith("[")):
        # Non-JSON body -> return empty to keep API simple/strict
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}

def _build_request(url: str, data: Optional[Dict[str, Any]], headers: Dict[str, str]) -> urllib.request.Request:
    if data is None:
        return urllib.request.Request(url, headers=headers, method="GET")
    body = json.dumps(data).encode("utf-8")
    return urllib.request.Request(url, data=body, headers=headers, method="POST")

def _request(url: str, data: Optional[Dict[str, Any]], timeout: float) -> Dict[str, Any]:
    """Single attempt; raises on network errors except 204/205 → {}."""
    req = _build_request(url, data, dict(_DEFAULT_HEADERS))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 204/205: no content
            status = getattr(resp, "status", None)
            if status in (204, 205):
                return {}
            raw = resp.read() or b""
            return _decode_body(resp, raw)
    except urllib.error.HTTPError as e:
        # 204/205 with HTTPError (rare but possible with some stacks)
        if e.code in (204, 205):
            return {}
        # Re-raise for retry logic to catch upstream
        raise
    except Exception:
        # Propagate for retry logic
        raise

def _sleep_backoff(i: int, base: float) -> None:
    """
    Exponential backoff with jitter.
    i = attempt index starting at 0.
    """
    # (base * 2^i) + jitter(0..0.25)
    delay = base * (2 ** i) + random.random() * 0.25
    time.sleep(delay)

def get_json(url: str, timeout: float = 5.0, retries: int = 0) -> Dict[str, Any]:
    """
    GET JSON from `url`.
    - Returns {} on empty / non-JSON bodies.
    - Raises the last exception after exhausting retries.
    """
    last_err: Optional[Exception] = None
    for i in range(max(0, retries) + 1):
        try:
            return _request(url, None, timeout)
        except urllib.error.HTTPError as e:
            # Retry on 429 and 5xx; otherwise, fail fast
            if e.code in (429, 500, 502, 503, 504):
                last_err = e
                if i < retries:
                    _sleep_backoff(i, base=0.35)
                    continue
            last_err = e
            break
        except Exception as e:
            last_err = e
            if i < retries:
                _sleep_backoff(i, base=0.35)
                continue
            break
    if last_err:
        raise last_err
    return {}

def post_json(url: str, payload: Dict[str, Any], timeout: float = 6.0, retries: int = 0) -> Dict[str, Any]:
    """
    POST JSON to `url` with `payload`.
    - Returns {} on empty / non-JSON bodies.
    - Raises the last exception after exhausting retries.
    """
    last_err: Optional[Exception] = None
    for i in range(max(0, retries) + 1):
        try:
            return _request(url, payload, timeout)
        except urllib.error.HTTPError as e:
            # Retry on 429 and 5xx; otherwise, fail fast
            if e.code in (429, 500, 502, 503, 504):
                last_err = e
                if i < retries:
                    _sleep_backoff(i, base=0.5)
                    continue
            last_err = e
            break
        except Exception as e:
            last_err = e
            if i < retries:
                _sleep_backoff(i, base=0.5)
                continue
            break
    if last_err:
        raise last_err
    return {}
