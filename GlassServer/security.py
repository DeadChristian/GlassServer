from fastapi import HTTPException, Header

# Dummy admin check
def require_admin(x_admin_token: str = Header(None)):
    if x_admin_token != "my-secret-admin-token":
        raise HTTPException(status_code=401, detail="Unauthorized")


