from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()


def create_token(
    *,
    subject: UUID,
    token_type: str,
    role: str,
    gym_id: UUID | None,
    expires_delta: timedelta,
    permissions: list[str] | None = None,
    extra_claims: dict | None = None,
) -> str:
    expires_at = datetime.now(UTC) + expires_delta
    user_id = str(subject)
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "type": token_type,
        "role": role,
        "gym_id": str(gym_id) if gym_id else None,
        "permissions": permissions or [],
        "exp": expires_at,
        "iat": datetime.now(UTC),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": str(uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        ) from exc

    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )
    return payload
