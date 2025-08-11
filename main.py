# main.py  — FastAPI entrypoint (Python 3.9+)

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from webhooks_gumroad import router as gumroad_router

app = FastAPI(title="Glass Licensing API", version="1.0.0")

@app.get("/")
def root():
    return {"ok": True, "service": "glass", "docs": "/docs", "health": "/healthz"}

@app.get("/healthz")
def healthz():
    # simple liveness check for Railway/Cloudflare
    return {"ok": True}

# mount Gumroad routes (exposes /webhooks/gumroad and /gumroad)
app.include_router(gumroad_router)

# local dev launcher: `python main.py`
if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
