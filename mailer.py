# mailer.py — prints to console (replace later with SMTP)
from typing import Optional
async def send_license_email(to_email: str, product_name: str, license_key: str, extra_message: Optional[str] = None):
    print("---- EMAIL ----")
    print("To:", to_email)
    print("Subject:", f"{product_name} • Your License")
    if license_key:
        print("License Key:", license_key)
    if extra_message:
        print(extra_message)
    print("--------------")
