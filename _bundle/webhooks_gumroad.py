# webhooks_gumroad.py — Gumroad Ping/Webhook handler (idempotent, PG/SQLite safe)

import os, json, time, hmac, hashlib, secrets, string
from typing import Dict, Any, Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, HTTPException
from starlette.responses import JSONResponse

from db import execute, query_one
from mailer import send_mail

# Optional httpx for Gumroad license verification (not required)
try:
    import httpx
except Exception:
    httpx = None  # type: ignore

router = APIRouter()

# --- Env / flags --------------------------------------------------------------
DEBUG = os.getenv("DEBUG", "false").lower() in ("1","true","yes","on")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1","true","yes","on")
SKIP_VALIDATION = os.getenv("SKIP_GUMROAD_VALIDATION", "false").lower() in ("1","true","yes","on")

WEBHOOK_SECRET = os.getenv("GUMROAD_WEBHOOK_SECRET", "")  # empty when using Ping UI
EXPECTED_SELLER_ID = (os.getenv("GUMROAD_SELLER_ID") or "").strip()

ALLOWED_PRODUCT_IDS = {p.strip() for p in (os.getenv("GUMROAD_PRODUCT_IDS") or "").split(",") if p.strip()}
ALLOWED_PERMALINKS = {p.strip() for p in (os.getenv("GUMROAD_PRODUCT_PERMALINKS") or "").split(",") if p.strip()}

DOMAIN = os.getenv("DOMAIN", "https://glassapp.me")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

# --- Table bootstrap ----------------------------------------------------------
def ensure_tables():
    ddl = """
    CREATE TABLE IF NOT EXISTS gumroad_sales (
        sale_id TEXT PRIMARY KEY,
        order_number TEXT,
        product_id TEXT,
        product_name TEXT,
        product_permalink TEXT,
        buyer_email TEXT,
        full_name TEXT,
        price_cents INTEGER,
        quantity INTEGER,
        license_key TEXT,
        refunded INTEGER DEFAULT 0,
        subscription_id TEXT,
        sale_timestamp TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        raw_json TEXT
    );
    """
    for _ in range(10):
        try:
            execute(ddl); return
        except Exception as e:
            if DEBUG: print("DDL_RETRY", repr(e))
            time.sleep(0.5)

# --- License helpers ----------------------------------------------------------
def _make_license_key():
    alphabet = string.ascii_uppercase + string.digits
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for __ in range(4))

def get_or_create_pro_license(buyer_email: str) -> str:
    row = query_one(
        "SELECT license_key FROM licenses WHERE buyer_email=:em AND tier='pro' AND (revoked=0 OR revoked IS NULL) ORDER BY issued_at DESC LIMIT 1",
        {"em": buyer_email},
    )
    if row and row.get("license_key"):
        return row["license_key"]
    key = _make_license_key()
    execute("INSERT INTO licenses (license_key, buyer_email, tier) VALUES (:k, :em, 'pro')", {"k": key, "em": buyer_email})
    return key

def revoke_licenses_for_email(buyer_email: str):
    execute("UPDATE licenses SET revoked=1 WHERE buyer_email=:em AND tier='pro' AND (revoked=0 OR revoked IS NULL)", {"em": buyer_email})

def send_license_email_plain(to_email: str, license_key: str):
    body = f"""Thanks for supporting Glass!

You're now Pro (unlimited windows).

Your license key:
{license_key}

Activate on your PC:
1) Open Glass
2) Enter License → paste the key
3) If needed, click Refresh License

Download: {DOMAIN}/download/windows
Policy: Digital license, delivered immediately. All sales are final. Chargebacks revoke the license.

– Glass
"""
    send_mail(to_email, "Your Glass Pro license", body)

# --- Helpers ------------------------------------------------------------------
def _http_400(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)

def _as_int(x) -> int:
    try: return int(x) if x is not None else 0
    except Exception: return 0

def _get_sale(sale_id: str) -> Optional[Dict[str, Any]]:
    return query_one("SELECT sale_id, refunded, buyer_email FROM gumroad_sales WHERE sale_id=:s", {"s": sale_id})

def _verify_hmac(raw_body: bytes, headers: Dict[str,str]) -> bool:
    if not WEBHOOK_SECRET:
        return True  # Ping mode: Gumroad doesn't send a signature
    recv = headers.get("x-gumroad-signature") or headers.get("x-signature") or ""
    if not recv:
        return False
    mac = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, recv)

def _allowlists_ok(p: Dict[str, Any]) -> None:
    # seller check (if configured)
    if EXPECTED_SELLER_ID and p.get("seller_id") != EXPECTED_SELLER_ID:
        raise _http_400("Unknown seller_id")

    pid = (p.get("product_id") or "").strip()
    plink = (p.get("product_permalink") or "").strip()

    # accept if any configured allow-list matches
    ok = False
    if ALLOWED_PRODUCT_IDS:
        ok = ok or (pid and pid in ALLOWED_PRODUCT_IDS)
    if ALLOWED_PERMALINKS:
        ok = ok or (plink and plink in ALLOWED_PERMALINKS)

    if (ALLOWED_PRODUCT_IDS or ALLOWED_PERMALINKS) and not ok:
        # pick the most helpful message
        if ALLOWED_PRODUCT_IDS and pid and pid not in ALLOWED_PRODUCT_IDS:
            raise _http_400("Unknown product_id")
        if ALLOWED_PERMALINKS and plink and plink not in ALLOWED_PERMALINKS:
            raise _http_400("Unknown product_permalink")
        # neither provided
        raise _http_400("Missing product_id/product_permalink")

