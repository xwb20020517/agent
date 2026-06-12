from dataclasses import dataclass
from typing import Any

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.security import decode_token
from app.crud.user import get_user_by_id
from app.db.redis import get_redis
from app.db.session import get_db_session
from app.models.user import User


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: User
    token: str
    payload: dict[str, Any]


async def get_redis_client() -> Redis:
    return get_redis()


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppException(
            "Authentication required",
            code=40100,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = credentials.credentials
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise AppException(
            "Access token required",
            code=40103,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    jti = payload.get("jti")
    if jti and await redis.exists(f"auth:blacklist:{jti}"):
        raise AppException(
            "Token has been revoked",
            code=40104,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user_id = payload.get("sub")
    if not user_id:
        raise AppException(
            "Invalid token",
            code=40101,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        parsed_user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise AppException(
            "Invalid token",
            code=40101,
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc

    user = await get_user_by_id(session, parsed_user_id)
    if not user:
        raise AppException(
            "User not found",
            code=40105,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    if not user.is_active:
        raise AppException(
            "User is disabled",
            code=40301,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    return AuthContext(user=user, token=token, payload=payload)


async def get_current_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user
