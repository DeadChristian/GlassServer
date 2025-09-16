# license_client.py  — minimal client for GlassServer
import os, json, platform, pathlib, requests

BASE = os.environ.get("GLASS_DOMAIN", "https://www.glassapp.me").rstrip("/")
APP  = "Glass"
PATH = pathlib.Path(os.environ.get("APPDATA", str(pathlib.Path.home()))) / APP / "license.json"
HWID = f"nt-{platform.node()}"  # same format you used in tests

DEFAULT_CAPS = {"free": 1, "starter": 2, "pro": 5}

def _save_token(tok: str) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({"token": tok}), encoding="utf-8")

def clear_token() -> None:
    try: PATH.unlink(missing_ok=True)
    except Exception: pass

def load_token():
    try:
        return json.loads(PATH.read_text(encoding="utf-8")).get("token")
    except Exception:
        return None

def activate(key: str, timeout: float = 8.0) -> dict:
    """POST /license/activate → returns {ok, tier, token, max_concurrent, download_url}"""
    payload = {"hwid": HWID, "key": key.strip()}
    r = requests.post(f"{BASE}/license/activate", json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get("ok") and data.get("token"):
        _save_token(data["token"])
        data["max_windows"] = data.get("max_concurrent", DEFAULT_CAPS.get(data["tier"], 1))
    return data

def validate(timeout: float = 5.0) -> dict:
    """POST /license/validate for saved token → returns {ok, tier, download_url} or {ok:false,...}"""
    tok = load_token()
    if not tok:
        return {"ok": False, "reason": "no_token"}
    payload = {"token": tok, "hwid": HWID}
    r = requests.post(f"{BASE}/license/validate", json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get("ok"):
        data["max_windows"] = DEFAULT_CAPS.get(data["tier"], 1)
    return data