def _store(p: Dict[str, Any]) -> None:
    row = {
        "sale_id": p.get("sale_id"),
        "order_number": p.get("order_number"),
        "product_id": p.get("product_id"),
        "product_name": p.get("product_name"),
        "product_permalink": p.get("product_permalink"),
        "buyer_email": p.get("email") or p.get("buyer_email"),
        "full_name": p.get("full_name"),
        "price_cents": _as_int(p.get("price")),
        "quantity": _as_int(p.get("quantity") or "1"),
        "license_key": p.get("license_key"),
        "refunded": 1 if str(p.get("refunded")).lower() in ("1","true","yes") else 0,
        "subscription_id": p.get("subscription_id"),
        "sale_timestamp": p.get("sale_timestamp"),
        "raw_json": json.dumps(p, separators=(",", ":"), ensure_ascii=False),
    }
    execute("""
    INSERT INTO gumroad_sales(
      sale_id, order_number, product_id, product_name, product_permalink,
      buyer_email, full_name, price_cents, quantity, license_key, refunded,
      subscription_id, sale_timestamp, raw_json
    ) VALUES (
      :sale_id, :order_number, :product_id, :product_name, :product_permalink,
      :buyer_email, :full_name, :price_cents, :quantity, :license_key, :refunded,
      :subscription_id, :sale_timestamp, :raw_json
    )
    ON CONFLICT(sale_id) DO UPDATE SET
      order_number=excluded.order_number,
      product_id=excluded.product_id,
      product_name=excluded.product_name,
      product_permalink=excluded.product_permalink,
      buyer_email=excluded.buyer_email,
      full_name=excluded.full_name,
      price_cents=excluded.price_cents,
      quantity=excluded.quantity,
      license_key=excluded.license_key,
      refunded=excluded.refunded,
      subscription_id=excluded.subscription_id,
      sale_timestamp=excluded.sale_timestamp,
      raw_json=excluded.raw_json
    """, row)

# --- Routes -------------------------------------------------------------------
@router.get("/gumroad")
async def gumroad_alive():
    return {"ok": True, "use": "POST /payments/gumroad (or /gumroad)"}

@router.post("/gumroad")
async def gumroad_webhook(request: Request):
    raw = await request.body()

    # HMAC only if secret set (Ping UI has no secret)
    if not _verify_hmac(raw, {k.lower(): v for k, v in request.headers.items()}):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload (prefer raw x-www-form-urlencoded; fallback to multipart)
    payload: Dict[str, Any] = {}
    if raw:
        try:
            qs = parse_qs(raw.decode("utf-8", errors="ignore"), keep_blank_values=True)
            payload = {k: v[0] for k, v in qs.items()}
        except Exception:
            payload = {}
    if not payload:
        form = await request.form()
        payload = {k: v for k, v in form.items()}

    if DEBUG:
        print("GUMROAD_KEYS", list(payload.keys()))
        preview = {k: payload.get(k) for k in ("sale_id","seller_id","product_id","product_permalink","email","refunded")}
        print("GUMROAD_PREVIEW", preview)

    # Accept Gumroad "Send test ping" (no DB writes)
    if payload.get("test") == "true" or payload.get("action") == "test" or "test" in payload:
        return JSONResponse({"ok": True, "test": True})

    # Minimal required fields for real events
    sale_id = payload.get("sale_id")
    email = payload.get("email") or payload.get("buyer_email")
    if not sale_id or not email:
        if DEBUG: print("GUMROAD_MISSING_CORE_FIELDS", {"sale_id": sale_id, "email": email})
        # return 200 so Gumroad doesn't keep retrying pings with minimal data
        return JSONResponse({"ok": True, "ignored": True})

    # Allow-lists (seller + product id/permalink)
    _allowlists_ok(payload)

    # Optional Gumroad license verify (if you use Gumroad licensing)
    if not await _maybe_verify_license(payload):
        raise _http_400("License verification failed")

    # Idempotent upsert
    if not DRY_RUN:
        try:
            _store(payload)
        except Exception as e:
            if DEBUG: print("STORE_ERROR", repr(e))
            raise HTTPException(status_code=500, detail="store_failed")

    # Post actions
    is_refund = str(payload.get("refunded")).lower() in ("1","true","yes")
    try:
        if is_refund:
            revoke_licenses_for_email(email)
        else:
            if _get_sale(sale_id) is None:
                key = get_or_create_pro_license(email)
                try:
                    send_license_email_plain(email, key)
                except Exception:
                    pass
    except Exception as e:
        if DEBUG: print("LICENSE_FLOW_ERROR", repr(e))

    return JSONResponse({"ok": True})

# --- Optional license verification --------------------------------------------
async def _maybe_verify_license(p: Dict[str, Any]) -> bool:
    if SKIP_VALIDATION or httpx is None:
        return True
    key = p.get("license_key")
    if not key:
        return True
    data: Dict[str, Any] = {"license_key": key}
    if p.get("product_permalink"):
        data["product_permalink"] = p["product_permalink"]
    elif p.get("product_id"):
        data["product_id"] = p["product_id"]
    else:
        return True
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post("https://api.gumroad.com/v2/licenses/verify", data=data)
        return r.status_code == 200 and bool(r.json().get("success"))
    except Exception:
        return True
