# core/license_client.py
from __future__ import annotations
import json, os, time, base64, urllib.request, urllib.error, uuid, platform, hashlib
from typing import Dict, Any, Optional

DOMAIN = os.getenv("GLASS_DOMAIN", "https://www.glassapp.me")

def get_hwid() -> str:
    # simple stable-ish HWID; you can swap to your existing get_hwid()
    n = uuid.getnode()
    s = f"{platform.system()}|{platform.release()}|{n}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]

def _post_json(path: str, payload: Dict[str, Any], timeout: float=5.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{DOMAIN}{path}", data=data,
        headers={"User-Agent": "Glass/1.0", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8").strip()
        return json.loads(body) if body else {}

def activate(license_key: str) -> Dict[str, Any]:
    # exchange license key -> token bound to HWID
    return _post_json("/license/activate", {"hwid": get_hwid(), "key": license_key.strip()})

def verify(token: str) -> Dict[str, Any]:
    # verify a previously minted token
    return _post_json("/license/verify", {"hwid": get_hwid(), "token": token})

def is_token_expiring(claims: Dict[str, Any], within_secs: int = 3*24*3600) -> bool:
    try:
        exp = int(claims.get("exp", 0))
        return (exp - int(time.time())) < within_secs
    except Exception:
        return True
