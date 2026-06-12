from fastapi import status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.crud.conversation import (
    create_conversation,
    get_conversation,
    hard_delete_owned_conversation,
    list_conversations,
    rename_conversation,
)
from app.crud.message import list_messages_by_conversation
from app.models.conversation import Conversation
from app.schemas.conversation import ConversationCreate, ConversationDetail, ConversationRead, ConversationUpdate
from app.schemas.message import MessageRead


async def create_user_conversation(
    session: AsyncSession,
    *,
    user_id: int,
    payload: ConversationCreate,
) -> Conversation:
    conversation = await create_conversation(
        session,
        user_id=user_id,
        title=payload.title,
    )
    logger.info("Conversation created: user_id={} conversation_id={}", user_id, conversation.id)
    return conversation


async def list_user_conversations(session: AsyncSession, *, user_id: int) -> list[Conversation]:
    return await list_conversations(session, user_id=user_id)


async def get_user_conversation(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
) -> Conversation:
    conversation = await get_conversation(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if not conversation:
        raise AppException(
            "Conversation not found",
            code=40401,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return conversation


async def get_user_conversation_detail(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
) -> ConversationDetail:
    conversation = await get_user_conversation(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    messages = await list_messages_by_conversation(session, conversation_id=conversation.id)
    return ConversationDetail(
        **ConversationRead.model_validate(conversation).model_dump(),
        messages=[MessageRead.model_validate(message) for message in messages],
    )


async def rename_user_conversation(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
    payload: ConversationUpdate,
) -> Conversation:
    conversation = await get_user_conversation(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    updated = await rename_conversation(session, conversation=conversation, title=payload.title)
    logger.info("Conversation renamed: user_id={} conversation_id={}", user_id, conversation_id)
    return updated


async def delete_user_conversation(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
) -> dict[str, int]:
    deleted_counts = await hard_delete_owned_conversation(
        session,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if deleted_counts["conversations"] == 0:
        raise AppException(
            "Conversation not found",
            code=40401,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    logger.info(
        "Conversation hard deleted: user_id={} conversation_id={} counts={}",
        user_id,
        conversation_id,
        deleted_counts,
    )
    return deleted_counts
