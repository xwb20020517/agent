from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.llm_call import LLMCall
from app.models.message import Message


def _active_owned_query(user_id: int) -> Select[tuple[Conversation]]:
    return select(Conversation).where(
        Conversation.user_id == user_id,
        Conversation.is_deleted.is_(False),
    )


async def create_conversation(
    session: AsyncSession,
    *,
    user_id: int,
    title: str,
    model_name: str | None = None,
    system_prompt: str | None = None,
) -> Conversation:
    conversation = Conversation(
        user_id=user_id,
        title=title,
        model_name=model_name,
        system_prompt=system_prompt,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def list_conversations(session: AsyncSession, *, user_id: int) -> list[Conversation]:
    result = await session.execute(
        _active_owned_query(user_id).order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )
    return list(result.scalars().all())


async def get_conversation(
    session: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
) -> Conversation | None:
    result = await session.execute(
        _active_owned_query(user_id).where(Conversation.id == conversation_id)
    )
    return result.scalar_one_or_none()


async def rename_conversation(
    session: AsyncSession,
    *,
    conversation: Conversation,
    title: str,
) -> Conversation:
    conversation.title = title
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def hard_delete_owned_conversation(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
) -> dict[str, int]:
    from loguru import logger

    logger.info(
        "hard_delete_owned_conversation START: user_id={} conversation_id={}",
        user_id,
        conversation_id,
    )

    conversation_result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if conversation is None:
        logger.warning(
            "hard_delete_owned_conversation: conversation not found user_id={} conversation_id={}",
            user_id,
            conversation_id,
        )
        return {"conversations": 0, "messages": 0, "llm_calls": 0}

    logger.info(
        "hard_delete_owned_conversation: found conversation id={} title={}",
        conversation.id,
        conversation.title,
    )

    llm_result = await session.execute(
        delete(LLMCall).where(LLMCall.conversation_id == conversation_id)
    )
    logger.info("hard_delete: llm_calls deleted rowcount={}", llm_result.rowcount)

    message_result = await session.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )
    logger.info("hard_delete: messages deleted rowcount={}", message_result.rowcount)

    conversation_result = await session.execute(
        delete(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    logger.info("hard_delete: conversations deleted rowcount={}", conversation_result.rowcount)

    await session.commit()
    logger.info(
        "hard_delete_owned_conversation COMMITTED: conversation_id={}",
        conversation_id,
    )

    return {
        "conversations": conversation_result.rowcount or 0,
        "messages": message_result.rowcount or 0,
        "llm_calls": llm_result.rowcount or 0,
    }


async def touch_conversation(
    session: AsyncSession,
    *,
    conversation_id: int,
    model_name: str | None = None,
) -> None:
    values = {"updated_at": func.now()}
    if model_name:
        values["model_name"] = model_name
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(**values)
    )
