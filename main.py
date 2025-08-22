# main.py — FastAPI for Glass (desktop licensing + public-config)
# Endpoints: /public-config, /verify, /license/activate, /license/validate, /license/issue, /ref/create
from contextlib import closing
from pathlib import Path
import os, sqlite3, hashlib, secrets, string, time

from fastapi import FastAPI, HTTPException, Query, Response, Request, APIRouter
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# --- Load env ---------------------------------------------------------------
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# --- Optional routers (won't crash if missing) ------------------------------
try:
    from referral_endpoints import router as ref_router
except Exception:
    ref_router = APIRouter()

try:
    from webhooks_gumroad import router as gumroad_router, ensure_tables as gumroad_ensure_tables
except Exception:
    gumroad_router = APIRouter()
    def gumroad_ensure_tables():
        pass

try:
    from webhooks_stripe import router as stripe_router
except Exception:
    stripe_router = APIRouter()

try:
    from webhooks_lemonsqueezy import router as lemon_router
except Exception:
    lemon_router = APIRouter()

# db helpers used by your Gumroad code; safe fallbacks if not present
try:
    from db import query_all, execute
except Exception:
    def query_all(*args, **kwargs):
        return []
    def execute(*args, **kwargs):
        pass

# mailer is optional
try:
    from mailer import send_mail
except Exception:
    def send_mail(to: str, subject: str, body: str) -> None:
        print(f"[MAILER-STUB] to={to!r} subject={subject!r}\n{body}")

# --- Config -----------------------------------------------------------------
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
WEB_DIR = Path(__file__).parent / "web"

# DB path (absolute so working-directory doesn't matter)
_DB_ENV = os.getenv("DB_PATH", "glass.db")
DB_PATH = str(Path(_DB_ENV) if os.path.isabs(_DB_ENV) else (Path(__file__).parent / _DB_ENV))

# Domain + Pro download URL
DOMAIN = (os.getenv("DOMAIN", "").rstrip("/"))
DOWNLOAD_URL_PRO = os.getenv("DOWNLOAD_URL_PRO", f"{DOMAIN}/static/GlassSetup.exe" if DOMAIN else "")

# Numeric caps (env-overridable)
PRO_MAX_WINDOWS = int(os.getenv("PRO_MAX_WINDOWS", "5"))
STARTER_MAX_WINDOWS = int(os.getenv("STARTER_MAX_WINDOWS", "2"))
FREE_MAX_WINDOWS = int(os.getenv("FREE_MAX_WINDOWS", "1"))

# Token settings
TOKEN_TTL_DAYS = int(os.getenv("TOKEN_TTL_DAYS", "90"))  # rotate every ~3 months
NOW = lambda: int(time.time())

