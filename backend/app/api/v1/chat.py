from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.deps import get_current_user, get_redis_client
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.response import ApiResponse, success
from app.services.chat_service import send_chat_message, stream_chat_message


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ApiResponse[ChatResponse])
async def chat(
    payload: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ChatResponse]:
    result = await send_chat_message(
        session,
        user_id=current_user.id,
        payload=payload,
    )
    return success(result, request_id=getattr(request.state, "request_id", None))


@router.post("/stream")
async def chat_stream(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis_client),
) -> StreamingResponse:
    event_stream = await stream_chat_message(
        session,
        redis,
        user_id=current_user.id,
        payload=payload,
    )
    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
