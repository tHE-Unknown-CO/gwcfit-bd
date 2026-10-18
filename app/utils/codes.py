import re
import secrets


def slug_prefix(value: str, length: int = 4) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return (normalized[:length] or "GYM").ljust(length, "X")


def generate_gym_code(name: str) -> str:
    return f"{slug_prefix(name)}-{secrets.token_hex(3).upper()}"


def generate_token() -> str:
    return secrets.token_urlsafe(32)
