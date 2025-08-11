# webhooks_gumroad.py — robust Gumroad webhook (idempotent + Postgres/SQLite safe)

import os
import json
import time
import hmac
import hashlib
import secrets, string
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, HTTPException
from starlette.responses import JSONResponse
from urllib.parse import parse_qs

# DB helpers use :name placeholders (db.py adapts for Postgres/SQLite)
from db import execute, query_one
from db import get_conn  # only used for rare connection-level ops
from mailer import send_mail

# Optional httpx for license verification; safe to omit
try:
    import httpx  # pip install httpx
except Exception:
    httpx = None  # type: ignore

# Optional action signer (not required for this flow)
try:
    from utils import sign_action
except Exception:
    sign_action = None  # type: ignore

router = APIRouter()

# ---- Env / flags
DEBUG = (os.getenv("DEBUG", "false").lower() == "true")
DRY_RUN = (os.getenv("DRY_RUN", "false").lower() == "true")
SKIP_VALIDATION = (os.getenv("SKIP_GUMROAD_VALIDATION", "false").lower() == "true")
WEBHOOK_SECRET = os.getenv("GUMROAD_WEBHOOK_SECRET", "")  # optional HMAC

EXPECTED_SELLER_ID = (os.getenv("GUMROAD_SELLER_ID") or "").strip()
ALLOWED_PRODUCT_IDS = {p.strip() for p in (os.getenv("GUMROAD_PRODUCT_IDS") or "").split(",") if p.strip()}
ALLOWED_PRODUCT_PERMALINKS = {p.strip() for p in (os.getenv("GUMROAD_PRODUCT_PERMALINKS") or "").split(",") if p.strip()}

DOMAIN = os.getenv("DOMAIN", "http://localhost:8000")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

# ---- Table creation (Postgres + SQLite)
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
    )
    """
    # retry a bit on boot race conditions
    for _ in range(20):
        try:
            execute(ddl); return
        except Exception as e:
            print("DDL_RETRY:", repr(e)); time.sleep(1)

# ---- License helpers (DB-agnostic via execute/query_one)

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
    execute(
        "INSERT INTO licenses (license_key, buyer_email, tier) VALUES (:key, :em, 'pro')",
        {"key": key, "em": buyer_email},
    )
    return key

def revoke_licenses_for_email(buyer_email: str):
    execute(
        "UPDATE licenses SET revoked=1 WHERE buyer_email=:em AND tier='pro' AND (revoked=0 OR revoked IS NULL)",
        {"em": buyer_email},
    )

def send_license_email_plain(to_email: str, license_key: str):
    body = f"""Thanks for supporting Glass!

You're now Pro (unlimited windows).

Your license key:
{license_key}

Activate on your PC:
1) Open Glass
2) Enter License → paste the key
3) Click Refresh License (if needed)

Download: {os.getenv("DOMAIN","https://glassapp.me")}/download/windows
Policy: Digital license, delivered immediately. All sales are final. If a payment is reversed/charged back, the license will be revoked.

