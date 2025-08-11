import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

app = FastAPI()

# Health check
@app.get("/healthz")
async def health_check():
    return {"status": "ok"}

# Example: return env variables (do NOT expose secrets in production!)
@app.get("/config")
async def get_config():
    return {
        "DOMAIN": os.getenv("DOMAIN"),
        "ADMIN_SECRET": os.getenv("ADMIN_SECRET"),
        "GUMROAD_SELLER_ID": os.getenv("GUMROAD_SELLER_ID"),
        "GUMROAD_PRODUCT_IDS": os.getenv("GUMROAD_PRODUCT_IDS"),
        "GUMROAD_PRODUCT_PERMALINKS": os.getenv("GUMROAD_PRODUCT_PERMALINKS"),
        "SKIP_GUMROAD_VALIDATION": os.getenv("SKIP_GUMROAD_VALIDATION")
    }

# Gumroad webhook endpoint
@app.post("/webhooks/gumroad")
async def gumroad_webhook(request: Request):
    form_data = await request.form()
    sale_id = form_data.get("sale_id")
    seller_id = form_data.get("seller_id")
    product_id = form_data.get("product_id")
    email = form_data.get("email")

    expected_seller_id = os.getenv("GUMROAD_SELLER_ID")
    expected_product_ids = os.getenv("GUMROAD_PRODUCT_IDS", "").split(",")

    # Validate
    if os.getenv("SKIP_GUMROAD_VALIDATION", "false").lower() != "true":
        if seller_id != expected_seller_id or product_id not in expected_product_ids:
            return JSONResponse(content={"detail": "Invalid Gumroad ping"}, status_code=400)

    print(f"✅ Payment received from {email} for product {product_id} (sale: {sale_id})")

    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
