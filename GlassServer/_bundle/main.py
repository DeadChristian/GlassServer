# main.py — FastAPI for Glass (desktop licensing + public-config)
# Endpoints: /public-config, /verify, /license/activate, /ref/create
from contextlib import closing
from pathlib import Path
import os, sqlite3, hashlib

from fastapi import FastAPI, HTTPException, Query, Response, Request, APIRouter
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional
from typing import Optional
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# --- Optional routers (won't crash if missing) -------------------------------
try:
    from referral_endpoints import router as ref_router
except Exception:
    ref_router = APIRouter()

try:
    from webhooks_gumroad import router as gumroad_router, ensure_tables as gumroad_ensure_tables
except Exception:
    gumroad_router = APIRouter()
    def gumroad_ensure_tables(): pass  # no-op if file not present

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
    def query_all(*args, **kwargs): return []
    def execute(*args, **kwargs): pass

# mailer is optional
try:
    from mailer import send_mail
except Exception:
    def send_mail(to: str, subject: str, body: str) -> None:
        print(f"[MAILER-STUB] to={to!r} subject={subject!r}\n{body}")

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
WEB_DIR = Path(__file__).parent / "web"

# DB path (absolute so working-directory doesn't matter)
_DB_ENV = os.getenv("DB_PATH", "glass.db")
DB_PATH = str(Path(_DB_ENV) if os.path.isabs(_DB_ENV) else (Path(__file__).parent / _DB_ENV))

# -------------------- tiny users table for desktop tiers ---------------------
def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def _init_users_table() -> None:
    with closing(_db()) as con, con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          hwid         TEXT UNIQUE NOT NULL,
          tier         TEXT NOT NULL DEFAULT 'free', -- free | starter | pro
          max_windows  INTEGER,                      -- optional override
          created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)
        con.execute("""
        CREATE TRIGGER IF NOT EXISTS users_touch AFTER UPDATE ON users
        BEGIN
          UPDATE users SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id;
        END;
        """)

