# GlassServer/admin_ui.py
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from db import get_conn
import os

router = APIRouter()

@router.get("/admin/ui", response_class=HTMLResponse)
def admin_ui(request: Request, secret: str):
    if secret != os.getenv("ADMIN_SECRET"):
        raise HTTPException(401, "unauthorized")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT sale_id, buyer_email, product_id, refunded, created_at
            FROM sales
            ORDER BY created_at DESC
            LIMIT 100
        """)
        sales = cur.fetchall()

        cur.execute("""
            SELECT hwid, tier, updated_at
            FROM device_tiers
            ORDER BY updated_at DESC
            LIMIT 100
        """)
        tiers = cur.fetchall()

        cur.execute("""
            SELECT code, referrer_hwid, successful_activations, created_at
            FROM referrals
            ORDER BY created_at DESC
            LIMIT 100
        """)
        refs = cur.fetchall()

    def rows(data):
        return "".join(f"<tr>{''.join(f'<td>{(c if c is not None else \"\")}</td>' for c in row)}</tr>" for row in data) or "<tr><td colspan=5>None</td></tr>"

    return f"""
    <html><head><title>Glass Admin</title>
    <style>
      body{{font-family:system-ui,Arial;margin:24px}}
      h2{{margin-top:32px}}
      table{{border-collapse:collapse;width:100%}}
      th,td{{border:1px solid #e3e3e3;padding:8px;font-size:14px}}
      th{{background:#fafafa;text-align:left}}
      .wrap{{max-width:1100px;margin:0 auto}}
      code{{background:#f6f6f6;padding:2px 4px;border-radius:4px}}
    </style>
    </head><body><div class="wrap">
      <h1>Glass Admin</h1>
      <p>Secret ok. <code>/admin/ui?secret=***</code></p>

      <h2>Recent Sales</h2>
      <table>
        <tr><th>sale_id</th><th>buyer_email</th><th>product_id</th><th>refunded</th><th>created_at</th></tr>
        {rows(sales)}
      </table>

      <h2>Device Tiers</h2>
      <table>
        <tr><th>hwid</th><th>tier</th><th>updated_at</th></tr>
        {rows(tiers)}
      </table>

      <h2>Referral Codes</h2>
      <table>
        <tr><th>code</th><th>referrer_hwid</th><th>successful_activations</th><th>created_at</th></tr>
        {rows(refs)}
      </table>
    </div></body></html>
    """
