# main.py — FastAPI entrypoint for Glass (Railway/Docker friendly)

from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi import APIRouter

from ratelimit import RateLimiter
from referral_endpoints import router as ref_router
from webhooks_gumroad import router as gumroad_router, ensure_tables

# Optional: Stripe & LemonSqueezy routers (fallback to empty if files not present)
try:
    from webhooks_stripe import router as stripe_router
except Exception:
    stripe_router = APIRouter()
try:
    from webhooks_lemonsqueezy import router as lemon_router
except Exception:
    lemon_router = APIRouter()

from db import query_all, execute

# Robust mail import (stub if missing)
try:
    from mailer import send_mail
except Exception:
    def send_mail(to, subject, body):
        print(f"[MAILER-STUB] to={to!r} subject={subject!r}\n{body}")

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
WEB_DIR = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure DB tables exist before serving requests (SQLite or Postgres)
    try:
        ensure_tables()
    except Exception:
        pass

    # Startup migration: add licenses.revoked (safe if already exists)
    try:
        execute("ALTER TABLE licenses ADD COLUMN revoked INTEGER DEFAULT 0")
    except Exception:
        try:
            execute("ALTER TABLE licenses ADD COLUMN IF NOT EXISTS revoked INTEGER DEFAULT 0")
        except Exception:
            pass

    yield  # add shutdown cleanup here if needed


app = FastAPI(
    title="Glass Licensing API",
    version=os.getenv("APP_VERSION", "1.0.0"),
    lifespan=lifespan,
)

# Global IP-based rate limiter (10 req / 10s)
app.add_middleware(RateLimiter, limit=10, window_seconds=10)

# Core API: referrals/verify/download
app.include_router(ref_router)

