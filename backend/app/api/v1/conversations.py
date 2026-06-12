from fastapi import APIRouter, Depends, Request, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationDetail, ConversationRead, ConversationUpdate
from app.schemas.response import ApiResponse, success
from app.services.conversation_service import (
    create_user_conversation,
    delete_user_conversation,
    get_user_conversation_detail,
    list_user_conversations,
    rename_user_conversation,
)


router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "",
    response_model=ApiResponse[ConversationRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation_endpoint(
    payload: ConversationCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ConversationRead]:
    conversation = await create_user_conversation(
        session,
        user_id=current_user.id,
        payload=payload,
    )
    return success(
        ConversationRead.model_validate(conversation),
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("", response_model=ApiResponse[list[ConversationRead]])
async def list_conversations_endpoint(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[list[ConversationRead]]:
    conversations = await list_user_conversations(session, user_id=current_user.id)
    return success(
        [ConversationRead.model_validate(item) for item in conversations],
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/{conversation_id}", response_model=ApiResponse[ConversationDetail])
async def get_conversation_endpoint(
    conversation_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ConversationDetail]:
    detail = await get_user_conversation_detail(
        session,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )
    return success(detail, request_id=getattr(request.state, "request_id", None))


@router.patch("/{conversation_id}", response_model=ApiResponse[ConversationRead])
async def rename_conversation_endpoint(
    conversation_id: int,
    payload: ConversationUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ConversationRead]:
    conversation = await rename_user_conversation(
        session,
        user_id=current_user.id,
        conversation_id=conversation_id,
        payload=payload,
    )
    return success(
        ConversationRead.model_validate(conversation),
        request_id=getattr(request.state, "request_id", None),
    )


@router.delete("/{conversation_id}", response_model=ApiResponse[dict[str, bool | int]])
async def delete_conversation_endpoint(
    conversation_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[dict[str, bool | int]]:
    logger.info(
        "DELETE /conversations/{} called: user_id={}",
        conversation_id,
        current_user.id,
    )
    deleted_counts = await delete_user_conversation(
        session,
        user_id=current_user.id,
        conversation_id=conversation_id,
    )
    logger.info(
        "DELETE /conversations/{} completed: counts={}",
        conversation_id,
        deleted_counts,
    )
    return success(
        {"deleted": True, **deleted_counts},
        request_id=getattr(request.state, "request_id", None),
    )
