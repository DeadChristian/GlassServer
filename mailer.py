# mailer.py — minimal stubs so the app never crashes in prod

from typing import Optional

def send_mail(to: str, subject: str, body: str) -> None:
    # Replace with real SMTP/SendGrid later
    print("---- EMAIL ----")
    print("To:", to)
    print("Subject:", subject)
    if body:
        print(body)
    print("--------------")

async def send_license_email(
    to_email: str,
    product_name: str,
    license_key: str,
    extra_message: Optional[str] = None
):
    # Keep async signature (webhooks may await it)
    lines = [f"Thanks for purchasing {product_name}!"]
    if license_key:
        lines.append(f"Your license key: {license_key}")
    if extra_message:
        lines.append(extra_message)
    send_mail(to_email, f"{product_name} • Your License", "\n\n".join(lines))