– Glass
"""
    send_mail(to_email, "Your Glass Pro license", body)

# ---- Helpers
def _bad(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)

def _int(x) -> int:
    try:
        return int(x) if x is not None else 0
    except Exception:
        return 0

def _get_sale(sale_id: str) -> Optional[Dict[str, Any]]:
    return query_one("SELECT sale_id, refunded, buyer_email FROM gumroad_sales WHERE sale_id=:s", {"s": sale_id})

def _upgrade_link() -> Optional[str]:
    if not ADMIN_SECRET or not sign_action:
        return None
    tok = sign_action(ADMIN_SECRET, "pro-upgrade")
    return f"{DOMAIN}/admin/upgrade-to-pro?token={tok}"

def _verify_hmac(raw_body: bytes, headers: Dict[str, str]) -> bool:
    """Verify Gumroad HMAC (if WEBHOOK_SECRET is set). Gumroad has used X-Signature or X-Gumroad-Signature."""
    if not WEBHOOK_SECRET:
        return True
    recv = headers.get("x-gumroad-signature") or headers.get("x-signature") or ""
    if not recv:
        return False
    mac = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, recv)

def _sanitize_payload(p: Dict[str, Any]) -> Dict[str, Any]:
    # accept buyer_email alias
    if "email" not in p and "buyer_email" in p:
        p["email"] = p.get("buyer_email")

    # must-have fields
    for k in ("sale_id", "seller_id", "product_id", "email"):
        if not p.get(k):
            raise _bad(f"Missing field: {k}")

    if EXPECTED_SELLER_ID and p["seller_id"] != EXPECTED_SELLER_ID:
        raise _bad("Unknown seller_id")

    if ALLOWED_PRODUCT_IDS and p["product_id"] not in ALLOWED_PRODUCT_IDS:
        raise _bad("Unknown product_id")

    if ALLOWED_PRODUCT_PERMALINKS:
        pp = p.get("product_permalink")
        if pp and pp not in ALLOWED_PRODUCT_PERMALINKS:
            raise _bad("Unknown product_permalink")

    return p

async def _verify_license_if_present(p: Dict[str, Any]) -> bool:
    """Optional Gumroad license verification — skipped if no key/httpx or SKIP_VALIDATION true."""
    if SKIP_VALIDATION:
        return True
    key = p.get("license_key")
    if not key or httpx is None:
        return True
    data: Dict[str, Any] = {"license_key": key}
    if p.get("product_permalink"):
        data["product_permalink"] = p["product_permalink"]
    elif p.get("product_id"):
        data["product_id"] = p["product_id"]
    else:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post("https://api.gumroad.com/v2/licenses/verify", data=data)
        return r.status_code == 200 and bool(r.json().get("success"))
    except Exception:
        # network hiccup: accept instead of 500ing the webhook
        return True

def _store(p: Dict[str, Any]) -> None:
    row = {
        "sale_id": p.get("sale_id"),
        "order_number": p.get("order_number"),
        "product_id": p.get("product_id"),
        "product_name": p.get("product_name"),
        "product_permalink": p.get("product_permalink"),
        "buyer_email": p.get("email"),
        "full_name": p.get("full_name"),
        "price_cents": _int(p.get("price")),
        "quantity": _int(p.get("quantity") or "1"),
        "license_key": p.get("license_key"),
        "refunded": 1 if str(p.get("refunded")).lower() == "true" else 0,
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

# ---- Routes
@router.get("/gumroad")
async def gumroad_alive():
    return {"ok": True, "use": "POST /webhooks/gumroad or /gumroad"}

@router.post("/gumroad")
async def gumroad_webhook(request: Request):
    # read raw body once (for HMAC + parsing)
    raw = await request.body()

    # Verify HMAC if secret is set
    if not _verify_hmac(raw, {k.lower(): v for k, v in request.headers.items()}):
        raise _bad("Invalid signature", 401)

    # Parse payload (prefer raw urlencoded because we already have it)
    payload: Dict[str, Any] = {}
    if raw:
        qs = parse_qs(raw.decode("utf-8", errors="ignore"), keep_blank_values=True)
        payload = {k: v[0] for k, v in qs.items()}
    if not payload:
        # fallback to Starlette Form parser (multipart/form-data)
        form = await request.form()
        payload = {k: v for k, v in form.items()}

    # Normalize + sanity checks
    try:
        payload = _sanitize_payload(payload)
    except HTTPException as exc:
        raise exc

    sid = payload["sale_id"]
    buyer_email = payload.get("email") or ""
    is_refund = 1 if str(payload.get("refunded")).lower() == "true" else 0

    # Optional license verify (Gumroad's own license system, if used)
    if not await _verify_license_if_present(payload):
        raise _bad("License verification failed")

    # Fetch previous sale state (if any)
    prev = _get_sale(sid)

    # Store/UPSERT (always) unless dry-run
    if not DRY_RUN:
        try:
            _store(payload)
        except Exception as e:
            print("STORE_ERROR:", repr(e))
            if DEBUG:
                return JSONResponse({"ok": False, "error": "store_failed", "why": str(e)}, status_code=500)
            raise HTTPException(status_code=500, detail="internal")
    else:
        print("DRY_RUN: skipping DB write")

    # Actions:
    # - First-time paid (no prev and not refund): create license + email
    # - Refund/chargeback (is_refund=1): revoke licenses for buyer
    try:
        if is_refund:
            if buyer_email:
                revoke_licenses_for_email(buyer_email)
        else:
            if prev is None and buyer_email:
                key = get_or_create_pro_license(buyer_email)
                try:
                    send_license_email_plain(buyer_email, key)
                except Exception:
                    pass  # don't fail webhook on email hiccups
    except Exception as e:
        print("LICENSE_FLOW_ERROR:", repr(e))

    # Optional: additional email via upgrade link (kept if you use that flow)
    # link = _upgrade_link()
    # if link and buyer_email and not is_refund and prev is None:
    #     try:
    #         send_mail(buyer_email, "Activate Glass Pro", f"Open this link on the PC running Glass:\n{link}")
    #     except Exception: pass

    return JSONResponse({"ok": True})
