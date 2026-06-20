from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag_query_log import RAGQueryLog


async def create_rag_query_log(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: int | None,
    user_message_id: int | None,
    assistant_message_id: int | None,
    query: str,
    answer: str | None,
    source_file_filter: str | None,
    retrieved_chunks_json: list[dict[str, Any]] | None,
    top_k: int,
    latency_ms: int | None,
    success: bool,
    error_message: str | None = None,
    commit: bool = True,
) -> RAGQueryLog:
    log = RAGQueryLog(
        user_id=user_id,
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        query=query,
        answer=answer,
        source_file_filter=source_file_filter,
        retrieved_chunks_json=retrieved_chunks_json,
        top_k=top_k,
        latency_ms=latency_ms,
        success=success,
        error_message=error_message,
    )
    session.add(log)
    if commit:
        await session.commit()
        await session.refresh(log)
    return log
