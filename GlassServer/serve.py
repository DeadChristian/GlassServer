from __future__ import annotations
import os
import uvicorn

if __name__ == "__main__":
    # Railway sets PORT at runtime (string). Fall back to 8000 locally.
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
