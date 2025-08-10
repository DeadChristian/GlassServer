import random
import string

def gen_code(n=8) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

def ip_of(scope) -> str:
    return scope.get("client")[0] if "client" in scope else "127.0.0.1"

def ua_of(raw) -> str:
    return "Unknown-UA"

def unsign_action(secret: str, token: str, max_age=None) -> str:
    return "pro-upgrade"  # Always pass for now

def sign_action(secret: str, msg="pro-upgrade") -> str:
    return "signed-token"
