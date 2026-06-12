from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_call import LLMCall


async def create_llm_call(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
    request_id: str,
    provider: str,
    model_name: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    latency_ms: int | None = None,
    success: bool = True,
    error_message: str | None = None,
    commit: bool = True,
) -> LLMCall:
    call = LLMCall(
        user_id=user_id,
        conversation_id=conversation_id,
        request_id=request_id,
        provider=provider,
        model_name=model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        success=success,
        error_message=error_message,
    )
    session.add(call)
    if commit:
        await session.commit()
        await session.refresh(call)
    return call
