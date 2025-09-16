# helpers_webhook.py
from fastapi import Request
import urllib.parse

async def read_form_safe(request: Request) -> dict:
    """
    Safely read form data from Request, tolerating odd/missing Content-Type.
    Tries multipart / x-www-form-urlencoded, then falls back to raw body parse.
    """
    ct = (request.headers.get("content-type") or "").lower()

    # Preferred: proper form encodings
    if "multipart/form-data" in ct or "application/x-www-form-urlencoded" in ct:
        try:
            return dict(await request.form())
        except Exception:
            pass

    # Fallback: parse raw body as query string
    try:
        body = (await request.body()).decode(errors="ignore")
        if body:
            parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
            return {k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
                    for k, v in parsed.items()}
    except Exception:
        pass

    return {}


