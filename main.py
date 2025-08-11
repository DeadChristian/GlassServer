# main.py — FastAPI entrypoint

from fastapi import FastAPI
from webhooks_gumroad import router as gumroad_router

# only needed if you moved table creation out of module import:
try:
    from webhooks_gumroad import ensure_tables  # function that runs CREATE TABLE IF NOT EXISTS
except Exception:
    ensure_tables = None

app = FastAPI(title="Glass Licensing API", version="1.0.0")

@app.get("/")
def root():
    return {"ok": True, "service": "glass", "docs": "/docs", "health": "/healthz"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.on_event("startup")
async def _startup():
    if ensure_tables:
        ensure_tables()

app.include_router(gumroad_router)

if __name__ == "__main__":
    import os, uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
