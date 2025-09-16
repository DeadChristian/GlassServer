# referral_endpoints.py
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import os
from pathlib import Path

from db import get_conn  # uses your existing db.py

router = APIRouter()

MAX_WINDOWS = {"free": 2, "referral": 3, "pro": 9999}

class HWIDPayload(BaseModel):
    hwid: str

def _ip_ua(request: Request):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:500]
    return ip, ua

@router.post("/ref/create")
def ref_create(p: HWIDPayload):
    # simple code generator
    import secrets, string
    code = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    with get_conn() as conn, conn.cursor() as cur:
        # ensure device + default tier
        cur.execute("INSERT INTO devices (hwid) VALUES (%s) ON CONFLICT DO NOTHING", (p.hwid,))
        cur.execute("INSERT INTO device_tiers (hwid, tier) VALUES (%s,'free') ON CONFLICT DO NOTHING", (p.hwid,))
        cur.execute("INSERT INTO referrals (code, referrer_hwid) VALUES (%s,%s)", (code, p.hwid))
        conn.commit()
    domain = os.getenv("DOMAIN", "http://localhost:8000")
    return {"ok": True, "code": code, "share_link": f"{domain}/?ref={code}"}

@router.post("/ref/click")
def ref_click(code: str, request: Request):
    ip, ua = _ip_ua(request)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ref_clicks (code, ip, user_agent) VALUES (%s,%s,%s)", (code, ip, ua))
        conn.commit()
    return {"ok": True}

@router.get("/download/windows")
def download_windows(request: Request, ref: Optional[str] = None):
    ip, ua = _ip_ua(request)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO ref_downloads (code, ip, user_agent) VALUES (%s,%s,%s)", (ref, ip, ua))
        conn.commit()
    exe_path = Path(__file__).parent / "static" / "GlassSetup.exe"
    if not exe_path.exists():
        raise HTTPException(404, "installer not yet uploaded")
    return FileResponse(str(exe_path), media_type="application/octet-stream", filename="GlassSetup.exe")

@router.post("/ref/hello")
def ref_hello(p: HWIDPayload, request: Request):
    ip, ua = _ip_ua(request)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO devices (hwid) VALUES (%s) ON CONFLICT DO NOTHING", (p.hwid,))
        cur.execute("INSERT INTO activations (hwid, ip, user_agent) VALUES (%s,%s,%s)", (p.hwid, ip, ua))
        # attribute: match last download within 24h
        cur.execute("""
          WITH d AS (
            SELECT code FROM ref_downloads
            WHERE ip = %s AND user_agent = %s
            ORDER BY downloaded_at DESC LIMIT 1
          )
          UPDATE activations a
          SET matched_code = d.code
          FROM d
          WHERE a.hwid = %s AND a.matched_code IS NULL
            AND a.created_at >= (NOW() - INTERVAL '24 hours')
          RETURNING a.matched_code
        """, (ip, ua, p.hwid))
        _ = cur.fetchone()
        # if matched, bump referrer to 'referral' (only if currently free)
        cur.execute("""
          WITH m AS (
            SELECT matched_code FROM activations
            WHERE hwid = %s AND matched_code IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
          )
          UPDATE device_tiers dt
          SET tier='referral', updated_at=NOW()
          FROM referrals r, m
          WHERE r.code = m.matched_code
            AND dt.hwid = r.referrer_hwid
            AND dt.tier = 'free'
        """, (p.hwid,))
        conn.commit()
    return {"ok": True}

class VerifyPayload(BaseModel):
    hwid: str
    license_key: Optional[str] = None

@router.post("/verify")
def verify(p: VerifyPayload):
    tier = "free"
    with get_conn() as conn, conn.cursor() as cur:
        # Optional license-key path (binds to this HWID on first use)
        if p.license_key:
            cur.execute(
                "SELECT tier, hwid, revoked FROM licenses WHERE license_key=%s",
                (p.license_key,),
            )
            row = cur.fetchone()
            if row and row[0] == "pro":
                bound_hwid = row[1]
                revoked = int(row[2] or 0)
                if revoked:
                    return {
                        "ok": True, "valid": False, "tier": "free",
                        "max_windows": 2, "message": "license revoked"
                    }
                if bound_hwid is None:
                    cur.execute(
                        "UPDATE licenses SET hwid=%s WHERE license_key=%s AND hwid IS NULL",
                        (p.hwid, p.license_key),
                    )
                    conn.commit()
                tier = "pro"

        if tier != "pro":
            cur.execute("SELECT tier FROM device_tiers WHERE hwid=%s", (p.hwid,))
            r = cur.fetchone()
            if r:
                tier = r[0]

    return {
        "ok": True, "valid": True, "tier": tier,
        "max_windows": MAX_WINDOWS[tier], "message": f"{tier} plan"
    }
