from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# -----------------------------
# Settings (Pydantic v2, py39 safe)
# -----------------------------
class Settings(BaseSettings):
    # public config
    domain: str = "https://www.glassapp.me"
    version: str = Field(default="1.0.0", validation_alias="APP_VERSION")
    token_ttl_days: int = 90
    download_url_pro: str = "https://www.glassapp.me/static/Glass.exe"
    addons_url: str = "https://www.glassapp.me/static/pro_addons_v1.zip"
    addons_version: str = "1.0.0"

    # sales/limits/flags
    sales_starter_enabled: bool = False
    sales_starter_price: str = "5"
    sales_starter_buy_url: str = ""
    sales_pro_enabled: bool = True
    sales_pro_price: str = "5"
    sales_pro_buy_url: str = "https://gumroad.com/l/xvphp"

    free_max_windows: int = 1
    starter_max_windows: int = 2
    pro_max_windows: int = 5

    intro_active: bool = True
    price_intro: str = "5"

    referrals_enabled: bool = True
    launch_url: str = "https://www.glassapp.me/launch"

    skip_gumroad_validation: bool = False
    dry_run: bool = False
    debug: bool = False

    # db path (for future license work)
    db_path: str = "glass.db"

    # load env from ./GlassServer/.env then ./.env; ignore unknown envs
    model_config = SettingsConfigDict(
        env_file=("GlassServer/.env", ".env"),
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


def public_config(s: Settings) -> Dict[str, Any]:
    """Shape the JSON the app expects today."""
    return {
        "domain": s.domain,
        "version": s.version,
        "token_ttl_days": s.token_ttl_days,
        "download_url_pro": s.download_url_pro,
        "addons_url": s.addons_url,
        "addons_version": s.addons_version,
        "sales": {
            "starter_enabled": s.sales_starter_enabled,
            "starter_price": s.sales_starter_price,
            "starter_buy_url": s.sales_starter_buy_url,
            "pro_enabled": s.sales_pro_enabled,
            "pro_price": s.sales_pro_price,
            "pro_buy_url": s.sales_pro_buy_url,
        },
        "limits": {
            "free_max_windows": s.free_max_windows,
            "starter_max_windows": s.starter_max_windows,
            "pro_max_windows": s.pro_max_windows,
        },
        "intro": {"active": s.intro_active, "price_intro": s.price_intro},
        "referrals_enabled": s.referrals_enabled,
        "launch_url": s.launch_url,
        "skip_gumroad_validation": s.skip_gumroad_validation,
        "dry_run": s.dry_run,
        "debug": s.debug,
    }


# -----------------------------
# App + static
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="GlassServer", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

settings = Settings()


# -----------------------------
# Routes
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def root():
    index = WEB_DIR / "index.html"
    if index.exists():
        return index.read_text(encoding="utf-8")
    # tiny fallback page
    return """<!doctype html>
<meta charset="utf-8" />
<title>GlassServer ✓ OK</title>
<h1>GlassServer is running ✓</h1>
<p>
  <a href="/healthz">/healthz</a> ·
  <a href="/config">/config</a> ·
  <a href="/static-check">/static-check</a>
</p>
"""


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": settings.version, "static_dir": str(STATIC_DIR)}


@app.get("/config")
def config():
    return JSONResponse(public_config(settings))


@app.get("/static-check")
def static_check():
    files = {}
    def add(name: str):
        p = STATIC_DIR / name
        files[name] = {
            "exists": p.exists(),
            "size_bytes": (p.stat().st_size if p.exists() else 0),
            "href": f"/static/{name}",
        }
    for n in ("Glass.exe", "og.png", "pro_addons_v1.zip"):
        add(n)
    return {"ok": True, "missing": [k for k,v in files.items() if not v["exists"]], "files": files}


# ---- downloads (GET) ----
@app.get("/download/latest")
def download_latest():
    path = STATIC_DIR / "Glass.exe"
    return FileResponse(path, filename="Glass.exe", media_type="application/octet-stream")


@app.get("/addons/latest")
def addons_latest():
    path = STATIC_DIR / "pro_addons_v1.zip"
    return FileResponse(path, filename="pro_addons_v1.zip", media_type="application/octet-stream")


# ---- explicit HEAD (avoid 405 and set correct Content-Length) ----
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
    return _head_file_headers(STATIC_DIR / "Glass.exe", "Glass.exe")

@app.head("/addons/latest")
def head_addons_latest():
    return _head_file_headers(STATIC_DIR / "pro_addons_v1.zip", "pro_addons_v1.zip")
