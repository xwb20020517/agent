from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from app.core.config import settings
from app.db.redis import ping_redis
from app.db.session import ping_mysql
from app.schemas.response import ApiResponse, success


router = APIRouter(tags=["health"])


async def _probe(name: str, probe: Any) -> dict[str, str]:
    try:
        await probe()
        return {"name": name, "status": "ok"}
    except Exception as exc:
        logger.warning("{} health check failed: {}", name, exc)
        return {"name": name, "status": "error", "message": str(exc)}


@router.get("/health", response_model=ApiResponse[dict[str, Any]])
async def health_check(request: Request) -> ApiResponse[dict[str, Any]]:
    services = [
        await _probe("mysql", ping_mysql),
        await _probe("redis", ping_redis),
    ]
    overall = "ok" if all(item["status"] == "ok" for item in services) else "degraded"
    return success(
        {
            "app": settings.APP_NAME,
            "env": settings.APP_ENV,
            "status": overall,
            "services": services,
        },
        request_id=getattr(request.state, "request_id", None),
    )
