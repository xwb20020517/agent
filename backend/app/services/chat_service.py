from collections.abc import AsyncGenerator
from time import perf_counter
from uuid import uuid4

from fastapi import status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException
from app.crud.conversation import touch_conversation
from app.crud.llm_call import create_llm_call
from app.crud.message import create_message, list_messages_by_conversation
from app.db.session import AsyncSessionLocal
from app.models.message import Message
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.conversation_service import get_user_conversation
from app.services.llm_service import chat_completion, stream_chat_completion
from app.services.sse import sse_event


def _history_to_llm_messages(messages: list[Message], new_message: str) -> list[dict[str, str]]:
    llm_messages = [
        {"role": item.role, "content": item.content}
        for item in messages
        if item.role in {"system", "user", "assistant"} and item.status == "success"
    ]
    llm_messages.append({"role": "user", "content": new_message})
    return llm_messages


async def send_chat_message(
    session: AsyncSession,
    *,
    user_id: int,
    payload: ChatRequest,
) -> ChatResponse:
    if payload.stream:
        raise AppException(
            "Streaming chat is not implemented in this endpoint",
            code=40010,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    conversation = await get_user_conversation(
        session,
        user_id=user_id,
        conversation_id=payload.conversation_id,
    )

    history = await list_messages_by_conversation(session, conversation_id=conversation.id)
    llm_messages = _history_to_llm_messages(history, payload.message)

    user_message = await create_message(
        session,
        conversation_id=conversation.id,
        user_id=user_id,
        role="user",
        content=payload.message,
        status="success",
    )

    request_id = uuid4().hex
    started_at = perf_counter()
    model_name = settings.LLM_MODEL or ""

    try:
        llm_result = await chat_completion(llm_messages)
        latency_ms = int((perf_counter() - started_at) * 1000)
        model_name = llm_result.model_name

        assistant_message = await create_message(
            session,
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content=llm_result.answer,
            status="success",
            token_count=llm_result.usage.completion_tokens,
            latency_ms=latency_ms,
            commit=False,
        )
        await create_llm_call(
            session,
            user_id=user_id,
            conversation_id=conversation.id,
            request_id=request_id,
            provider=settings.LLM_PROVIDER,
            model_name=model_name,
            prompt_tokens=llm_result.usage.prompt_tokens,
            completion_tokens=llm_result.usage.completion_tokens,
            total_tokens=llm_result.usage.total_tokens,
            latency_ms=latency_ms,
            success=True,
            commit=False,
        )
        await touch_conversation(
            session,
            conversation_id=conversation.id,
            model_name=model_name,
        )
        await session.commit()
        await session.refresh(assistant_message)

        logger.info(
            "LLM call succeeded: user_id={} conversation_id={} request_id={} latency_ms={}",
            user_id,
            conversation.id,
            request_id,
            latency_ms,
        )
        return ChatResponse(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            answer=llm_result.answer,
        )
    except Exception as exc:
        await session.rollback()
        latency_ms = int((perf_counter() - started_at) * 1000)
        error_message = str(exc)
        assistant_message = await create_message(
            session,
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content="",
            status="failed",
            latency_ms=latency_ms,
            commit=False,
        )
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
        await touch_conversation(
            session,
            conversation_id=conversation.id,
            model_name=model_name,
        )
        await session.commit()
        await session.refresh(assistant_message)
        logger.exception(
            "LLM call failed: user_id={} conversation_id={} request_id={}",
            user_id,
            conversation.id,
            request_id,
        )

        if isinstance(exc, AppException):
            raise exc
        raise AppException(
            "LLM call failed",
            code=50200,
            status_code=status.HTTP_502_BAD_GATEWAY,
            data={"assistant_message_id": assistant_message.id},
        ) from exc


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

    # Extract primitives BEFORE the session closes — the async generator
    # runs later and ORM attributes will be expired by then.
    conversation_id = conversation.id

    lock_key = f"chat:streaming:{conversation_id}"
    lock_acquired = await redis.set(lock_key, "1", ex=120, nx=True)
    if not lock_acquired:
        raise AppException(
            "Conversation is already streaming",
            code=40901,
            status_code=status.HTTP_409_CONFLICT,
        )

    history = await list_messages_by_conversation(session, conversation_id=conversation_id)
    llm_messages = _history_to_llm_messages(history, payload.message)

    user_message = await create_message(
        session,
        conversation_id=conversation_id,
        user_id=user_id,
        role="user",
        content=payload.message,
        status="success",
    )
    user_message_id = user_message.id

    request_id = uuid4().hex
    started_at = perf_counter()
    model_name = settings.LLM_MODEL or ""
    chunks: list[str] = []

    async def event_generator() -> AsyncGenerator[str, None]:
        nonlocal chunks
        yield sse_event(
            "start",
            {
                "conversation_id": conversation_id,
                "user_message_id": user_message_id,
                "request_id": request_id,
            },
        )

        try:
            async for content in stream_chat_completion(llm_messages):
                chunks.append(content)
                yield sse_event("delta", {"content": content})

            answer = "".join(chunks)
            latency_ms = int((perf_counter() - started_at) * 1000)
            async with AsyncSessionLocal() as save_session:
                assistant_message = await create_message(
                    save_session,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role="assistant",
                    content=answer,
                    status="success",
                    latency_ms=latency_ms,
                    commit=False,
                )
                await create_llm_call(
                    save_session,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    request_id=request_id,
                    provider=settings.LLM_PROVIDER,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    success=True,
                    commit=False,
                )
                await touch_conversation(
                    save_session,
                    conversation_id=conversation_id,
                    model_name=model_name,
                )
                await save_session.commit()
                await save_session.refresh(assistant_message)

            logger.info(
                "Streaming LLM call succeeded: user_id={} conversation_id={} request_id={} latency_ms={}",
                user_id,
                conversation_id,
                request_id,
                latency_ms,
            )
            yield sse_event(
                "done",
                {
                    "conversation_id": conversation_id,
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message.id,
                    "answer": answer,
                },
            )
        except Exception as exc:
            await session.rollback()
            latency_ms = int((perf_counter() - started_at) * 1000)
            error_message = str(exc)
            async with AsyncSessionLocal() as save_session:
                assistant_message = await create_message(
                    save_session,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role="assistant",
                    content="".join(chunks),
                    status="failed",
                    latency_ms=latency_ms,
                    commit=False,
                )
                await create_llm_call(
                    save_session,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    request_id=request_id,
                    provider=settings.LLM_PROVIDER,
                    model_name=model_name,
                    latency_ms=latency_ms,
                    success=False,
                    error_message=error_message[:4000],
                    commit=False,
                )
                await touch_conversation(
                    save_session,
                    conversation_id=conversation_id,
                    model_name=model_name,
                )
                await save_session.commit()
                await save_session.refresh(assistant_message)

            logger.exception(
                "Streaming LLM call failed: user_id={} conversation_id={} request_id={}",
                user_id,
                conversation_id,
                request_id,
            )
            yield sse_event(
                "error",
                {
                    "message": "LLM stream failed",
                    "assistant_message_id": assistant_message.id,
                },
            )
        finally:
            await redis.delete(lock_key)

    return event_generator()
