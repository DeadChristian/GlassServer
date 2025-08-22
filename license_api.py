# license_api.py — FastAPI router for Pro licensing (activate + validate)
import os, time, secrets
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import execute, query_one, query_all  # uses your existing DB helpers

router = APIRouter()

PRO_DOWNLOAD_URL = os.getenv("PRO_DOWNLOAD_URL", "https://www.glassapp.me/downloads/pro")
DEFAULT_TIER = "pro"
TOKEN_TTL_DAYS = int(os.getenv("TOKEN_TTL_DAYS", "90"))  # rotate every ~3 months
NOW = lambda: int(time.time())

# ──────────────────────────────────────────────────────────────────────────────
# Schema bootstrap
# ──────────────────────────────────────────────────────────────────────────────
def ensure_license_tables():
    # license_keys: created by you (or Gumroad webhook) at time of sale
    execute("""
    CREATE TABLE IF NOT EXISTS license_keys (
        id               INTEGER PRIMARY KEY,
        key              TEXT UNIQUE NOT NULL,
        tier             TEXT NOT NULL DEFAULT 'pro',
        max_activations  INTEGER NOT NULL DEFAULT 1,
        created_at       INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        revoked          INTEGER NOT NULL DEFAULT 0
    );
    """)
    # license_tokens: issued to a specific hwid on activation
    execute("""
    CREATE TABLE IF NOT EXISTS license_tokens (
        id          INTEGER PRIMARY KEY,
        token       TEXT UNIQUE NOT NULL,
        key_id      INTEGER NOT NULL,
        hwid        TEXT NOT NULL,
        tier        TEXT NOT NULL,
        created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        expires_at  INTEGER,
        revoked     INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(key_id) REFERENCES license_keys(id)
    );
    """)
    # helpful indexes
    execute("CREATE INDEX IF NOT EXISTS idx_tokens_key ON license_tokens(key_id);")
    execute("CREATE INDEX IF NOT EXISTS idx_tokens_token ON license_tokens(token);")
    execute("CREATE INDEX IF NOT EXISTS idx_tokens_hwid ON license_tokens(hwid);")

# ──────────────────────────────────────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────────────────────────────────────
class ActivateReq(BaseModel):
    key: str
    hwid: str
    app_version: Optional[str] = None

class ValidateReq(BaseModel):
    token: str
    hwid: str
    app_version: Optional[str] = None

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _issue_token(key_id: int, hwid: str, tier: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = NOW() + TOKEN_TTL_DAYS * 86400 if TOKEN_TTL_DAYS > 0 else None
    execute(
        "INSERT INTO license_tokens(token, key_id, hwid, tier, created_at, expires_at, revoked) VALUES(?,?,?,?,?,?,0)",
        (token, key_id, hwid, tier, NOW(), expires_at)
    )
    return token

def _activations_used(key_id: int) -> int:
    row = query_one("SELECT COUNT(*) AS c FROM license_tokens WHERE key_id=? AND revoked=0", (key_id,))
    return int(row["c"]) if row else 0

def _existing_token_for(key_id: int, hwid: str) -> Optional[Dict[str, Any]]:
    return query_one("""
      SELECT * FROM license_tokens
      WHERE key_id=? AND hwid=? AND revoked=0
      ORDER BY created_at DESC LIMIT 1
    """, (key_id, hwid))

def _token_row(token: str) -> Optional[Dict[str, Any]]:
    return query_one("SELECT * FROM license_tokens WHERE token=? LIMIT 1", (token,))

# ──────────────────────────────────────────────────────────────────────────────
# POST /license/activate  { key, hwid }
# - Checks key validity and activation limit
# - Binds to HWID and returns an opaque token
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/activate")
def activate(req: ActivateReq):
    k = query_one("SELECT * FROM license_keys WHERE key=? LIMIT 1", (req.key.strip(),))
    if not k:
        raise HTTPException(status_code=400, detail="invalid_key")
    if int(k["revoked"]) == 1:
        raise HTTPException(status_code=400, detail="revoked_key")

    key_id = int(k["id"])
    tier = str(k.get("tier") or DEFAULT_TIER).lower()
    max_acts = int(k.get("max_activations", 1))

    # If an active token already exists for this HWID, return it
    existing = _existing_token_for(key_id, req.hwid)
    if existing and int(existing.get("revoked", 0)) == 0:
        return {
            "ok": True,
            "tier": tier,
            "token": existing["token"],
            "download_url": PRO_DOWNLOAD_URL,
        }

    # Enforce activation limit
    used = _activations_used(key_id)
    if used >= max_acts:
        # If limit is reached but no token for THIS hwid, block
        raise HTTPException(status_code=403, detail="activation_limit_reached")

    token = _issue_token(key_id, req.hwid, tier)
    return {
        "ok": True,
        "tier": tier,
        "token": token,
        "download_url": PRO_DOWNLOAD_URL,
    }

# ──────────────────────────────────────────────────────────────────────────────
# POST /license/validate { token, hwid }
# - Validates token, not revoked, matches HWID, not expired
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/validate")
def validate(req: ValidateReq):
    t = _token_row(req.token)
    if not t:
        return {"ok": False, "reason": "unknown_token"}

    if int(t.get