# Static site mounted at /launch (place index.html, styles.css, etc. in ./web/)
app.mount("/launch", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


# -------------------- Core utility routes --------------------

@app.get("/")
def root():
    return {"ok": True, "service": "glass", "docs": "/docs", "health": "/healthz"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/version")
def version():
    return {
        "ok": True,
        "app": "glass",
        "version": os.getenv("APP_VERSION", "0.0.0"),
        "git": os.getenv("GIT_SHA", "unknown"),
    }

@app.get("/public-config")
def public_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    def on(name, default="0"):
        return os.getenv(name, default).lower() in ("1","true","yes","on")
    return {
        "app": "glass",
        "pro_sales_enabled": on("PRO_SALES_ENABLED", "0"),
        "buy_url": os.getenv("BUY_URL", ""),
        "price": os.getenv("PRO_PRICE", "9.99"),
    }


# -------------------- Admin JSON + tools --------------------

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

@app.get("/admin/sales")
def admin_sales(secret: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    _check_admin(secret)
    rows = query_all(
        """
        SELECT sale_id, buyer_email, product_id, product_name, product_permalink,
               price_cents, quantity, refunded, created_at
        FROM gumroad_sales
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """,
        {"limit": limit, "offset": offset},
    )
    return {"ok": True, "rows": rows, "count": len(rows)}

@app.get("/admin/sales/{sale_id}")
def admin_sale_by_id(sale_id: str, secret: str):
    _check_admin(secret)
    rows = query_all("SELECT * FROM gumroad_sales WHERE sale_id = :sid", {"sid": sale_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True, "sale": rows[0]}

@app.post("/admin/test-email")
def admin_test_email(to: str = Query(...), secret: str = Query(...)):
    _check_admin(secret)
    send_mail(to, "Glass test", "It works! – Glass")
    return {"ok": True}


# -------------------- Inline Admin UI (HTML-only) --------------------

@app.get("/admin/ui", response_class=HTMLResponse)
def admin_ui():
    html = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Glass Admin • Sales</title>
  <style>
    :root { --bg:#0f1115; --card:#161a22; --muted:#9aa7b5; --text:#e6edf3; --accent:#6ea8fe; --ok:#22c55e; --warn:#f59e0b; --bad:#ef4444; }
    * { box-sizing: border-box; }
    html,body { margin:0; padding:0; background:var(--bg); color:var(--text); font:14px/1.45 system-ui, -apple-system, Segoe UI, Roboto, Arial; }
    header { padding:16px 20px; border-bottom:1px solid #212836; background:var(--card); position:sticky; top:0; z-index:10;}
    h1 { font-size:16px; margin:0; letter-spacing:.2px; }
    .muted { color:var(--muted); }
    .wrap { max-width:1100px; margin:16px auto; padding:0 16px; }
    .controls { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; align-items:center; }
    input, select, button { background:#0f1525; color:var(--text); border:1px solid #263044; border-radius:10px; padding:8px 10px; }
    input:focus, button:focus { outline:1px solid var(--accent); }
    button { cursor:pointer; }
    table { width:100%; border-collapse:collapse; background:var(--card); border-radius:14px; overflow:hidden; }
    th, td { padding:10px 12px; border-bottom:1px solid #212836; text-align:left; vertical-align:top; }
    th { font-weight:600; color:#b9c4d0; background:#151a23; position:sticky; top:61px; z-index:5; }
    td .pill { padding:2px 8px; border-radius:999px; font-size:12px; }
    .ok { background:#16341f; color:#8bf0a4; }
    .warn { background:#3a2a13; color:#f6d399; }
    .bad { background:#3b1212; color:#ffb4b4; }
    .row-actions { display:flex; gap:6px; }
    .row-actions a, .row-actions button { padding:6px 8px; border-radius:8px; border:1px solid #2b354a; background:#11182a; color:#cfe0ff; text-decoration:none; }
    .foot { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:10px; }
    .link { color:#cfe0ff; }
    .small { font-size:12px; }
  </style>
</head>
<body>
<header>
  <h1>Glass Admin <span class="muted">/ Sales</span></h1>
</header>

<div class="wrap">
  <div class="controls">
    <label class="small muted">Secret</label>
    <input id="secret" placeholder="ADMIN_SECRET" size="36" />
    <label class="small muted">Limit</label>
    <select id="limit">
      <option>20</option><option selected>50</option><option>100</option><option>200</option>
    </select>
    <button id="apply">Apply</button>
    <button id="export">Export CSV</button>
    <span id="status" class="small muted"></span>
  </div>

  <table id="tbl">
    <thead>
      <tr>
        <th style="width:210px">Sale</th>
        <th style="width:240px">Buyer</th>
        <th>Product</th>
        <th style="width:120px">Price × Qty</th>
        <th style="width:180px">Created</th>
        <th style="width:180px">Actions</th>
      </tr>
    </thead>
    <tbody id="rows"><tr><td colspan="6" class="muted">Loading…</td></tr></tbody>
  </table>

  <div class="foot">
    <div class="small muted" id="count"></div>
    <div>
      <button id="prev">Prev</button>
      <button id="next">Next</button>
    </div>
  </div>
</div>

<script>
(function(){
  const $ = sel => document.querySelector(sel);
  const params = new URLSearchParams(location.search);
  const origin = location.origin;
  const secretInp = $('#secret');
  const limitSel = $('#limit');
  const status = $('#status');
  const rowsEl = $('#rows');
  const countEl = $('#count');
  let offset = parseInt(params.get('offset')||'0',10);
  let limit  = parseInt(params.get('limit') || '50',10);
  let secret = params.get('secret') || '';

  secretInp.value = secret;
  limitSel.value = String(limit);

  function setStatus(s){ status.textContent = s || ''; }
  function fmtMoney(cents){ if(cents==null) return '-'; return '$'+(cents/100).toFixed(2); }
  function esc(s){ return (s||'').toString().replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m])); }

  async function load(){
    if(!secret){ setStatus('Set secret then Apply'); rowsEl.innerHTML = '<tr><td colspan="6" class="muted">No secret</td></tr>'; return; }
    setStatus('Loading…');
    const qs = new URLSearchParams({ secret, limit: String(limit), offset: String(offset) });
    const r = await fetch(`${origin}/admin/sales?`+qs.toString(), { cache:'no-store' });
    if(!r.ok){
      rowsEl.innerHTML = `<tr><td colspan="6">Error ${r.status}</td></tr>`;
      setStatus('Error '+r.status);
      return;
    }
    const data = await r.json();
    render(data.rows||[], data.count||0);
    setStatus('');
  }

  function render(rows, count){
    countEl.textContent = count ? `${count} rows` : '';
    if(!rows.length){
      rowsEl.innerHTML = '<tr><td colspan="6" class="muted">No data</td></tr>';
      return;
    }
    rowsEl.innerHTML = rows.map(r=>{
      const pid = esc(r.product_id||'');
      const pname = esc(r.product_name||'');
      const email = esc(r.buyer_email||'');
      const sale = esc(r.sale_id||'');
      const created = esc(r.created_at||'');
      const price = fmtMoney(r.price_cents);
      const qty = r.quantity ?? 1;
      const refunded = r.refunded ? '<span class="pill bad">refunded</span>' : '<span class="pill ok">paid</span>';
      const viewJson = `${origin}/admin/sales/${encodeURIComponent(sale)}?secret=${encodeURIComponent(secret)}`;
      return `
      <tr>
        <td><code>${sale}</code><div class="small muted">${refunded}</div></td>
        <td>${email}</td>
        <td>${pname || pid}</td>
        <td>${price} × ${qty}</td>
        <td>${created}</td>
        <td class="row-actions">
          <button onclick="navigator.clipboard.writeText('${sale}')">Copy ID</button>
          <a class="link" target="_blank" href="${viewJson}">JSON</a>
        </td>
      </tr>`;
    }).join('');
  }

  $('#apply').onclick = ()=>{
    secret = secretInp.value.trim();
    limit  = parseInt(limitSel.value,10);
    offset = 0;
    const next = new URL(location.href);
    next.searchParams.set('secret', secret);
    next.searchParams.set('limit',  String(limit));
    next.searchParams.set('offset', String(offset));
    history.replaceState(null, '', next.toString());
    load();
  };

  $('#prev').onclick = ()=>{
    offset = Math.max(0, offset - limit);
    const next = new URL(location.href);
    next.searchParams.set('offset', String(offset));
    history.replaceState(null, '', next.toString());
    load();
  };

  $('#next').onclick = ()=>{
    offset = offset + limit;
    const next = new URL(location.href);
    next.searchParams.set('offset', String(offset));
    history.replaceState(null, '', next.toString());
    load();
  };

  $('#export').onclick = async ()=>{
    if(!secret){ alert('Set secret first'); return; }
    const qs = new URLSearchParams({ secret, limit: '200', offset: '0' });
    const r = await fetch(`${origin}/admin/sales?`+qs.toString(), { cache:'no-store' });
    if(!r.ok){ alert('Export failed: '+r.status); return; }
    const data = await r.json();
    const rows = data.rows || [];
    const cols = ["sale_id","buyer_email","product_id","product_name","product_permalink","price_cents","quantity","refunded","created_at"];
    const csv = [cols.join(",")].concat(
      rows.map(o => cols.map(k=>{
        const v = (o[k] ?? '').toString().replace(/"/g,'""');
        return /[",\n]/.test(v) ? `"${v}"` : v;
      }).join(","))
    ).join("\n");
    const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'gumroad_sales.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if(secret) load();
})();
</script>
</body>
</html>
    """
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


# -------------------- Payments routers --------------------

# New namespaced routes under /payments/*
app.include_router(gumroad_router,   prefix="/payments")     # /payments/gumroad
app.include_router(stripe_router,    prefix="/payments")     # /payments/stripe
app.include_router(lemon_router,     prefix="/payments")     # /payments/lemonsqueezy

# Back-compat legacy paths for Gumroad
app.include_router(gumroad_router)                           # /gumroad
app.include_router(gumroad_router, prefix="/webhooks")       # /webhooks/gumroad


# -------------------- Nice 404 for /launch --------------------

@app.exception_handler(404)
async def not_found(request, exc):
    # Return static 404 for /launch paths; otherwise JSON
    if str(request.url.path).startswith("/launch"):
        nf = WEB_DIR / "404.html"
        if nf.exists():
            return FileResponse(nf, status_code=404)
    return JSONResponse({"detail": "Not Found"}, status_code=404)


# -------------------- Uvicorn local run --------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
