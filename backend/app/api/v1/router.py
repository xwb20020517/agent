from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.health import router as health_router
from app.api.v1.users import router as users_router
from app.core.config import settings


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router, prefix=settings.API_V1_PREFIX)
api_router.include_router(chat_router, prefix=settings.API_V1_PREFIX)
api_router.include_router(conversations_router, prefix=settings.API_V1_PREFIX)
api_router.include_router(users_router, prefix=settings.API_V1_PREFIX)
