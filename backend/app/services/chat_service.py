from collections.abc import AsyncGenerator
from time import perf_counter
from uuid import uuid4

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud.conversation import touch_conversation
from app.crud.llm_call import create_llm_call
from app.crud.message import create_message
from app.crud.rag_query_log import create_rag_query_log
from app.rag.prompt_builder import NO_ANSWER, build_rag_prompt, build_sources
from app.rag.retriever import expand_chunk_contexts, retrieve_rewritten_query_seeds
from app.rag.retriever_types import RetrievedChunk
from app.schemas.chat import ChatRequest
from app.services.conversation_memory_service import (
    get_recent_history_for_rewrite,
    maybe_refresh_conversation_summary,
)
from app.services.conversation_service import get_user_conversation
from app.services.llm_service import stream_chat_completion
from app.services.query_rewrite_service import rewrite_query
from app.services.sse import sse_event


async def _retrieve_chunks_with_query_rewrite(
    session: AsyncSession,
    redis: Redis,
    *,
    conversation_id: int,
    current_user_message_id: int,
    original_query: str,
    source_file: str | None,
    top_k: int,
) -> tuple[list[RetrievedChunk], str]:
    history_summary, recent_history = await get_recent_history_for_rewrite(
        session,
        conversation_id=conversation_id,
        before_message_id=current_user_message_id,
    )
    rewrite = await rewrite_query(
        original_query,
        history=recent_history,
        history_summary=history_summary,
    )
    seeds = await retrieve_rewritten_query_seeds(
        rewrite,
        source_file=source_file,
        top_k=top_k,
        redis=redis,
    )
    chunks = expand_chunk_contexts(seeds)
    logger.info(
        "Query rewrite retrieval original_query={} keywords={} seed_hits={} expanded_hits={}",
        original_query,
        rewrite.keywords,
        [chunk.chunk_id for chunk in seeds],
        [chunk.chunk_id for chunk in chunks],
    )
    return chunks, rewrite.rewritten_query


async def stream_chat_message(
    session: AsyncSession,
    redis: Redis,
    *,
    user_id: int,
    payload: ChatRequest,
) -> AsyncGenerator[str, None]:
    conversation = await get_user_conversation(
        session,
        user_id=user_id,
        conversation_id=payload.conversation_id,
    )

    user_message = await create_message(
        session,
        conversation_id=conversation.id,
        user_id=user_id,
        role="user",
        content=payload.message,
        status="success",
    )
    await session.commit()
    await session.refresh(user_message)

    request_id = uuid4().hex
    started_at = perf_counter()
    model_name = settings.LLM_MODEL or ""
    effective_top_k = payload.top_k or settings.RAG_TOP_K

    yield sse_event("start", {
        "conversation_id": conversation.id,
        "user_message_id": user_message.id,
        "request_id": request_id,
    })

    try:
        chunks, rewritten_query = await _retrieve_chunks_with_query_rewrite(
            session,
            redis,
            conversation_id=conversation.id,
            current_user_message_id=user_message.id,
            original_query=payload.message,
            source_file=payload.source_file,
            top_k=effective_top_k,
        )
    except Exception as exc:
        logger.exception("RAG retrieval failed in streaming chat")
        yield sse_event("error", {"message": str(exc)})
        return

    sources = build_sources(chunks)

    if not chunks:
        full_answer = NO_ANSWER
        yield sse_event("delta", {"content": full_answer})
        latency_ms = int((perf_counter() - started_at) * 1000)

        assistant_message = await create_message(
            session,
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content=full_answer,
            status="success",
            latency_ms=latency_ms,
            commit=False,
        )
        await session.flush()
        await create_rag_query_log(
            session,
            user_id=user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            query=payload.message,
            answer=full_answer,
            source_file_filter=payload.source_file,
            retrieved_chunks_json=[],
            top_k=effective_top_k,
            latency_ms=latency_ms,
            success=True,
            commit=False,
        )
        await touch_conversation(session, conversation_id=conversation.id, model_name=model_name)
        await maybe_refresh_conversation_summary(session, conversation_id=conversation.id)
        await session.commit()
        await session.refresh(assistant_message)

        yield sse_event("done", {
            "conversation_id": conversation.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
            "answer": full_answer,
            "sources": [s.model_dump(mode="json") for s in sources],
            "latency_ms": latency_ms,
        })
        return

    try:
        full_answer = ""
        messages = build_rag_prompt(payload.message, chunks, rewritten_query=rewritten_query)

        async for token in stream_chat_completion(messages):
            full_answer += token
            yield sse_event("delta", {"content": token})

        latency_ms = int((perf_counter() - started_at) * 1000)

        assistant_message = await create_message(
            session,
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content=full_answer,
            status="success",
            latency_ms=latency_ms,
            commit=False,
        )
        await session.flush()

        await create_llm_call(
            session,
            user_id=user_id,
            conversation_id=conversation.id,
            request_id=request_id,
            provider=settings.LLM_PROVIDER,
            model_name=model_name,
            latency_ms=latency_ms,
            success=True,
            commit=False,
        )
        await create_rag_query_log(
            session,
            user_id=user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            query=payload.message,
            answer=full_answer,
            source_file_filter=payload.source_file,
            retrieved_chunks_json=[chunk.to_dict() for chunk in chunks],
            top_k=effective_top_k,
            latency_ms=latency_ms,
            success=True,
            commit=False,
        )
        await touch_conversation(session, conversation_id=conversation.id, model_name=model_name)
        await maybe_refresh_conversation_summary(session, conversation_id=conversation.id)
        await session.commit()
        await session.refresh(assistant_message)

        logger.info(
            "Streaming RAG chat succeeded: user_id={} conversation_id={} request_id={} latency_ms={}",
            user_id,
            conversation.id,
            request_id,
            latency_ms,
        )
        yield sse_event("done", {
            "conversation_id": conversation.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
            "answer": full_answer,
            "sources": [s.model_dump(mode="json") for s in sources],
            "latency_ms": latency_ms,
        })
    except Exception as exc:
        await session.rollback()
        latency_ms = int((perf_counter() - started_at) * 1000)
        error_message = str(exc)

        try:
            assistant_message = await create_message(
                session,
                conversation_id=conversation.id,
                user_id=user_id,
                role="assistant",
                content=NO_ANSWER,
                status="failed",
                latency_ms=latency_ms,
                commit=False,
            )
            await session.flush()
            await create_llm_call(
                session,
                user_id=user_id,
                conversation_id=conversation.id,
                request_id=request_id,
                provider=settings.LLM_PROVIDER,
                model_name=model_name,
                latency_ms=latency_ms,
                success=False,
                error_message=error_message[:4000],
                commit=False,
            )
            await create_rag_query_log(
                session,
                user_id=user_id,
                conversation_id=conversation.id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                query=payload.message,
                answer=NO_ANSWER,
                source_file_filter=payload.source_file,
                retrieved_chunks_json=[],
                top_k=effective_top_k,
                latency_ms=latency_ms,
                success=False,
                error_message=error_message[:4000],
                commit=False,
            )
            await touch_conversation(session, conversation_id=conversation.id, model_name=model_name)
            await session.commit()
        except Exception:
            logger.exception("Failed to save streaming error logs")

        logger.exception(
            "Streaming RAG chat failed: user_id={} conversation_id={} request_id={}",
            user_id,
            conversation.id,
            request_id,
        )
        yield sse_event("error", {"message": error_message})
