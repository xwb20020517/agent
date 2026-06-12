from typing import Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = Field(default=0, description="业务状态码，0 表示成功")
    message: str = Field(default="success", description="响应消息")
    data: T | None = Field(default=None, description="响应数据")
    request_id: str | None = Field(default=None, description="请求 ID")


def success(
    data: T | None = None,
    message: str = "success",
    request_id: str | None = None,
) -> ApiResponse[T]:
    return ApiResponse(code=0, message=message, data=data, request_id=request_id)
