# main_server.py — Glass Licensing API (Python 3.9+)
# - Loads .env (DOMAIN, ADMIN_SECRET, GUMROAD_* vars)
# - CORS relaxed for dev (tighten allow_origins in prod)
# - Global rate-limit hook (uses your ratelimit.py stubs)
# - Health check + simple root
# - Mounts Gumroad webhook at /webhooks/gumroad

import os
from typing import List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# ---- Load env ---------------------------------------------------------------
load_dotenv()

DOMAIN = os.getenv("DOMAIN", "http://localhost:8000")

# Optional CORS origins from env: "https://app.yourdomain.com,https://glassapp.me"
_allowed: List[str] = [
    o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# ---- App --------------------------------------------------------------------
app = FastAPI(title="Glass Licensing API", version="1.0.0")

# ---- CORS (relaxed for dev; tighten in prod) --------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Global rate limit middleware (your ratelimit.py) -----------------------
try:
    from ratelimit import global_rate_limit
except Exception:
    async def global_rate_limit(request: Request):
        return  # noop if stub missing

@app.middleware("http")
async def _rl_middleware(request: Request, call_next):
    await global_rate_limit(request)
    return await call_next(request)

# ---- Routes -----------------------------------------------------------------
@app.get("/")
async def root():
    return {"ok": True, "service": "Glass Licensing API", "domain": DOMAIN}

@app.get("/healthz")
async def health():
    return {"ok": True}

# ---- Safe include for webhooks ----------------------------------------------
def _safe_include(module_name: str, prefix: str = "/webhooks"):
    """
    Import a module that exposes `router` and include it under `prefix`.
    Won't crash the app if the file is missing or has an error; prints why.
    """
    try:
        module = __import__(module_name, fromlist=["router"])
        router = getattr(module, "router")
        app.include_router(router, prefix=prefix)
        print(f"[mount] Mounted {module_name} at {prefix}")
    except Exception as e:
        print(f"[mount] Skipped {module_name}: {e}")

# Mount ONLY Gumroad (no Stripe)
_safe_include("webhooks_gumroad", prefix="/webhooks")

# (Optional) If you later add Lemon Squeezy, uncomment:
# _safe_include("webhooks_lemonsqueezy", prefix="/webhooks")

# ---- Startup log ------------------------------------------------------------
@app.on_event("startup")
async def _on_startup():
    print("=== Glass Licensing API ===")
    print(f"DOMAIN={DOMAIN}")
    print("Webhooks mounted at /webhooks/*")
    print("===========================")
