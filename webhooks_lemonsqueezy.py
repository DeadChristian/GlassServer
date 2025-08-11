# webhooks_lemonsqueezy.py
import os, hmac, hashlib
from fastapi import APIRouter, Request, HTTPException
from db import get_conn

router = APIRouter()

@router.post("/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request):
    # Verify HMAC signature
    secret = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(500, "LEMONSQUEEZY_WEBHOOK_SECRET not set")

    raw = await request.body()
    got_sig = request.headers.get("X-Signature", "")
    want_sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(got_sig, want_sig):
        raise HTTPException(400, "invalid signature")

    # Parse event
    payload = await request.json()
    meta = (payload.get("meta") or {})
    event_name = meta.get("event_name")

    data = (payload.get("data") or {}).get("attributes") or {}
    buyer_email = data.get("user_email")
    custom = data.get("custom_data") or {}
    hwid = custom.get("hwid")  # you must pass HWID via LS Checkout custom data/field

    # Upgrade on successful order events
    if event_name in ("order_created", "order_paid"):
        if hwid:
            with get_conn() as conn, conn.cursor() as cur:
                # ensure device exists
                cur.execute("INSERT INTO devices (hwid) VALUES (%s) ON CONFLICT DO NOTHING", (hwid,))
                # set tier to pro
                cur.execute("""
                    INSERT INTO device_tiers (hwid, tier)
                    VALUES (%s, 'pro')
                    ON CONFLICT (hwid) DO UPDATE SET tier='pro', updated_at=NOW()
                """, (hwid,))
                conn.commit()
        # (Optional) You can also log the event into a table if you want.

    return {"ok": True}
