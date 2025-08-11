# main.py
from fastapi import FastAPI
from webhooks_gumroad import router as gumroad_router

app = FastAPI(title="Glass Licensing API", version="1.0.0")

@app.get("/")
def root():
    return {"ok": True}

@app.get("/healthz")
def health():
    return {"ok": True}

# Mount Gumroad routes
app.include_router(gumroad_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
