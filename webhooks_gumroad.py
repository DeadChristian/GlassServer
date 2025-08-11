# webhooks_gumroad.py — robust Gumroad webhook (idempotent + Postgres/SQLite safe)

import os
import json
import time
import hmac
import hashlib
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, HTTPException
from starlette.responses import JSONResponse
from urllib.parse import parse_qs

# Optional httpx for license verification; safe to omit
try:
    import httpx  # pip install httpx
except Exception:
    httpx = None  # type: ignore

from db import execute, query_one  # uses :name placeholders (db.py adapts for Postgres)

# Optional mailer/signing (no-ops if not present)
try:
    from mailer import send_license_email  # async def send_license_email(...)
except Exception:
    send_license_email = None  # type: ignore

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
    import time
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
    for _ in range(20):
        try:
            execute(ddl); return
        except Exception as e:
            print("DDL_RETRY:", repr(e)); time.sleep(1)


# ---- Helpers
def _bad(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)

def _int(x) -> int:
    try:
        return int(x) if x is not None else 0
    except Exception:
        return 0

def _already(sale_id: str) -> bool:
    return bool(query_one("SELECT sale_id FROM gumroad_sales WHERE sale_id=:s", {"s": sale_id}))

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
    # constant-time compare
    return hmac.compare_digest(mac, recv)

def _sanitize_payload(p: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize fields and basic allow-listing."""
    # accept buyer_email as alias for email
    if "email" not in p and "buyer_email" in p:
        p["email"] = p.get("buyer_email")

    # Must have these
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
    """Optional license verification — skipped if no key or httpx missing or SKIP_VALIDATION true."""
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

    # Idempotency
    if _already(sid):
        return JSONResponse({"ok": True, "duplicate": True})

    # Optional license verify
    if not await _verify_license_if_present(payload):
        raise _bad("License verification failed")

    # Store or dry-run
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

    # Optional email (best-effort)
    if send_license_email:
        try:
            product = payload.get("product_name") or "Glass"
            lines = [f"Thanks for purchasing {product}!"]
            if payload.get("license_key"):
                lines.append(f"Your license key: {payload['license_key']}")
            link = _upgrade_link()
            if link:
                lines.append("Activate Pro: " + link)
                lines.append("Open this on the same computer that runs Glass to attach your HWID.")
            body = "\n\n".join(lines)
            res = send_license_email(
                to_email=payload.get("email"),
                product_name=product,
                license_key=payload.get("license_key") or "",
                extra_message=body,
            )
            if hasattr(res, "__await__"):
                await res
        except Exception as e:
            print("MAIL_ERROR:", repr(e))

    return JSONResponse({"ok": True})
