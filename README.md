# GlassServer

FastAPI + Uvicorn service for Glass (Windows app) downloads, config, and license APIs.

## Public endpoints
- `/` – HTML sanity page
- `/healthz` – status/version
- `/config` – public config (from Railway Shared Variables)
- `/static-check` – verifies bundled static assets + sizes
- `/download/latest` – returns `Glass.exe` (GET/HEAD; real Content-Length)
- `/addons/latest` – returns `pro_addons_v1.zip` (GET/HEAD; real Content-Length)

## Deploy (Railway, Railpack)
- Source repo: `DeadChristian/GlassServer`
- Root directory: `GlassServer`
- Start command: `python GlassServer/serve.py` (reads `$PORT`)
- Runtime: Python 3.11.x (pinned in `runtime.txt`)

## Shared Variables (examples)
DOMAIN, APP_VERSION, DB_PATH, ADMIN_SECRET, TOKEN_TTL_DAYS,
DOWNLOAD_URL_PRO, ADDONS_URL, ADDONS_VERSION,
STARTER_* / PRO_* pricing + toggles,
FREE_MAX_WINDOWS, STARTER_MAX_WINDOWS, PRO_MAX_WINDOWS,
INTRO_ACTIVE, PRICE_INTRO, REFERRALS_ENABLED, LAUNCH_URL,
GUMROAD_SELLER_ID, GUMROAD_WEBHOOK_SECRET,
SKIP_GUMROAD_VALIDATION, DRY_RUN, DEBUG

## Local dev
$env:PYTHONPATH = (Get-Location).Path
uvicorn GlassServer.main:app --host 0.0.0.0 --port 8000 --reload

## Verify (production)
$ORIGIN = "https://glassserver.up.railway.app"
(iwr "$ORIGIN/?t=$(Get-Random)").StatusCode
(iwr "$ORIGIN/healthz").Content
(iwr "$ORIGIN/config").Content
(iwr "$ORIGIN/static-check").Content
(iwr "$ORIGIN/download/latest" -Method Head -MaximumRedirection 0).Headers["Content-Length"]
(iwr "$ORIGIN/addons/latest"   -Method Head -MaximumRedirection 0).Headers["Content-Length"]
