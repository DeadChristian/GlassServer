from fastapi import Request

# Dummy placeholders until you implement real rate limiting
async def global_rate_limit(request: Request):
    pass

def limiter(limit: int, per_seconds: int, key: str):
    def decorator(func):
        return func
    return decorator
