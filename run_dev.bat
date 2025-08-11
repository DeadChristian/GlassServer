@echo off
REM === Local dev env ===
set PORT=8000
set SKIP_GUMROAD_VALIDATION=true
set DRY_RUN=true
set DB_PATH=%TEMP%\glass.db

REM === Activate venv and run ===
call .\.venv\Scripts\activate
uvicorn main:app --host 0.0.0.0 --port %PORT%
