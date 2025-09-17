# GlassServer/main.py
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, PlainTextResponse

# robust .env loading for both repo and package folder
try:
    from dotenv import load_dotenv  # python-dotenv
    here = Path(__file__).resolve()
    load_dotenv(here.with_name(".env"), override=False)
    # also try repo-root .env (one directory up)
    load_dotenv(here.parent.parent / ".env", override=False)
except Exception:
    pass

# Pydantic v2 settings (works on 3.9+ if we avoid "|" unions)
try:
    from pydantic_settings import BaseSettings
except Exception as e:  # fallback message if dependency missing
    raise RuntimeError(
        "Missing dependency 'pydantic-settings'. Add it to requirements.txt"
    ) from e


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_STATIC = {
    "Glass.exe": "application/octet-stream",
    "og.png": "image/png",
    "pro_addons_v1.zip": "application/zip",
}


def _to_bool(val: Optional[str], default: bool) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


class Settings(BaseSettings):
    # Public
    DOMAIN: str = os.getenv("DOMAIN", "https://www.glassapp.me")
    APP_VERSION: str = os.getenv("APP_VERSION", "1.0.0")
    TOKEN_TTL_DAYS: int = int(os.getenv("TOKEN_TTL_DAYS", "90"))

    DOWNLOAD_URL_PRO: str = os.getenv("DOWNLOAD_URL_PRO", f"{DOMAIN}/static/Glass.exe")
    ADDONS_URL: str = os.getenv("ADDONS_URL", f"{DOMAIN}/static/pro_addons_v1.zip")
    ADDONS_VERSION: str = os.getenv("ADDONS_VERSION", "1.0.0")

    STARTER_SALES_ENABLED: bool = _to_bool(os.getenv("STARTER_SALES_ENABLED"), False)
    STARTER_PRICE: str = os.getenv("STARTER_PRICE", "5")
    STARTER_BUY_URL: str = os.getenv("STARTER_BUY_URL", "https://gumroad.com/l/kisnxu")

    PRO_SALES_ENABLED: bool = _to_bool(os.getenv("PRO_SALES_ENABLED"), True)
    PRO_PRICE: str = os.getenv("PRO_PRICE", "5")
    PRO_BUY_URL: str = os.getenv("PRO_BUY_URL", "https://gumroad.com/l/xvphp")

    FREE_MAX_WINDOWS: int = int(os.getenv("FREE_MAX_WINDOWS", "1"))
    STARTER_MAX_WINDOWS: int = int(os.getenv("STARTER_MAX_WINDOWS", "2"))
    PRO_MAX_WINDOWS: int = int(os.getenv("PRO_MAX_WINDOWS", "5"))

    INTRO_ACTIVE: bool = _to_bool(os.getenv("INTRO_ACTIVE"), True)
    PRICE_INTRO: str = os.getenv("PRICE_INTRO", "5")

    REFERRALS_ENABLED: bool = _to_bool(os.getenv("REFERRALS_ENABLED"), True)
    LAUNCH_URL: str = os.getenv("LAUNCH_URL", f"{DOMAIN}/launch")

    SKIP_GUMROAD_VALIDATION: bool = _to_bool(os.getenv("SKIP_GUMROAD_VALIDATION"), False)
    DRY_RUN: bool = _to_bool(os.getenv("DRY_RUN"), False)
    DEBUG: bool = _to_bool(os.getenv("DEBUG"), False)

    # Non-public/ignored here: DB_PATH, ADMIN_SECRET, etc.

    def public_config(self) -> Dict[str, Any]:
        return {
            "domain": self.DOMAIN,
            "version": self.APP_VERSION,
            "token_ttl_days": self.TOKEN_TTL_DAYS,
            "download_url_pro": self.DOWNLOAD_URL_PRO,
            "addons_url": self.ADDONS_URL,
            "addons_version": self.ADDONS_VERSION,
            "sales": {
                "starter_enabled": self.STARTER_SALES_ENABLED,
                "starter_price": self.STARTER_PRICE,
                "starter_buy_url": self.STARTER_BUY_URL if self.STARTER_SALES_ENABLED else "",
                "pro_enabled": self.PRO_SALES_ENABLED,
                "pro_price": self.PRO_PRICE,
                "pro_buy_url": self.PRO_BUY_URL if self.PRO_SALES_ENABLED else "",
            },
            "limits": {
                "free_max_windows": self.FREE_MAX_WINDOWS,
                "starter_max_windows": self.STARTER_MAX_WINDOWS,
                "pro_max_windows": self.PRO_MAX_WINDOWS,
            },
            "intro": {"active": self.INTRO_ACTIVE, "price_intro": self.PRICE_INTRO},
            "referrals_enabled": self.REFERRALS_ENABLED,
            "launch_url": self.LAUNCH_URL,
            "skip_gumroad_validation": self.SKIP_GUMROAD_VALIDATION,
            "dry_run": self.DRY_RUN,
            "debug": self.DEBUG,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # reads env once and caches


app = FastAPI(title="GlassServer", version=get_settings().APP_VERSION)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<meta charset="utf-8" />
<title>GlassServer ✓ OK</title>
<h1>GlassServer is running ✓</h1>
<p>
  <a href="/healthz">/healthz</a> ·
  <a href="/config">/config</a> ·
  <a href="/static-check">/static-check</a>
</p>
"""
    )


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse(
        {"status": "ok", "version": get_settings().APP_VERSION, "static_dir": str(STATIC_DIR)}
    )


@app.get("/config")
async def config() -> JSONResponse:
    return JSONResponse(get_settings().public_config())


@app.get("/static-list")
async def static_list() -> JSONResponse:
    items = []
    if STATIC_DIR.exists():
        for p in sorted(STATIC_DIR.iterdir()):
            if p.is_file():
                items.append({"name": p.name, "size_bytes": p.stat().st_size})
    return JSONResponse({"count": len(items), "files": items})


@app.get("/static-check")
async def static_check() -> JSONResponse:
    files = {}
    for name in REQUIRED_STATIC:
        path = STATIC_DIR / name
        files[name] = {
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "href": f"/static/{name}",
        }
    missing = [n for n, info in files.items() if not info["exists"]]
    return JSONResponse({"ok": len(missing) == 0, "missing": missing, "files": files})


def _head_only_headers(filename: str, mime: str) -> Dict[str, str]:
    # headers for HEAD response w/o body
    return {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime,
        "Accept-Ranges": "bytes",
    }


def _send_file_or_404(name: str, mime_fallback: str) -> FileResponse:
    path = STATIC_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return FileResponse(path, filename=name, media_type=mime_fallback)


@app.api_route("/download/latest", methods=["GET", "HEAD"])
async def download_latest(request: Request):
    name = "Glass.exe"
    mime = REQUIRED_STATIC.get(name, "application/octet-stream")
    if request.method == "HEAD":
        return Response(status_code=200, headers=_head_only_headers(name, mime))
    return _send_file_or_404(name, mime)


@app.api_route("/addons/latest", methods=["GET", "HEAD"])
async def addons_latest(request: Request):
    name = "pro_addons_v1.zip"
    mime = REQUIRED_STATIC.get(name, "application/zip")
    if request.method == "HEAD":
        return Response(status_code=200, headers=_head_only_headers(name, mime))
    return _send_file_or_404(name, mime)


# Optional plaintext 404 (keeps logs clearer on Railway)
@app.exception_handler(404)
async def not_found(_req: Request, exc: HTTPException):
    return PlainTextResponse("Not Found", status_code=404)
