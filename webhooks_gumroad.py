# webhooks_gumroad.py — idempotent Gumroad webhook with safe JSON storage

import os, json, hmac, hashlib
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, HTTPException, Header
from starlette.responses import JSONResponse

# Optional httpx for license verify
try:
    import httpx  # pip install httpx
except Exception:
    httpx = None  # type: ignore

from db import execute, query_one
from helpers_webhook import read_form_safe

# Optional mailer/signing (safe if missing)
try:
    from mailer import send_license_email  # async def send_license_email(...)
except Exception:
    send_license_email = None  # type: ignore

try:
    from utils import sign_action
except Exception:
    sign_action = None  # type: ignore

router = APIRouter()

# ---------- Env ----------
def _env_true(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in ("1", "true", "yes", "on")

EXPECTED_SELLER_ID = (os.getenv("GUMROAD_SELLER_ID") or "").strip()
ALLOWED_PRODUCT_IDS = {p.strip() for p in (os.getenv("GUMROAD_PRODUCT_IDS") or "").split(",") if p.strip()}
ALLOWED_PRODUCT_PERMALINKS = {p.strip() for p in (os.getenv("GUMROAD_PRODUCT_PERMALINKS") or "").split(",") if p.strip()}
DOMAIN = os.getenv("DOMAIN", "http://localhost:8000")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
SKIP_GUMROAD_VALIDATION = _env_true("SKIP_GUMROAD_VALIDATION")
GUMROAD_WEBHOOK_SECRET = (os.getenv("GUMROAD_WEBHOOK_SECRET") or "").strip()
DRY_RUN = _env_true("DRY_RUN")

# --- DB table creation (with retry) ---
def ensure_tables():
    import time
    sql = """
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
    for attempt in range(20):  # ~20s total
        try:
            execute(sql)
            return
        except Exception as e:
            time.sleep(1)


# ---------- Helpers ----------
def _bad(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)

def _normalize_payload(p: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common Gumroad field variations."""
    p = dict(p)
    p["email"] = p.get("email") or p.get("buyer_email") or p.get("purchaser_email")
    p["product_permalink"] = p.get("product_permalink") or p.get("permalink")
    p["product_id"] = p.get("product_id") or p.get("product")
    return p

def _sanity(p: Dict[str, Any]) -> bool:
    # While wiring, only require sale_id
    if SKIP_GUMROAD_VALIDATION:
        return bool(p.get("sale_id"))

    # Strict mode
    if not p.get("sale_id") or not p.get("seller_id"):
        return False
    if not p.get("email"):
        return False
    if not (p.get("product_id") or p.get("product_permalink")):
        return False

    if EXPECTED_SELLER_ID and p.get("seller_id") != EXPECTED_SELLER_ID:
        return False

    if ALLOWED_PRODUCT_IDS or ALLOWED_PRODUCT_PERMALINKS:
        pid = p.get("product_id")
        pp  = p.get("product_permalink")
        ok = (pid in ALLOWED_PRODUCT_IDS) or (pp in ALLOWED_PRODUCT_PERMALINKS)
        if not ok:
            return False

    return True

async def _verify_license_if_present(p: Dict[str, Any]) -> bool:
    lic = p.get("license_key")
    if not lic:
        return True
    if httpx is None:
        return True

    data: Dict[str, Any] = {"license_key": lic}
    if p.get("product_permalink"):
        data["product_permalink"] = p["product_permalink"]
    elif p.get("product_id"):
        data["product_id"] = p["product_id"]
    else:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post("https://api.gumroad.com/v2/licenses/verify", data=data)
        if r.status_code != 200:
            return False
        return bool(r.json().get("success"))
    except Exception:
        # Network issue: do not crash webhook
        return True

def _already(sale_id: str) -> bool:
    return bool(query_one("SELECT sale_id FROM gumroad_sales WHERE sale_id=:s", {"s": sale_id}))

def _i(x) -> int:
    try:
        return int(x) if x is not None else 0
    except Exception:
        return 0

def _store(p: Dict[str, Any]) -> None:
    if DRY_RUN:
        print("DRY_RUN: skipping DB store")
        return
    row = {
        "sale_id": p.get("sale_id"),
        "order_number": p.get("order_number"),
        "product_id": p.get("product_id"),
        "product_name": p.get("product_name"),
        "product_permalink": p.get("product_permalink"),
        "buyer_email": p.get("email"),
        "full_name": p.get("full_name"),
        "price_cents": _i(p.get("price")),
        "quantity": _i(p.get("quantity") or "1"),
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

def _upgrade_link() -> Optional[str]:
    if not ADMIN_SECRET or not sign_action:
        return None
    token = sign_action(ADMIN_SECRET, "pro-upgrade")
    return f"{DOMAIN}/admin/upgrade-to-pro?token={token}"

# ---------- Routes ----------
@router.get("/webhooks/gumroad")
@router.get("/gumroad")
async def gumroad_alive():
    return {"ok": True, "use": "POST /webhooks/gumroad or /gumroad"}

@router.post("/webhooks/gumroad")
@router.post("/gumroad")
async def gumroad_webhook(
    request: Request,
    x_gumroad_signature: Optional[str] = Header(default=None),
):
    try:
        payload = await read_form_safe(request)
        payload = _normalize_payload(payload)

        if not _sanity(payload):
            raise _bad("Invalid Gumroad ping")

        # Optional HMAC signature (only if you set a secret in Gumroad)
        if GUMROAD_WEBHOOK_SECRET and not SKIP_GUMROAD_VALIDATION:
            body_bytes = await request.body()
            digest = hmac.new(GUMROAD_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
            if not x_gumroad_signature or not hmac.compare_digest(digest, x_gumroad_signature):
                raise _bad("Bad signature")

        sid = payload.get("sale_id")
        if _already(sid):
            return JSONResponse({"ok": True, "duplicate": True})

        if not SKIP_GUMROAD_VALIDATION:
            if not await _verify_license_if_present(payload):
                raise _bad("License verification failed")

        # Guard DB: do not 500 the webhook during wiring
        try:
            _store(payload)
        except Exception as db_err:
            print("STORE ERROR:", repr(db_err))
            return JSONResponse({"ok": True, "stored": False, "reason": "db_error"})

        # Optional fulfillment email (non-blocking)
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
            except Exception as mail_err:
                print("MAIL ERROR:", repr(mail_err))

        return JSONResponse({"ok": True})

    except HTTPException:
        raise
    except Exception as e:
        print("GUMROAD WEBHOOK ERROR:", repr(e))
        return JSONResponse({"ok": False, "error": "internal"}, status_code=500)
