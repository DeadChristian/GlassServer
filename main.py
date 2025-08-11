# main.py — FastAPI entrypoint (Railway/Docker friendly)

from fastapi import FastAPI
from webhooks_gumroad import router as gumroad_router, ensure_tables

app = FastAPI(title="Glass Licensing API", version="1.0.0")

@app.get("/")
def root():
    return {"ok": True, "service": "glass", "docs": "/docs", "health": "/healthz"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.on_event("startup")
async def _startup():
    # Make sure DB table exists (works for SQLite or Postgres)
    ensure_tables()

# Mount Gumroad routes (/webhooks/gumroad and /gumroad)
app.include_router(gumroad_router)

# Local dev launcher: `python main.py`
if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
