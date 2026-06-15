from fastapi import status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_ttl_seconds,
    verify_password,
)
from app.crud.user import create_user, get_user_by_id, get_user_by_username, get_user_by_username_or_email
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest, TokenResponse


async def register_user(session: AsyncSession, payload: RegisterRequest) -> User:
    existing_user = await get_user_by_username_or_email(
        session,
        username=payload.username,
        email=str(payload.email) if payload.email else None,
    )
    if existing_user:
        if existing_user.username == payload.username:
            raise AppException("Username already exists", code=40002)
        raise AppException("Email already exists", code=40003)

    user = await create_user(
        session,
        username=payload.username,
        email=str(payload.email) if payload.email else None,
        hashed_password=hash_password(payload.password),
    )
    logger.info("User registered: user_id={} username={}", user.id, user.username)
    return user


async def login_user(session: AsyncSession, redis: Redis, payload: LoginRequest) -> TokenResponse:
    user = await get_user_by_username(session, payload.username)
    if not user or not verify_password(payload.password, user.hashed_password):
        raise AppException(
            "Invalid username or password",
            code=40102,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    if not user.is_active:
        raise AppException(
            "User is disabled",
            code=40301,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    claims = {"username": user.username}
    access_token, _ = create_access_token(subject=str(user.id), extra_claims=claims)
    refresh_token, refresh_payload = create_refresh_token(subject=str(user.id), extra_claims=claims)

    refresh_key = f"auth:refresh:{user.id}:{refresh_payload['jti']}"
    await redis.setex(refresh_key, settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60, "1")

    logger.info("User logged in: user_id={} username={}", user.id, user.username)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def refresh_user_tokens(
    session: AsyncSession,
    redis: Redis,
    payload: RefreshTokenRequest,
) -> TokenResponse:
    refresh_payload = decode_token(payload.refresh_token)
    if refresh_payload.get("type") != "refresh":
        raise AppException(
            "Refresh token required",
            code=40106,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user_id = refresh_payload.get("sub")
    jti = refresh_payload.get("jti")
    if not user_id or not jti:
        raise AppException(
            "Invalid token",
            code=40101,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    refresh_key = f"auth:refresh:{user_id}:{jti}"
    if not await redis.exists(refresh_key):
        raise AppException(
            "Refresh token has been revoked",
            code=40107,
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

    claims = {"username": user.username}
    access_token, _ = create_access_token(subject=str(user.id), extra_claims=claims)
    refresh_token, new_refresh_payload = create_refresh_token(subject=str(user.id), extra_claims=claims)

    await redis.delete(refresh_key)
    new_refresh_key = f"auth:refresh:{user.id}:{new_refresh_payload['jti']}"
    await redis.setex(new_refresh_key, settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60, "1")

    logger.info("User token refreshed: user_id={} username={}", user.id, user.username)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def logout_user(redis: Redis, token_payload: dict) -> None:
    jti = token_payload.get("jti")
    user_id = token_payload.get("sub")
    if not jti:
        raise AppException(
            "Invalid token",
            code=40101,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    ttl = token_ttl_seconds(token_payload)
    if ttl > 0:
        await redis.setex(f"auth:blacklist:{jti}", ttl, "1")

    logger.info("User logged out: user_id={} jti={}", user_id, jti)
