from fastapi import FastAPI

app = FastAPI(title="Glass Licensing API")

@app.get("/healthz")
async def health():
    return {"ok": True}

def _safe_include(modname: str, prefix: str = "/webhooks"):
    try:
        module = __import__(modname, fromlist=["router"])
        app.include_router(getattr(module, "router"), prefix=prefix)
        print(f"[webhook] Mounted {modname} at {prefix}")
    except Exception as e:
        print(f"[webhook] Skipped {modname}: {e}")

_safe_include("webhooks_gumroad")        # /webhooks/gumroad
