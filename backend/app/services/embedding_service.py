from fastapi import status
from loguru import logger
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.exceptions import AppException


def _client() -> AsyncOpenAI:
    if settings.EMBEDDING_PROVIDER != "openai_compatible":
        raise AppException(
            "Unsupported embedding provider",
            code=50020,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if not settings.EMBEDDING_API_KEY:
        raise AppException(
            "Embedding API key is not configured",
            code=50021,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return AsyncOpenAI(api_key=settings.EMBEDDING_API_KEY, base_url=settings.EMBEDDING_BASE_URL)


def _validate_vector(vector: list[float]) -> list[float]:
    if not vector:
        raise AppException(
            "Embedding service returned an empty vector",
            code=50210,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    if len(vector) != settings.EMBEDDING_DIM:
        raise AppException(
            "Embedding dimension mismatch",
            code=50211,
            status_code=status.HTTP_502_BAD_GATEWAY,
            data={"expected": settings.EMBEDDING_DIM, "actual": len(vector)},
        )
    return vector


async def embed_text(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not settings.EMBEDDING_MODEL:
        raise AppException(
            "Embedding model is not configured",
            code=50022,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    cleaned = [text.strip() for text in texts]
    if not cleaned or any(not text for text in cleaned):
        raise AppException(
            "Embedding input cannot be empty",
            code=40020,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        response = await _client().embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=cleaned,
        )
    except Exception as exc:
        logger.exception("Embedding request failed")
        raise AppException(
            "Embedding service call failed",
            code=50212,
            status_code=status.HTTP_502_BAD_GATEWAY,
        ) from exc

    data = sorted(response.data, key=lambda item: item.index)
    vectors = [_validate_vector(list(item.embedding)) for item in data]
    if len(vectors) != len(cleaned):
        raise AppException(
            "Embedding service returned an unexpected number of vectors",
            code=50213,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    return vectors
