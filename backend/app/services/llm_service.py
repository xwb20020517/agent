from fastapi import status
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.exceptions import AppException


def _client() -> AsyncOpenAI:
    api_key = settings.resolved_llm_api_key
    if not api_key:
        raise AppException(
            "LLM API key is not configured",
            code=50010,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return AsyncOpenAI(api_key=api_key, base_url=settings.LLM_BASE_URL)


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


async def chat_completion(messages: list[dict[str, str]]) -> str:
    if not settings.LLM_MODEL:
        raise AppException(
            "LLM model is not configured",
            code=50011,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    response = await _client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        extra_body={"enable_thinking": False},
        stream=False,
    )
    if not response.choices:
        return ""
    content = response.choices[0].message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item) for item in content)
    return ""
