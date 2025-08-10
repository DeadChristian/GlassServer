from fastapi import APIRouter, Request

router = APIRouter()

@router.post("/webhook/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request):
    payload = await request.body()
    print("LemonSqueezy webhook received:", payload)
    return {"ok": True}
