# GlassServer/main.py
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------- Settings ----------
class Settings(BaseSettings):
    # load from .env
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # public-ish
    DOMAIN: str = Field(default="https://www.glassapp.me")
    APP_VERSION: str = Field(default="1.0.1")
    TOKEN_TTL_DAYS: int = Field(default=90)

    DOWNLOAD_URL_PRO: str = Field(default="https://www.glassapp.me/static/Glass.exe")
    ADDONS_URL: str = Field(default="https://www.glassapp.me/static/pro_addons_v1.zip")
    ADDONS_VERSION: str = Field(default="1.0.0")

    STARTER_SALES_ENABLED: int = Field(default=0)
    STARTER_PRICE: int = Field(default=5)
    STARTER_BUY_URL: str = Field(default="https://gumroad.com/l/kisnxu")

    PRO_SALES_ENABLED: int = Field(default=1)
    PRO_PRICE: int = Field(default=5)
    PRO_BUY_URL: str = Field(default="https://gumroad.com/l/xvphp")

    FREE_MAX_WINDOWS: int = Field(default=1)
    STARTER_MAX_WINDOWS: int = Field(default=2)
    PRO_MAX_WINDOWS: int = Field(default=5)

    INTRO_ACTIVE: int = Field(default=1)
    PRICE_INTRO: int = Field(default=5)

    REFERRALS_ENABLED: int = Field(default=1)
    LAUNCH_URL: str = Field(default="https://www.glassapp.me/launch")

    SKIP_GUMROAD_VALIDATION: bool = Field(default=False)
    DRY_RUN: bool = Field(default=False)
    DEBUG: bool = Field(default=False)

    # private/server
    DB_PATH: str = Field(default="glass.db")
    ADMIN_SECRET: Optional[str] = Field(default=None)

    # computed/infra
    PYTHON_VERSION: Optional[str] = None


settings = Settings()

# Paths
HERE = Path(__file__).resolve().parent
DEFAULT_STATIC = (HERE / "web" / "static").resolve()
STATIC_DIR = Path(os.environ.get("STATIC_DIR", str(DEFAULT_STATIC))).resolve()

# Files we expose
EXE_FILE = STATIC_DIR / "Glass.exe"
ZIP_FILE = STATIC_DIR / "pro_addons_v1.zip"
OG_PNG = STATIC_DIR / "og.png"


# ---------- App ----------
class CacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        return resp


app = FastAPI(title="GlassServer", version=settings.APP_VERSION)

