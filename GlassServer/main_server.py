import os, sqlite3, hashlib
from contextlib import closing
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# --------------------------------------------------------------------
# env + app
# --------------------------------------------------------------------
load_dotenv()
app = FastAPI(title="Glass Server", version="1.0")

DB_PATH = os.getenv("DB_PATH", "glass.db")

# --------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------
def _db() -> sqlite3.Connection:
    # new connection per request; safe for uvicorn workers/threads
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def _init_db() -> None:
    with closing(_db()) as con, con:  # commit context
        con.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          hwid         TEXT UNIQUE NOT NULL,
          tier         TEXT NOT NULL DEFAULT 'free',   -- free | starter | pro
          max_windows  INTEGER,                        -- optional override
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

def _get_or_create_user(hwid: str) -> dict:
    with closing(_db()) as con, con:
        row = con.execute("SELECT hwid, tier, max_windows FROM users WHERE hwid=?", (hwid,)).fetchone()
        if row:
            return dict(row)
        con.execute("INSERT INTO users (hwid, tier) VALUES (?, 'free')", (hwid,))
        return {"hwid": hwid, "tier": "free", "max_windows": None}

def _set_user_tier(hwid: str, tier: str, max_windows: Optional[int] = None) -> None:
    with closing(_db()) as con, con:
        _get_or_create_user(hwid)  # ensure exists
        if max_windows is None:
            con.execute("UPDATE users SET tier=? WHERE hwid=?", (tier, hwid))
        else:
            con.execute("UPDATE users SET tier=?, max_windows=? WHERE hwid=?", (tier, max_windows, hwid))

@app.on_event("startup")
def _on_startup():
    _init_db()

# --------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------
class VerifyIn(BaseModel):
    hwid: str = Field(min_length=1)

class ActivateIn(BaseModel):
    hwid: str = Field(min_length=1)
    key:  str = Field(min_length=1)

class RefIn(BaseModel):
    hwid: str = Field(min_length=1)

# --------------------------------------------------------------------
# Health
# --------------------------------------------------------------------
@app.get("/healthz")
async def health_check():
    return {"status": "ok"}

# ⚠️ Dev helper: returns env values (don’t expose in prod)
@app.get("/config")
async def get_config():
    return {
        "DOMAIN": os.getenv("DOMAIN"),
        "ADMIN_SECRET": os.getenv("ADMIN_SECRET"),
        "GUMROAD_SELLER_ID": os.getenv("GUMROAD_SELLER_ID"),
        "GUMROAD_PRODUCT_IDS": os.getenv("GUMROAD_PRODUCT_IDS"),
        "GUMROAD_PRODUCT_PERMALINKS": os.getenv("GUMROAD_PRODUCT_PERMALINKS"),
        "SKIP_GUMROAD_VALIDATION": os.getenv("SKIP_GUMROAD_VALIDATION")
    }

# --------------------------------------------------------------------
# Public config (consumed by the desktop app)
# --------------------------------------------------------------------
@app.get("/public-config")
async def public_config():
    """
    Controls client pricing UI and buy links.
    Override via .env (see example below).
    """
    data = {
        "starter_sales_enabled": _env_bool("STARTER_SALES_ENABLED", True),
        "starter_price": os.getenv("STARTER_PRICE", "5"),
        "starter_buy_url": os.getenv("STARTER_BUY_URL", "https://www.glassapp.me/buy?tier=starter"),
        "pro_sales_enabled": _env_bool("PRO_SALES_ENABLED", True),
        "pro_price": os.getenv("PRO_PRICE", "9.99"),
        "pro_buy_url": os.getenv("PRO_BUY_URL", "https://www.glassapp.me/buy?tier=pro"),
        "intro_active": _env_bool("INTRO_ACTIVE", False),  # if you want "$5 first month → then $9.99"
        "price_intro": os.getenv("PRICE_INTRO", "5"),
        "referrals_enabled": _env_bool("REFERRALS_ENABLED", False),
    }
    return JSONResponse(data)

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

# --------------------------------------------------------------------
# Verify (tier lookup)
# --------------------------------------------------------------------
@app.post("/verify")
async def verify(body: VerifyIn):
    u = _get_or_create_user(body.hwid.strip())
    resp = {"tier": u.get("tier", "free")}
    if u.get("max_windows"):
        resp["max_windows"] = int(u["max_windows"])
    return JSONResponse(resp)

# --------------------------------------------------------------------
# License activation (simple key format)
# --------------------------------------------------------------------
@app.post("/license/activate")
async def license_activate(body: ActivateIn):
    hwid = body.hwid.strip()
    key  = body.key.strip().upper()

    # Replace this with your real license store if you have one.
    if key.startswith("PRO-"):
        _set_user_tier(hwid, "pro", None)
        return Response(status_code=204)
    if key.startswith("START"):
        _set_user_tier(hwid, "starter", None)
        return Response(status_code=204)

    # Optional: admin override keys via env, e.g. GLASS_ADMIN_KEY=XYZ
    admin_key = (os.getenv("GLASS_ADMIN_KEY") or "").strip().upper()
    if admin_key and key == admin_key:
        _set_user_tier(hwid, "pro", None)
        return Response(status_code=204)

    raise HTTPException(status_code=400, detail="invalid key")

# --------------------------------------------------------------------
# Referral link (optional, no tier changes)
# --------------------------------------------------------------------
@app.post("/ref/create")
async def ref_create(body: RefIn):
    hwid = body.hwid.strip()
    code = hashlib.sha1(hwid.encode("utf-8")).hexdigest()[:8].upper()
    launch = os.getenv("LAUNCH_URL", "https://www.glassapp.me/launch")
    return {"ref_url": f"{launch}?ref={code}", "ref_code": code}

# --------------------------------------------------------------------
# Gumroad Webhook (kept from your file; optional validation)
# Tip: You can use this to mint/issue license keys out-of-band.
# --------------------------------------------------------------------
@app.post("/webhooks/gumroad")
async def gumroad_webhook(request: Request):
    form_data = await request.form()
    sale_id   = form_data.get("sale_id")
    seller_id = form_data.get("seller_id")
    product_id= form_data.get("product_id")
    email     = form_data.get("email")

    expected_seller_id = os.getenv("GUMROAD_SELLER_ID")
    expected_product_ids = (os.getenv("GUMROAD_PRODUCT_IDS", "") or "").split(",")

    if os.getenv("SKIP_GUMROAD_VALIDATION", "false").lower() != "true":
        if seller_id != expected_seller_id or product_id not in expected_product_ids:
            return JSONResponse(content={"detail": "Invalid Gumroad ping"}, status_code=400)

    # At this point you can:
    #  - send an email with a license key (PRO-xxxx or START-xxxx),
    #  - or store a pending entitlement for an email address.
    print(f"✅ Payment received from {email} for product {product_id} (sale: {sale_id})")
    return {"ok": True}

# --------------------------------------------------------------------
# Root
# --------------------------------------------------------------------
@app.get("/")
async def root():
    return {"ok": True}

# --------------------------------------------------------------------
# Local dev runner
# --------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


