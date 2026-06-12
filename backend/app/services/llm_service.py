from dataclasses import dataclass

from fastapi import status
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.exceptions import AppException


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class LLMResult:
    answer: str
    model_name: str
    usage: LLMUsage


def _client() -> AsyncOpenAI:
    api_key = settings.resolved_llm_api_key
    if not api_key:
        raise AppException(
            "LLM API key is not configured",
            code=50010,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return AsyncOpenAI(api_key=api_key, base_url=settings.LLM_BASE_URL)


def _usage_from_response(completion) -> LLMUsage:
    usage = getattr(completion, "usage", None)
    if not usage:
        return LLMUsage()
    return LLMUsage(
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
    )


async def chat_completion(messages: list[dict[str, str]]) -> LLMResult:
    if not settings.LLM_MODEL:
        raise AppException(
            "LLM model is not configured",
            code=50011,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    completion = await _client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        extra_body={"enable_thinking": settings.LLM_ENABLE_THINKING},
        stream=False,
    )

    message = completion.choices[0].message
    answer = message.content or ""
    return LLMResult(
        answer=answer,
        model_name=getattr(completion, "model", None) or settings.LLM_MODEL,
        usage=_usage_from_response(completion),
    )


async def stream_chat_completion(messages: list[dict[str, str]]):
    if not settings.LLM_MODEL:
        raise AppException(
            "LLM model is not configured",
            code=50011,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    stream = await _client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        extra_body={"enable_thinking": settings.LLM_ENABLE_THINKING},
        stream=True,
    )
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)
        if content:
            yield content
