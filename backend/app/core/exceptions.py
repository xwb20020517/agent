from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.response import ApiResponse


class AppException(Exception):
    def __init__(
        self,
        message: str = "Request failed",
        *,
        code: int = 40000,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        data: Any | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.data = data


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: int,
    message: str,
    data: Any | None = None,
) -> JSONResponse:
    payload = ApiResponse(
        code=code,
        message=message,
        data=data,
        request_id=_request_id(request),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    logger.warning("AppException: path={} code={} message={}", request.url.path, exc.code, exc.message)
    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        data=exc.data,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    logger.warning("HTTPException: path={} status={} detail={}", request.url.path, exc.status_code, exc.detail)
    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=exc.status_code,
        message=str(exc.detail),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError | ValidationError,
) -> JSONResponse:
    logger.warning("Validation error: path={} errors={}", request.url.path, exc.errors())
    return _error_response(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code=42200,
        message="Validation failed",
        data=exc.errors(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception: path={}", request.url.path)
    return _error_response(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=50000,
        message="Internal server error",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