# -------------------- tiny users table for desktop tiers --------------------

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def _init_users_table() -> None:
    with closing(_db()) as con, con:
        con.execute(
            """
        CREATE TABLE IF NOT EXISTS users (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          hwid         TEXT UNIQUE NOT NULL,
          tier         TEXT NOT NULL DEFAULT 'free',
          max_windows  INTEGER,
          created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
        )
        con.execute(
            """
        CREATE TRIGGER IF NOT EXISTS users_touch AFTER UPDATE ON users
        BEGIN
          UPDATE users SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id;
        END;
        """
        )

def _ensure_user_schema(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(users)").fetchall()}
    if "max_windows" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN max_windows INTEGER")

def _get_or_create_user(hwid: str) -> dict:
    try:
        with closing(_db()) as con, con:
            try:
                con.execute("SELECT 1 FROM users LIMIT 1")
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    _init_users_table()
                else:
                    raise
            _ensure_user_schema(con)
            row = con.execute(
                "SELECT hwid, tier, max_windows FROM users WHERE hwid=?",
                (hwid,),
            ).fetchone()
            if row:
                return dict(row)
            con.execute("INSERT INTO users (hwid, tier) VALUES (?, 'free')", (hwid,))
            return {"hwid": hwid, "tier": "free", "max_windows": None}
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            _init_users_table()
            return _get_or_create_user(hwid)
        raise

def _set_user_tier(hwid: str, tier: str, max_windows: Optional[int] = None) -> None:
    with closing(_db()) as con, con:
        try:
            con.execute("SELECT 1 FROM users LIMIT 1")
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                _init_users_table()
            else:
                raise
        _ensure_user_schema(con)
        row = con.execute("SELECT 1 FROM users WHERE hwid=?", (hwid,)).fetchone()
        if not row:
            con.execute("INSERT INTO users (hwid, tier) VALUES (?, 'free')", (hwid,))
        if max_windows is None:
            con.execute("UPDATE users SET tier=? WHERE hwid=?", (tier, hwid))
        else:
            con.execute("UPDATE users SET tier=?, max_windows=? WHERE hwid=?", (tier, max_windows, hwid))

# -------------------- license tables (keys + activations + tokens) ----------

def _init_license_tables(con: sqlite3.Connection) -> None:
    # keys
    con.execute(
        """
    CREATE TABLE IF NOT EXISTS licenses (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      license_key     TEXT UNIQUE NOT NULL,
      buyer_email     TEXT,
      tier            TEXT NOT NULL DEFAULT 'pro',
      max_concurrent  INTEGER DEFAULT 5,
      max_activations INTEGER DEFAULT 3,
      revoked         INTEGER DEFAULT 0,
      issued_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    )
    # activations (legacy; we keep for audit)
    con.execute(
        """
    CREATE TABLE IF NOT EXISTS license_activations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      license_key TEXT NOT NULL,
      hwid        TEXT NOT NULL,
      activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(license_key, hwid)
    );
    """
    )
    # tokens (new; what the client uses)
    con.execute(
        """
    CREATE TABLE IF NOT EXISTS license_tokens (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      token       TEXT UNIQUE NOT NULL,
      license_key TEXT,             -- may be NULL for prefix/admin keys
      hwid        TEXT NOT NULL,
      tier        TEXT NOT NULL,
      created_at  INTEGER NOT NULL,
      expires_at  INTEGER,
      revoked     INTEGER NOT NULL DEFAULT 0
    );
    """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_tokens_token ON license_tokens(token)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_tokens_hwid  ON license_tokens(hwid)")

# -------------------- FastAPI app -------------------------------------------
app = FastAPI(title="Glass Licensing API", version=os.getenv("APP_VERSION", "1.0.0"))

# CORS (if the desktop app calls from a renderer/webview)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("DOMAIN", "*")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve /static and /launch
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
WEB_DIR = Path(__file__).parent / "web"
app.mount("/launch", StaticFiles(directory=str(WEB_DIR), html=True, check_dir=False), name="web")

# Optional global IP rate limit (safe if package missing)
try:
    from ratelimit import RateLimiter  # type: ignore
    app.add_middleware(RateLimiter, limit=10, window_seconds=10)
except Exception:
    pass

@app.on_event("startup")
def _startup():
    try:
        gumroad_ensure_tables()
    except Exception:
        pass
    try:
        _init_users_table()
    except Exception:
        pass
    try:
        with closing(_db()) as con, con:
            _init_license_tables(con)
    except Exception:
        pass

# Core API: referrals (if present)
app.include_router(ref_router)

# -------------------- Utility routes ----------------------------------------
@app.get("/")
def root():
    return {"ok": True, "service": "glass", "docs": "/docs", "health": "/healthz"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/version")
def version():
    return {"ok": True, "app": "glass", "version": os.getenv("APP_VERSION", "0.0.0"), "git": os.getenv("GIT_SHA", "unknown")}

def _env_on(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")

@app.get("/public-config")
def public_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    starter_enabled = _env_on("STARTER_SALES_ENABLED", "1")
    starter_price = os.getenv("STARTER_PRICE", "5")
    starter_buy = os.getenv("STARTER_BUY_URL")
    pro_enabled = _env_on("PRO_SALES_ENABLED", "1")
    pro_price = os.getenv("PRO_PRICE") or os.getenv("price") or "9.99"
    pro_buy = os.getenv("PRO_BUY_URL") or os.getenv("BUY_URL") or "https://www.glassapp.me/buy?tier=pro"
    intro_active = _env_on("INTRO_ACTIVE", "1")
    price_intro = os.getenv("PRICE_INTRO", "5")
    referrals_on = _env_on("REFERRALS_ENABLED", "1")
    if not starter_enabled and not os.getenv("STARTER_BUY_URL"):
        if os.getenv("BUY_URL") and not pro_enabled:
            starter_enabled = True
            starter_buy = os.getenv("BUY_URL")
            starter_price = os.getenv("STARTER_PRICE", "5")
    return {
        "app": "glass",
        "starter_sales_enabled": starter_enabled,
        "starter_price": starter_price,
        "starter_buy_url": starter_buy or "https://www.glassapp.me/buy?tier=starter",
        "pro_sales_enabled": pro_enabled,
        "pro_price": pro_price,
        "pro_buy_url": pro_buy,
        "intro_active": intro_active,
        "price_intro": price_intro,
        "referrals_enabled": referrals_on,
    }

# -------------------- Desktop-tier endpoints --------------------------------
class VerifyIn(BaseModel):
    hwid: str = Field(min_length=1)

class ActivateIn(BaseModel):
    hwid: str = Field(min_length=1)
    key: str = Field(min_length=1)

class ValidateIn(BaseModel):
    token: str = Field(min_length=1)
    hwid: str = Field(min_length=1)

class RefIn(BaseModel):
    hwid: str = Field(min_length=1)

class IssueIn(BaseModel):
    max_concurrent: int = Field(default=5, ge=1, le=50)
    max_activations: int = Field(default=3, ge=1, le=50)
    tier: str = Field(default="pro")
    email: Optional[str] = None
    prefix: str = Field(default="GL")

def _make_key(prefix: str = "GL") -> str:
    alphabet = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(alphabet) for _ in range(5)) for __ in range(3)]
    return f"{prefix}-" + "-".join(parts)

def _is_admin(request: Request, secret_qs: Optional[str]) -> bool:
    auth = request.headers.get("Authorization", "")
    bearer = ""
    if auth.lower().startswith("bearer "):
        bearer = auth[7:]
    return bool(ADMIN_SECRET) and (secret_qs == ADMIN_SECRET or bearer == ADMIN_SECRET)

# ---- Helpers for tokens -----------------------------------------------------

def _issue_token(con: sqlite3.Connection, *, license_key: Optional[str], hwid: str, tier: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = NOW() + TOKEN_TTL_DAYS * 86400 if TOKEN_TTL_DAYS > 0 else None
    con.execute(
        "INSERT INTO license_tokens(token, license_key, hwid, tier, created_at, expires_at, revoked) "
        "VALUES (?,?,?,?,?,?,0)",
        (token, license_key, hwid, tier, NOW(), expires_at),
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
    if exp is not None and isinstance(exp, int) and NOW() > exp:
        return {"ok": False, "reason": "expired"}
    tier = str(row["tier"] or "pro").lower()
    return {"ok": True, "tier": tier}

# ---- Verify: still supports HWID→tier (for UI caps) -------------------------

@app.post("/verify")
def verify(body: VerifyIn):
    u = _get_or_create_user(body.hwid.strip())
    tier = str(u.get("tier", "free")).lower()
    resp = {"tier": tier}
    if u.get("max_windows") is not None:
        resp["max_windows"] = int(u["max_windows"])
        return resp
    if tier == "free":
        resp["max_windows"] = FREE_MAX_WINDOWS
    elif tier == "starter":
        resp["max_windows"] = STARTER_MAX_WINDOWS
    elif tier == "pro":
        resp["max_windows"] = PRO_MAX_WINDOWS
    else:
        resp["max_windows"] = FREE_MAX_WINDOWS
    return resp

# ---- Admin: Issue license keys ---------------------------------------------

@app.post("/license/issue")
def license_issue(body: IssueIn, request: Request, secret: Optional[str] = Query(None)):
    if not _is_admin(request, secret):
        raise HTTPException(status_code=403, detail="Forbidden")
    with closing(_db()) as con, con:
        _init_license_tables(con)
        key = _make_key(body.prefix)
        con.execute(
            "INSERT INTO licenses (license_key, buyer_email, tier, max_concurrent, max_activations) VALUES (?,?,?,?,?)",
            (key, body.email, body.tier, body.max_concurrent, body.max_activations),
        )
        return {"ok": True, "key": key, "tier": body.tier, "max_concurrent": body.max_concurrent, "max_activations": body.max_activations}

# ---- Activate: validates key + HWID, issues opaque token --------------------

@app.post("/license/activate")
def license_activate(body: ActivateIn):
    hwid = body.hwid.strip()
    key = body.key.strip().upper()

    with closing(_db()) as con, con:
        _init_license_tables(con)

        # 1) Backdoor/legacy prefixes (keep your existing behavior, but issue token too)
        if key.startswith("PRO-"):
            tier = "pro"
            _set_user_tier(hwid, tier, None)
            token = _issue_token(con, license_key=None, hwid=hwid, tier=tier)
            return {"ok": True, "tier": tier, "token": token, "max_concurrent": PRO_MAX_WINDOWS, "download_url": DOWNLOAD_URL_PRO}

        if key.startswith("START"):
            tier = "starter"
            _set_user_tier(hwid, tier, None)
            token = _issue_token(con, license_key=None, hwid=hwid, tier=tier)
            return {"ok": True, "tier": tier, "token": token, "max_concurrent": STARTER_MAX_WINDOWS, "download_url": ""}

        # 2) DB-backed licenses
        rec = con.execute(
            "SELECT license_key, tier, max_concurrent, max_activations, revoked FROM licenses WHERE license_key=?",
            (key,),
        ).fetchone()

        if rec:
            if int(rec["revoked"] or 0) == 1:
                raise HTTPException(status_code=400, detail="disabled")
            used = con.execute("SELECT COUNT(*) AS c FROM license_activations WHERE license_key=?", (key,)).fetchone()["c"]
            exists = con.execute("SELECT 1 FROM license_activations WHERE license_key=? AND hwid=?", (key, hwid)).fetchone()
            if not exists and used >= int(rec["max_activations"] or 0):
                raise HTTPException(status_code=400, detail="activation_limit")

            # record activation (idempotent)
            con.execute("INSERT OR IGNORE INTO license_activations (license_key, hwid) VALUES (?,?)", (key, hwid))

            tier = (rec["tier"] or "pro").lower()
            cap = int(rec["max_concurrent"] or (PRO_MAX_WINDOWS if tier == "pro" else STARTER_MAX_WINDOWS if tier == "starter" else FREE_MAX_WINDOWS))

            _set_user_tier(hwid, tier, None)

            # return (or reuse) a token for this hwid
            trow = con.execute(
                "SELECT token FROM license_tokens WHERE license_key=? AND hwid=? AND revoked=0 ORDER BY created_at DESC LIMIT 1",
                (key, hwid)
            ).fetchone()
            if trow:
                token = trow["token"]
            else:
                token = _issue_token(con, license_key=key, hwid=hwid, tier=tier)

            return {"ok": True, "tier": tier, "token": token, "max_concurrent": cap,
                    "download_url": DOWNLOAD_URL_PRO if tier == "pro" else ""}

        # 3) Admin master key (env)
        admin_key = (os.getenv("GLASS_ADMIN_KEY") or "").strip().upper()
        if admin_key and key == admin_key:
            tier = "pro"
            _set_user_tier(hwid, tier, None)
            token = _issue_token(con, license_key=None, hwid=hwid, tier=tier)
            return {"ok": True, "tier": tier, "token": token, "max_concurrent": PRO_MAX_WINDOWS, "download_url": DOWNLOAD_URL_PRO}

    raise HTTPException(status_code=400, detail="invalid key")

# ---- Validate: client sends token + HWID, server confirms -------------------

@app.post("/license/validate")
def license_validate(body: ValidateIn):
    hwid = body.hwid.strip()
    token = body.token.strip()
    with closing(_db()) as con, con:
        _init_license_tables(con)
        res = _validate_token(con, token, hwid)
        if not res.get("ok"):
            return {"ok": False, "reason": res.get("reason", "invalid")}
        tier = res["tier"]
        # Optional: keep users.tier roughly in sync for /verify UX
        _set_user_tier(hwid, tier, None)
        return {"ok": True, "tier": tier, "download_url": DOWNLOAD_URL_PRO if tier == "pro" else ""}

@app.post("/ref/create")
def ref_create(body: 'RefIn'):
    hwid = body.hwid.strip()
    code = hashlib.sha1(hwid.encode("utf-8")).hexdigest()[:8].upper()
    launch = os.getenv("LAUNCH_URL", "https://www.glassapp.me/launch")
    return {"ref_url": f"{launch}?ref={code}", "ref_code": code}

# -------------------- Admin helpers (safe if db.py missing) -----------------

def _check_admin(secret: str):
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

@app.post("/admin/migrate/add-revoked")
def admin_migrate_add_revoked(secret: str = Query(...)):
    _check_admin(secret)
    tried = []
    try:
        execute("ALTER TABLE licenses ADD COLUMN revoked INTEGER DEFAULT 0")
        tried.append("added")
        return {"ok": True, "result": "added"}
    except Exception as e1:
        tried.append(f"plain_failed:{type(e1).__name__}")
        try:
            execute("ALTER TABLE licenses ADD COLUMN IF NOT EXISTS revoked INTEGER DEFAULT 0")
            tried.append("if_not_exists_added")
            return {"ok": True, "result": "added_if_not_exists"}
        except Exception as e2:
            tried.append(f"if_not_exists_failed:{type(e2).__name__}")
            return {"ok": True, "result": "probably_exists", "detail": tried}

# Optional: bulk token migration for legacy activations (issue tokens for all)
@app.post("/admin/migrate/tokens")
def admin_migrate_tokens(secret: str = Query(...)):
    _check_admin(secret)
    issued = 0
    with closing(_db()) as con, con:
        _init_license_tables(con)
        acts = con.execute("SELECT license_key, hwid FROM license_activations").fetchall()
        for a in acts:
            # Skip if a valid token already exists
            trow = con.execute(
                "SELECT token FROM license_tokens WHERE license_key=? AND hwid=? AND revoked=0 LIMIT 1",
                (a["license_key"], a["hwid"])
            ).fetchone()
            if trow:
                continue
            lic = con.execute(
                "SELECT tier FROM licenses WHERE license_key=? AND revoked=0",
                (a["license_key"],)
            ).fetchone()
            tier = (lic["tier"] if lic else "pro").lower()
            _issue_token(con, license_key=a["license_key"], hwid=a["hwid"], tier=tier)
            issued += 1
    return {"ok": True, "issued": issued}

# -------------------- Routers & 404 for /launch -----------------------------
app.include_router(gumroad_router, prefix="/payments")
app.include_router(stripe_router, prefix="/payments")
app.include_router(lemon_router, prefix="/payments")
app.include_router(gumroad_router)
app.include_router(gumroad_router, prefix="/webhooks")

@app.exception_handler(404)
async def not_found(request: Request, exc):
    if str(request.url.path).startswith("/launch"):
        nf = WEB_DIR / "404.html"
        if nf.exists():
            return FileResponse(nf, status_code=404)
    return JSONResponse({"detail": "Not Found"}, status_code=404)

# -------------------- Local run --------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
