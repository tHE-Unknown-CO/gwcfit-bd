import hashlib
import hmac

import bcrypt

from app.core.config import get_settings

MAX_BCRYPT_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > MAX_BCRYPT_PASSWORD_BYTES:
        raise ValueError(f"Password must be {MAX_BCRYPT_PASSWORD_BYTES} bytes or fewer.")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > MAX_BCRYPT_PASSWORD_BYTES:
        return False

    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        return False


def hash_token(token: str) -> str:
    secret = get_settings().jwt_secret_key.encode("utf-8")
    digest = hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256${digest}"


def verify_token(token: str, hashed_token: str) -> bool:
    return hmac.compare_digest(hash_token(token), hashed_token)
