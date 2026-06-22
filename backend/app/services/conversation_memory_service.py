from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.conversation_memory import ConversationMemory
from app.models.message import Message
from app.services.llm_service import chat_completion


SUMMARY_SYSTEM_PROMPT = """你是车辆用户手册问答系统的对话历史压缩助手。

任务：把旧摘要和新增对话压缩成一个新的历史摘要，供下一轮查询改写理解上下文。

要求：
1. 只保留和车辆功能、故障现象、用户意图、已讨论主题、指代对象有关的信息。
2. 不要把助手回答中的未证实内容当成事实；优先记录用户关注点和已检索到的手册主题。
3. 不要编造车型、功能、页码、故障原因或解决方法。
4. 摘要要简洁，使用中文，最多 1200 字。
5. 只输出摘要正文，不要输出 JSON 或额外解释。
"""


async def get_conversation_memory(
    session: AsyncSession,
    *,
    conversation_id: int,
) -> ConversationMemory | None:
    result = await session.execute(
        select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id)
    )
    return result.scalar_one_or_none()


async def get_recent_history_for_rewrite(
    session: AsyncSession,
    *,
    conversation_id: int,
    before_message_id: int,
) -> tuple[str | None, list[dict[str, str]]]:
    memory = await get_conversation_memory(session, conversation_id=conversation_id)
    recent_limit = max(1, settings.RAG_HISTORY_RECENT_ROUNDS) * 2
    result = await session.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.id < before_message_id,
            Message.status == "success",
            Message.role.in_(["user", "assistant"]),
        )
        .order_by(Message.id.desc())
        .limit(recent_limit)
    )
    messages = list(reversed(result.scalars().all()))
    return (
        memory.summary if memory and memory.summary else None,
        [{"role": message.role, "content": message.content} for message in messages],
    )


async def maybe_refresh_conversation_summary(
    session: AsyncSession,
    *,
    conversation_id: int,
) -> None:
    interval = max(1, settings.RAG_HISTORY_SUMMARY_ROUND_INTERVAL)
    user_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role == "user",
                    Message.status == "success",
                )
            )
        ).scalar_one()
        or 0
    )
    if user_count == 0 or user_count % interval != 0:
        return

    memory = await get_conversation_memory(session, conversation_id=conversation_id)
    summarized_rounds = memory.summarized_rounds if memory else 0
    if summarized_rounds >= user_count:
        return

    after_message_id = memory.summarized_until_message_id if memory else None
    filters = [
        Message.conversation_id == conversation_id,
        Message.status == "success",
        Message.role.in_(["user", "assistant"]),
    ]
    if after_message_id:
        filters.append(Message.id > after_message_id)

    result = await session.execute(select(Message).where(*filters).order_by(Message.id.asc()))
    messages = list(result.scalars().all())
    if not messages:
        return

    try:
        summary = await _summarize_history(
            previous_summary=memory.summary if memory else None,
            messages=messages,
        )
    except Exception:
        logger.exception("Conversation summary refresh failed conversation_id={}", conversation_id)
        return

    if memory is None:
        memory = ConversationMemory(conversation_id=conversation_id)
        session.add(memory)
        await session.flush()

    memory.summary = summary[: settings.RAG_HISTORY_SUMMARY_MAX_CHARS]
    memory.summarized_until_message_id = messages[-1].id
    memory.summarized_rounds = user_count
    logger.info(
        "Conversation summary refreshed conversation_id={} summarized_rounds={} until_message_id={}",
        conversation_id,
        user_count,
        messages[-1].id,
    )


async def _summarize_history(
    *,
    previous_summary: str | None,
    messages: list[Message],
) -> str:
    transcript = "\n".join(
        f"{'用户' if message.role == 'user' else '助手'}：{message.content}"
        for message in messages
    )
    prompt = f"""旧历史摘要：
{previous_summary or "无"}

新增对话：
{transcript}

请生成新的历史摘要："""
    summary = await chat_completion(
        [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
    )
    return summary.strip()
