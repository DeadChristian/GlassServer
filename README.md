# GlassServer

FastAPI service that serves the Glass download page, static assets, and Pro add-ons.

## Local dev (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r GlassServer/requirements.txt
$env:PYTHONPATH = (Get-Location).Path
uvicorn GlassServer.main:app --host 0.0.0.0 --port 8000 --reload

