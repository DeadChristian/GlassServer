# main.py — FastAPI entrypoint for Glass (Railway/Docker friendly)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from webhooks_gumroad import router as gumroad_router, ensure_tables

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure DB tables exist before serving requests (SQLite or Postgres)
    ensure_tables()
    yield  # add shutdown cleanup after this if needed

app = FastAPI(
    title="Glass Licensing API",
    version="1.0.0",
    lifespan=lifespan,
)

@app.get("/")
def root():
    return {"ok": True, "service": "glass", "docs": "/docs", "health": "/healthz"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

# Mount Gumroad webhook routes at both paths:
#   /gumroad                (handy for manual tests)
#   /webhooks/gumroad       (your production webhook URL)
app.include_router(gumroad_router)                     # /gumroad
app.include_router(gumroad_router, prefix="/webhooks") # /webhooks/gumroad

# Local dev: `python main.py`
if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
