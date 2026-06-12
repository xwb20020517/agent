from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message


async def list_messages_by_conversation(
    session: AsyncSession,
    *,
    conversation_id: int,
) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return list(result.scalars().all())


async def create_message(
    session: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    role: str,
    content: str,
    status: str = "success",
    token_count: int | None = None,
    latency_ms: int | None = None,
    commit: bool = True,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        user_id=user_id,
        role=role,
        content=content,
        status=status,
        token_count=token_count,
        latency_ms=latency_ms,
    )
    session.add(message)
    if commit:
        await session.commit()
        await session.refresh(message)
    return message
