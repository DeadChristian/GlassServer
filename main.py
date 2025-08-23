# main.py - GlassServer (ASCII only)
import os
import sqlite3
import time
import secrets
import string
from contextlib import closing
from typing import Optional, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

# ----- Env -----
DOMAIN = os.getenv("DOMAIN", "").rstrip("/")
DOWNLOAD_URL_PRO = os.getenv(
    "DOWNLOAD_URL_PRO",
    f"{DOMAIN}/static/GlassSetup.exe" if DOMAIN else ""
)
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
DB_PATH = os.getenv("DB_PATH", "glass.db")
TOKEN_TTL_DAYS = int(os.getenv("TOKEN_TTL_DAYS", "90"))
FREE_MAX_WINDOWS = int(os.getenv("FREE_MAX_WINDOWS", "1"))
STARTER_MAX_WINDOWS = int(os.getenv("STARTER_MAX_WINDOWS", "2"))
PRO_MAX_WINDOWS = int(os.getenv("PRO_MAX_WINDOWS", "5"))
PRO_BUY_URL = os.getenv("PRO_BUY_URL", "https://gumroad.com/l/xvphp").strip()

now = lambda: int(time.time())

# ----- App -----
app = FastAPI(title="GlassServer", version=os.getenv("APP_VERSION", "1.0.0"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static mount using absolute path (works in Docker/Railway)
ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ----- DB -----
def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def _init_db() -> None:
    with closing(_db()) as con, con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          hwid        TEXT UNIQUE NOT NULL,
          tier        TEXT NOT NULL DEFAULT 'free',
          max_windows INTEGER,
          created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now')),
          updated_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );""")
        con.execute("""
        CREATE TRIGGER IF NOT EXISTS users_touch AFTER UPDATE ON users
        BEGIN
          UPDATE users SET updated_at=strftime('%s','now') WHERE id=NEW.id;
        END;""")
        con.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
          id               INTEGER PRIMARY KEY AUTOINCREMENT,
          license_key      TEXT UNIQUE NOT NULL,
          buyer_email      TEXT,
          tier             TEXT NOT NULL DEFAULT 'pro',
          max_concurrent   INTEGER NOT NULL DEFAULT 5,
          max_activations  INTEGER NOT NULL DEFAULT 1,
          revoked          INTEGER NOT NULL DEFAULT 0,
          issued_at        INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );""")
        con.execute("""
        CREATE TABLE IF NOT EXISTS license_activations (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          license_key  TEXT NOT NULL,
          hwid         TEXT NOT NULL,
          activated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
          UNIQUE(license_key, hwid)
        );""")
        con.execute("""
        CREATE TABLE IF NOT EXISTS license_tokens (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          token       TEXT UNIQUE NOT NULL,
          license_key TEXT,
          hwid        TEXT NOT NULL,
          tier        TEXT NOT NULL,
          created_at  INTEGER NOT NULL,
          expires_at  INTEGER,
          revoked     INTEGER NOT NULL DEFAULT 0
        );""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_tokens_token ON license_tokens(token);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_tokens_hwid  ON license_tokens(hwid);")

_init_db()

# ----- Models -----
class IssueIn(BaseModel):
    max_concurrent: int = Field(default=5, ge=1, le=50)
    max_activations: int = Field(default=1, ge=1, le=50)
    tier: str = Field(default="pro")
    email: Optional[str] = None
    prefix: str = Field(default="GL")

class ActivateIn(BaseModel):
    hwid: str = Field(min_length=1)
    key:  str = Field(min_length=1)

class ValidateIn(BaseModel):
    token: str = Field(min_length=1)
    hwid:  str = Field(min_length=1)

class VerifyIn(BaseModel):
    hwid: str = Field(min_length=1)

# ----- Helpers -----
def _set_user_tier(hwid: str, tier: str, max_windows: Optional[int] = None) -> None:
    with closing(_db()) as con, con:
        row = con.execute("SELECT id FROM users WHERE hwid=?", (hwid,)).fetchone()
        if not row:
            con.execute("INSERT INTO users (hwid, tier, max_windows) VALUES (?,?,?)", (hwid, tier, max_windows))
        else:
            if max_windows is None:
                con.execute("UPDATE users SET tier=? WHERE hwid=?", (tier, hwid))
            else:
                con.execute("UPDATE users SET tier=?, max_windows=? WHERE hwid=?", (tier, max_windows, hwid))

def _make_key(prefix: str = "GL") -> str:
    alphabet = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(alphabet) for _ in range(5)) for __ in range(3)]
    return f"{prefix}-" + "-".join(parts)

def _issue_token(con: sqlite3.Connection, *, license_key: Optional[str], hwid: str, tier: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = now() + TOKEN_TTL_DAYS * 86400 if TOKEN_TTL_DAYS > 0 else None
    con.execute(
        "INSERT INTO license_tokens(token, license_key, hwid, tier, created_at, expires_at, revoked) VALUES (?,?,?,?,?,?,0)",
        (token, license_key, hwid, tier, now(), expires_at)
    )
    return token

def _validate_token(con: sqlite3.Connection, token: str, hwid: str) -> Dict[str, Any]:
    row = con.execute("SELECT * FROM license_tokens WHERE token=?", (token,)).fetchone()
    if not row:
        return {"ok": False, "reason": "unknown_token"}
    if int(row["revoked"] or 0) == 1:
        return {"ok": False, "reason": "revoked"}
    if hwid != row["hwid"]:
        return {"ok": False, "reason": "hwid_mismatch"}
    exp = row["expires_at"]
    if exp is not None and isinstance(exp, int) and now() > exp:
        return {"ok": False, "reason": "expired"}
    return {"ok": True, "tier": str(row["tier"] or "pro").lower()}

def _require_admin(secret_qs: Optional[str], request: Request) -> None:
    hdr = request.headers.get("Authorization", "")
    bearer = hdr[7:] if hdr.lower().startswith("bearer ") else ""
    if not ADMIN_SECRET or (secret_qs != ADMIN_SECRET and bearer != ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")

# ----- Routes -----
@app.get("/")
def root():
    return {"ok": True, "service": "glass", "docs": "/docs", "health": "/healthz"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/public-config")
def public_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {
        "app": "glass",
        "starter_sales_enabled": os.getenv("STARTER_SALES_ENABLED", "1") in ("1","true","True"),
        "starter_price": os.getenv("STARTER_PRICE", "5"),
        "starter_buy_url": os.getenv("STARTER_BUY_URL", "https://gumroad.com/l/kisnxu"),
        "pro_sales_enabled": os.getenv("PRO_SALES_ENABLED", "1") in ("1","true","True"),
        "pro_price": os.getenv("PRO_PRICE", "9.99"),
        "pro_buy_url": PRO_BUY_URL,
        "intro_active": os.getenv("INTRO_ACTIVE", "1") in ("1","true","True"),
        "price_intro": os.getenv("PRICE_INTRO", "5"),
        "referrals_enabled": os.getenv("REFERRALS_ENABLED", "1") in ("1","true","True"),
    }

@app.get("/buy")
def buy_redirect(tier: str = "pro"):
    return RedirectResponse(url=PRO_BUY_URL, status_code=307)

@app.get("/static-list")
def static_list():
    try:
        files = sorted(p.name for p in STATIC_DIR.iterdir()) if STATIC_DIR.exists() else []
        return {"root": str(ROOT), "static": str(STATIC_DIR), "exists": STATIC_DIR.exists(), "files": files}
    except Exception as e:
        return {"error": str(e)}

@app.post("/license/issue")
def license_issue(body: IssueIn, request: Request, secret: Optional[str] = Query(None)):
    _require_admin(secret, request)
    with closing(_db()) as con, con:
        _init_db()
        key = _make_key(body.prefix)
        con.execute(
            "INSERT INTO licenses (license_key, buyer_email, tier, max_concurrent, max_activations, revoked) VALUES (?,?,?,?,?,0)",
            (key, body.email, body.tier.lower(), body.max_concurrent, body.max_activations)
        )
        return {"ok": True, "key": key, "tier": body.tier.lower(),
                "max_concurrent": body.max_concurrent, "max_activations": body.max_activations}

@app.post("/license/activate")
def license_activate(body: ActivateIn):
    import traceback
    try:
        hwid = body.hwid.strip()
        key  = body.key.strip().upper()
        _init_db()

        # Legacy prefixes (no DB-backed license required)
        if key.startswith("PRO-"):
            tier = "pro"
            with closing(_db()) as con, con:
                _set_user_tier(hwid, tier)
                token = _issue_token(con, license_key=None, hwid=hwid, tier=tier)
            return {
                "ok": True, "tier": tier, "token": token,
                "max_concurrent": PRO_MAX_WINDOWS,
                "download_url": DOWNLOAD_URL_PRO
            }

        if key.startswith("START"):
            tier = "starter"
            with closing(_db()) as con, con:
                _set_user_tier(hwid, tier)
                token = _issue_token(con, license_key=None, hwid=hwid, tier=tier)
            return {
                "ok": True, "tier": tier, "token": token,
                "max_concurrent": STARTER_MAX_WINDOWS,
                "download_url": ""
            }

        # DB-backed license keys
        with closing(_db()) as con, con:
            rec = con.execute("SELECT * FROM licenses WHERE license_key=?", (key,)).fetchone()
            if not rec:
                raise HTTPException(status_code=400, detail="invalid_key")
            if int(rec["revoked"] or 0) == 1:
                raise HTTPException(status_code=400, detail="revoked")

            used = con.execute(
                "SELECT COUNT(*) AS c FROM license_activations WHERE license_key=?",
                (key,)
            ).fetchone()["c"]
            exists = con.execute(
                "SELECT 1 FROM license_activations WHERE license_key=? AND hwid=?",
                (key, hwid)
            ).fetchone()

            if not exists and used >= int(rec["max_activations"] or 1):
                raise HTTPException(status_code=403, detail="activation_limit_reached")

            con.execute(
                "INSERT OR IGNORE INTO license_activations (license_key, hwid) VALUES (?,?)",
                (key, hwid)
            )

            tier = (rec["tier"] or "pro").lower()
            if tier == "pro":
                cap = int(rec["max_concurrent"] or PRO_MAX_WINDOWS)
            elif tier == "starter":
                cap = int(rec["max_concurrent"] or STARTER_MAX_WINDOWS)
            else:
                cap = FREE_MAX_WINDOWS

            trow = con.execute(
                "SELECT token FROM license_tokens WHERE license_key=? AND hwid=? AND revoked=0 ORDER BY created_at DESC LIMIT 1",
                (key, hwid)
            ).fetchone()
            token = trow["token"] if trow else _issue_token(con, license_key=key, hwid=hwid, tier=tier)

        return {
            "ok": True, "tier": tier, "token": token,
            "max_concurrent": cap,
            "download_url": DOWNLOAD_URL_PRO if tier == "pro" else ""
        }

    except HTTPException:
        # FastAPI errors pass through unchanged
        raise
    except Exception as e:
        traceback.print_exc()
        # Surface the exact reason to the client
        raise HTTPException(status_code=500, detail=f"activate_error: {e.__class__.__name__}: {e}")

@app.get("/admin/db-diag")
def db_diag():
    import os, traceback
    try:
        # basic write test
        with closing(_db()) as con, con:
            con.execute("CREATE TABLE IF NOT EXISTS _diag (k TEXT PRIMARY KEY, v TEXT)")
            con.execute("INSERT OR REPLACE INTO _diag(k,v) VALUES (?,?)", ("ts", str(int(time.time()))))
            row = con.execute("SELECT COUNT(*) AS c FROM _diag").fetchone()
        return {
            "db_path": os.path.abspath(DB_PATH),
            "writable": True,
            "rows_in_diag": int(row["c"])
        }
    except Exception as e:
        traceback.print_exc()
        return {"db_path": os.path.abspath(DB_PATH), "writable": False, "error": f"{e.__class__.__name__}: {e}"}

@app.post("/verify")
def verify(body: VerifyIn):
    hwid = body.hwid.strip()
    with closing(_db()) as con, con:
        row = con.execute("SELECT tier, max_windows FROM users WHERE hwid=?", (hwid,)).fetchone()
        tier = (row["tier"] if row else "free").lower()
        maxw = row["max_windows"] if (row and row["max_windows"] is not None) else None
    if maxw is not None:
        return {"tier": tier, "max_windows": int(maxw)}
    if tier == "starter":
        return {"tier": "starter", "max_windows": STARTER_MAX_WINDOWS}
    if tier == "pro":
        return {"tier": "pro", "max_windows": PRO_MAX_WINDOWS}
    return {"tier": "free", "max_windows": FREE_MAX_WINDOWS}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")

