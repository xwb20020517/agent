from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

import bcrypt
import jwt
from fastapi import status
from jwt import InvalidTokenError

from app.core.config import settings
from app.core.exceptions import AppException


TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        raise AppException("Password is too long", code=40001)
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        return False
    return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))


def create_token(
    *,
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, payload


def create_access_token(subject: str, extra_claims: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    return create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims=extra_claims,
    )


def create_refresh_token(subject: str, extra_claims: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    return create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        extra_claims=extra_claims,
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except InvalidTokenError as exc:
        raise AppException(
            "Invalid or expired token",
            code=40101,
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc


def token_ttl_seconds(payload: dict[str, Any]) -> int:
    exp = int(payload.get("exp", 0))
    now = int(datetime.now(UTC).timestamp())
    return max(exp - now, 0)
