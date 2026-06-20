from dataclasses import dataclass

from loguru import logger
from redis.asyncio import Redis

from app.core.config import settings
from app.rag.utils import json_dumps, json_loads, normalize_query, sha256_text
from app.rag.vector_store import QdrantVectorStore
from app.services.embedding_service import embed_text


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    source_file: str
    section_title: str | None
    page_number_start: str | None
    page_number_end: str | None
    chunk_type: str | None
    score: float
    content: str

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "source_file": self.source_file,
            "section_title": self.section_title,
            "page_number_start": self.page_number_start,
            "page_number_end": self.page_number_end,
            "chunk_type": self.chunk_type,
            "score": self.score,
            "content": self.content,
        }


async def _get_cached_json(redis: Redis | None, key: str):
    if redis is None:
        return None
    try:
        value = await redis.get(key)
        return json_loads(value) if value else None
    except Exception as exc:
        logger.warning("RAG cache read failed for {}: {}", key, exc)
        return None


async def _set_cached_json(redis: Redis | None, key: str, value, ttl: int) -> None:
    if redis is None:
        return
    try:
        await redis.set(key, json_dumps(value), ex=ttl)
    except Exception as exc:
        logger.warning("RAG cache write failed for {}: {}", key, exc)


async def retrieve_chunks(
    query: str,
    *,
    source_file: str | None = None,
    top_k: int | None = None,
    redis: Redis | None = None,
) -> list[RetrievedChunk]:
    cleaned_query = normalize_query(query)
    effective_top_k = top_k or settings.RAG_TOP_K
    query_hash = sha256_text(cleaned_query)
    source_key = source_file or "all"
    retrieval_key = f"rag:retrieval:{query_hash}:{source_key}:{effective_top_k}"

    cached_results = await _get_cached_json(redis, retrieval_key)
    if cached_results is not None:
        return [RetrievedChunk(**item) for item in cached_results]

    embedding_key = f"rag:query_embedding:{query_hash}"
    vector = await _get_cached_json(redis, embedding_key)
    if vector is None:
        vector = await embed_text(cleaned_query)
        await _set_cached_json(redis, embedding_key, vector, settings.RAG_QUERY_EMBEDDING_CACHE_TTL)

    # 最普通的向量检索方式
    results = await QdrantVectorStore().search(
        vector,
        top_k=effective_top_k,
        source_file=source_file,
        score_threshold=settings.RAG_SCORE_THRESHOLD,
    )
    chunks = [
        RetrievedChunk(
            chunk_id=str(item.payload.get("chunk_id") or item.id),
            source_file=str(item.payload.get("source_file") or ""),
            section_title=item.payload.get("section_title"),
            page_number_start=item.payload.get("page_number_start"),
            page_number_end=item.payload.get("page_number_end"),
            chunk_type=item.payload.get("chunk_type"),
            score=item.score,
            content=str(item.payload.get("content") or ""),
        )
        for item in results
        if item.payload.get("content")
    ]
    await _set_cached_json(
        redis,
        retrieval_key,
        [chunk.to_dict() for chunk in chunks],
        settings.RAG_RETRIEVAL_CACHE_TTL,
    )
    logger.info(
        "RAG retrieval query_hash={} source_file={} top_k={} hits={}",
        query_hash,
        source_file,
        effective_top_k,
        [chunk.chunk_id for chunk in chunks],
    )
    return chunks
