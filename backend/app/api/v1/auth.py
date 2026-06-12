from fastapi import APIRouter, Depends, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_redis_client
from app.db.session import get_db_session
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.response import ApiResponse, success
from app.schemas.user import UserRead
from app.services.auth_service import login_user, logout_user, register_user


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ApiResponse[UserRead],
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[UserRead]:
    user = await register_user(session, payload)
    return success(
        UserRead.model_validate(user),
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
) -> ApiResponse[TokenResponse]:
    tokens = await login_user(session, redis, payload)
    return success(tokens, request_id=getattr(request.state, "request_id", None))


@router.post("/logout", response_model=ApiResponse[dict[str, bool]])
async def logout(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
    redis: Redis = Depends(get_redis_client),
) -> ApiResponse[dict[str, bool]]:
    await logout_user(redis, context.payload)
    return success(
        {"logged_out": True},
        request_id=getattr(request.state, "request_id", None),
    )