# Mount /static (served from STATIC_DIR)
app.mount("/static", CacheStaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------- Helpers ----------
def _etag_for_file(p: Path) -> str:
    st = p.stat()
    raw = f"{st.st_mtime_ns}-{st.st_size}".encode()
    return hashlib.md5(raw).hexdigest()


def _download_response(p: Path, download_name: str) -> FileResponse:
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    resp = FileResponse(
        path=str(p),
        media_type="application/octet-stream",
        filename=download_name,
    )
    # good for installers; lets clients revalidate if changed
    resp.headers["Cache-Control"] = "public, max-age=604800"
    resp.headers["ETag"] = _etag_for_file(p)
    return resp


# ---------- Routes ----------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    html = f"""<!doctype html>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Glass — Download</title>
<link rel="icon" href="/static/favicon.ico">
<meta property="og:title" content="Glass — Download">
<meta property="og:image" content="/static/og.png">
<meta name="theme-color" content="#111111">
<link rel="stylesheet" href="/static/styles.css">

<main class="wrap">
  <header class="hero">
    <img src="/static/glass_logo.svg" alt="Glass" height="48" />
    <h1>Make any window transparent</h1>
    <p class="sub">Free basics. One-time ${settings.PRO_PRICE} for Pro. No telemetry.</p>
  </header>

  <section class="cta">
    <a class="btn" href="/download/latest" download>⬇ Download Glass.exe <span id="exeSize"></span></a>
    <a class="btn ghost" href="/addons/latest"  download>Pro Add-ons <span id="zipSize"></span></a>
    <a class="btn ghost" href="{settings.PRO_BUY_URL}" target="_blank" rel="noreferrer">Buy Pro — ${settings.PRO_PRICE}</a>
  </section>

  <section class="faq">
    <h2>FAQ</h2>
    <ul>
      <li><b>Install?</b> Just run Glass.exe. If SmartScreen appears: More info → Run anyway.</li>
      <li><b>Unlock Pro?</b> Buy on Gumroad, then enter your license in the app.</li>
      <li><b>Offline?</b> 7-day grace after one successful validation.</li>
      <li><b>Shortcuts?</b> Ctrl+Enter apply · Ctrl+0 reset · Ctrl+T Top (Pro) · Ctrl+G Click-through (Pro)</li>
    </ul>
  </section>

  <footer>
    <a href="https://www.glassapp.me/terms" target="_blank" rel="noreferrer">Terms</a> ·
    <a href="https://www.glassapp.me/privacy" target="_blank" rel="noreferrer">Privacy</a>
  </footer>
</main>

<script>
async function headSize(url) {{
  try {{
    const r = await fetch(url, {{ method: 'HEAD' }});
    const len = r.headers.get('content-length');
    if (!len) return '';
    const mb = (Number(len) / (1024*1024)).toFixed(1);
    return `({{mb}} MB)`;
  }} catch {{
    return '';
  }}
}}
(async () => {{
  document.getElementById('exeSize').textContent = '…';
  document.getElementById('zipSize').textContent = '…';
  document.getElementById('exeSize').textContent = await headSize('/download/latest');
  document.getElementById('zipSize').textContent = await headSize('/addons/latest');
}})();
</script>
"""
    return HTMLResponse(content=html)


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "static_dir": str(STATIC_DIR),
    }


@app.get("/config")
async def config():
    return {
        "domain": settings.DOMAIN,
        "version": settings.APP_VERSION,
        "token_ttl_days": settings.TOKEN_TTL_DAYS,
        "download_url_pro": settings.DOWNLOAD_URL_PRO,
        "addons_url": settings.ADDONS_URL,
        "addons_version": settings.ADDONS_VERSION,
        "sales": {
            "starter_enabled": bool(settings.STARTER_SALES_ENABLED),
            "starter_price": str(settings.STARTER_PRICE),
            "starter_buy_url": settings.STARTER_BUY_URL if bool(settings.STARTER_SALES_ENABLED) else "",
            "pro_enabled": bool(settings.PRO_SALES_ENABLED),
            "pro_price": str(settings.PRO_PRICE),
            "pro_buy_url": settings.PRO_BUY_URL,
        },
        "limits": {
            "free_max_windows": settings.FREE_MAX_WINDOWS,
            "starter_max_windows": settings.STARTER_MAX_WINDOWS,
            "pro_max_windows": settings.PRO_MAX_WINDOWS,
        },
        "intro": {
            "active": bool(settings.INTRO_ACTIVE),
            "price_intro": str(settings.PRICE_INTRO),
        },
        "referrals_enabled": bool(settings.REFERRALS_ENABLED),
        "launch_url": settings.LAUNCH_URL,
        "skip_gumroad_validation": bool(settings.SKIP_GUMROAD_VALIDATION),
        "dry_run": bool(settings.DRY_RUN),
        "debug": bool(settings.DEBUG),
    }


@app.get("/static-check")
async def static_check():
    def info(p: Path, href_name: str):
        return {
            "exists": p.exists(),
            "size_bytes": p.stat().st_size if p.exists() else 0,
            "href": f"/static/{href_name}",
        }

    files = {
        "Glass.exe": info(EXE_FILE, "Glass.exe"),
        "og.png": info(OG_PNG, "og.png"),
        "pro_addons_v1.zip": info(ZIP_FILE, "pro_addons_v1.zip"),
    }
    missing = [k for k, v in files.items() if not v["exists"]]
    return {"ok": len(missing) == 0, "missing": missing, "files": files}


@app.get("/download/latest")
async def download_latest():
    return _download_response(EXE_FILE, "Glass.exe")


@app.get("/addons/latest")
async def addons_latest():
    return _download_response(ZIP_FILE, "pro_addons_v1.zip")
# --- HEAD endpoints to avoid 405 locally and ensure correct headers ---
from pathlib import Path
from fastapi import Response

def _head_file_headers(path: Path, filename: str) -> Response:
    size = path.stat().st_size
    return Response(
        status_code=200,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(size),
            "Accept-Ranges": "bytes",
            "Content-Type": "application/octet-stream",
        },
    )

@app.head("/download/latest")
def head_download_latest():
    path = STATIC_DIR / "Glass.exe"
    return _head_file_headers(path, "Glass.exe")

@app.head("/addons/latest")
def head_addons_latest():
    path = STATIC_DIR / "pro_addons_v1.zip"
    return _head_file_headers(path, "pro_addons_v1.zip")
