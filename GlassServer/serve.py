from __future__ import annotations
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))  # Railway provides PORT
    uvicorn.run("main:app", host="0.0.0.0", port=port)