def _ensure_user_schema(con: sqlite3.Connection) -> None:
    """Add missing columns on the fly (handles old DBs)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(users)").fetchall()}
    if "max_windows" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN max_windows INTEGER")

def _get_or_create_user(hwid: str) -> dict:
    try:
        with closing(_db()) as con, con:
            # self-heal: table + columns
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
                (hwid,)
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

# -------------------- FastAPI app -------------------------------------------
app = FastAPI(
    title="Glass Licensing API",
    version=os.getenv("APP_VERSION", "1.0.0"),
)

# Optional global IP rate limit (safe if package missing)
try:
    from ratelimit import RateLimiter  # type: ignore
    app.add_middleware(RateLimiter, limit=10, window_seconds=10)
    print("[BOOT] RateLimiter enabled")
except Exception as e:
    print("[BOOT] RateLimiter not enabled:", repr(e))

@app.on_event("startup")
def _startup():
    try: gumroad_ensure_tables()
    except Exception: pass
    try: _init_users_table()
    except Exception as e: print("[BOOT] users table init error:", repr(e))
    # Optional migration used by older Gumroad code:
    try:
        execute("ALTER TABLE licenses ADD COLUMN revoked INTEGER DEFAULT 0")
    except Exception:
        try: execute("ALTER TABLE licenses ADD COLUMN IF NOT EXISTS revoked INTEGER DEFAULT 0")
        except Exception: pass
    print(f"[BOOT] DB_PATH -> {DB_PATH}")

# Core API: referrals (if present)
app.include_router(ref_router)

# Static site at /launch
app.mount("/launch", StaticFiles(directory=str(WEB_DIR), html=True, check_dir=False), name="web")

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
    """
    Desktop UI config
    Free = 1 window
    Starter = 2 windows ($5)
    Pro = 5 windows (cap to reduce tearing risk)
    """
    response.headers["Cache-Control"] = "no-store"

    starter_enabled = _env_on("STARTER_SALES_ENABLED", "1")
    starter_price   = os.getenv("STARTER_PRICE", "5")
    starter_buy     = os.getenv("STARTER_BUY_URL")

    pro_enabled     = _env_on("PRO_SALES_ENABLED", "1")
    pro_price       = os.getenv("PRO_PRICE") or os.getenv("price") or "9.99"
    pro_buy         = (os.getenv("PRO_BUY_URL")
                       or os.getenv("BUY_URL")
                       or "https://www.glassapp.me/buy?tier=pro")

    intro_active    = _env_on("INTRO_ACTIVE", "1")        # "$5 first month → then $9.99"
    price_intro     = os.getenv("PRICE_INTRO", "5")
    referrals_on    = _env_on("REFERRALS_ENABLED", "1")

    # Legacy-only (single BUY_URL) shim to Starter
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
        # (No numeric caps here; caps are returned by /verify)
    }

# -------------------- Desktop-tier endpoints --------------------------------
class VerifyIn(BaseModel):
    hwid: str = Field(min_length=1)

class ActivateIn(BaseModel):
    hwid: str = Field(min_length=1)
    key:  str = Field(min_length=1)

class RefIn(BaseModel):
    hwid: str = Field(min_length=1)

@app.post("/verify")
def verify(body: VerifyIn):
    u = _get_or_create_user(body.hwid.strip())
    tier = str(u.get("tier", "free")).lower()
    resp = {"tier": tier}

    # Per-user overrides win first
    if u.get("max_windows") is not None:
        resp["max_windows"] = int(u["max_windows"])
        return resp

    # Global caps (Pro capped at 5 by default)
    if tier == "free":
        resp["max_windows"] = 1
    elif tier == "starter":
        resp["max_windows"] = 2
    elif tier == "pro":
        resp["max_windows"] = int(os.getenv("PRO_MAX_WINDOWS", "5"))
    return resp

@app.post("/license/activate")
def license_activate(body: ActivateIn):
    hwid = body.hwid.strip()
    key  = body.key.strip().upper()

    # Launch plan: START-xxxxx => Starter (2), PRO-xxxxx => Pro (5 cap via /verify)
    if key.startswith("PRO-"):
        _set_user_tier(hwid, "pro", None)
        return Response(status_code=204)
    if key.startswith("START"):
        _set_user_tier(hwid, "starter", None)
        return Response(status_code=204)

    admin_key = (os.getenv("GLASS_ADMIN_KEY") or "").strip().upper()
    if admin_key and key == admin_key:
        _set_user_tier(hwid, "pro", None)
        return Response(status_code=204)

    raise HTTPException(status_code=400, detail="invalid key")

@app.post("/ref/create")
def ref_create(body: RefIn):
    hwid = body.hwid.strip()
    code = hashlib.sha1(hwid.encode("utf-8")).hexdigest()[:8].upper()
    launch = os.getenv("LAUNCH_URL", "https://www.glassapp.me/launch")
    return {"ref_url": f"{launch}?ref={code}", "ref_code": code}

# -------------------- Admin helpers (safe if db.py missing) ------------------
def _check_admin(secret: str):
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

@app.post("/admin/migrate/add-revoked")
def admin_migrate_add_revoked(secret: str = Query(...)):
    _check_admin(secret)
    tried = []
    try:
        execute("ALTER TABLE licenses ADD COLUMN revoked INTEGER DEFAULT 0")
        tried.append("added"); return {"ok": True, "result": "added"}
    except Exception as e1:
        tried.append(f"plain_failed:{type(e1).__name__}")
        try:
            execute("ALTER TABLE licenses ADD COLUMN IF NOT EXISTS revoked INTEGER DEFAULT 0")
            tried.append("if_not_exists_added"); return {"ok": True, "result": "added_if_not_exists"}
        except Exception as e2:
            tried.append(f"if_not_exists_failed:{type(e2).__name__}")
            return {"ok": True, "result": "probably_exists", "detail": tried}

@app.get("/admin/sales")
def admin_sales(secret: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    _check_admin(secret)
    rows = query_all("""
        SELECT sale_id, buyer_email, product_id, product_name, product_permalink,
               price_cents, quantity, refunded, created_at
        FROM gumroad_sales
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """, {"limit": limit, "offset": offset})
    return {"ok": True, "rows": rows, "count": len(rows)}

@app.get("/admin/sales/{sale_id}")
def admin_sale_by_id(sale_id: str, secret: str):
    _check_admin(secret)
    rows = query_all("SELECT * FROM gumroad_sales WHERE sale_id = :sid", {"sid": sale_id})
    if not rows: raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True, "sale": rows[0]}

@app.post("/admin/test-email")
def admin_test_email(to: str = Query(...), secret: str = Query(...)):
    _check_admin(secret)
    send_mail(to, "Glass test", "It works! – Glass")
    return {"ok": True}

# -------------------- Routers & 404 for /launch ------------------------------
app.include_router(gumroad_router, prefix="/payments")
app.include_router(stripe_router,  prefix="/payments")
app.include_router(lemon_router,   prefix="/payments")

# Legacy back-compat mounts
app.include_router(gumroad_router)                     # /gumroad
app.include_router(gumroad_router, prefix="/webhooks") # /webhooks/gumroad

@app.exception_handler(404)
async def not_found(request: Request, exc):
    if str(request.url.path).startswith("/launch"):
        nf = WEB_DIR / "404.html"
        if nf.exists():
            return FileResponse(nf, status_code=404)
    return JSONResponse({"detail": "Not Found"}, status_code=404)

# -------------------- Local run ---------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


