# main.py — FastAPI entrypoint for Glass (Railway/Docker friendly)

from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, HTTPException, Query
from webhooks_gumroad import router as gumroad_router, ensure_tables
from db import query_all

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")

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

# ---- Admin JSON viewer ----
def _check_admin(secret: str):
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

@app.get("/admin/sales")
def admin_sales(secret: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    _check_admin(secret)
    rows = query_all(
        """
        SELECT sale_id, buyer_email, product_id, product_name, product_permalink,
               price_cents, quantity, refunded, created_at
        FROM gumroad_sales
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """,
        {"limit": limit, "offset": offset},
    )
    return {"ok": True, "rows": rows, "count": len(rows)}

@app.get("/admin/sales/{sale_id}")
def admin_sale_by_id(sale_id: str, secret: str):
    _check_admin(secret)
    rows = query_all("SELECT * FROM gumroad_sales WHERE sale_id = :sid", {"sid": sale_id})
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True, "sale": rows[0]}

# Webhook routes at both paths
app.include_router(gumroad_router)                     # /gumroad
app.include_router(gumroad_router, prefix="/webhooks") # /webhooks/gumroad

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
