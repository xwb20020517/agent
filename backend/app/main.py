import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn

# 确保 backend 目录在 sys.path 中，以便直接运行 `python app/main.py` 时也能正常导入
_this_file = Path(__file__).resolve()
_backend_dir = _this_file.parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from fastapi import FastAPI, Request
from loguru import logger
from starlette.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestIdMiddleware
from app.db.init_db import init_db
from app.db.redis import close_redis, init_redis, ping_redis
from app.db.session import close_mysql, ping_mysql
from app.schemas.response import ApiResponse, success


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    logger.info("Starting {}", settings.APP_NAME)

    await init_redis()
    if settings.STRICT_STARTUP_CHECK:
        await ping_mysql()
        await ping_redis()
        if settings.AUTO_CREATE_TABLES:
            await init_db()
        logger.info("External service startup checks passed")
    else:
        for name, probe in (("mysql", ping_mysql), ("redis", ping_redis)):
            try:
                await probe()
                logger.info("{} connection check passed", name)
            except Exception as exc:
                logger.warning("{} connection check failed: {}", name, exc)
        if settings.AUTO_CREATE_TABLES:
            try:
                await init_db()
            except Exception as exc:
                logger.warning("Database table initialization failed: {}", exc)

    yield

    logger.info("Stopping {}", settings.APP_NAME)
    await close_redis()
    await close_mysql()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()


@app.get("/", response_model=ApiResponse[dict[str, str]], tags=["root"])
async def root(request: Request) -> ApiResponse[dict[str, str]]:
    return success(
        {"name": settings.APP_NAME, "docs": "/docs", "health": "/health"},
        request_id=getattr(request.state, "request_id", None),
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=settings.DEBUG,
        log_level="info",
    )
