from loguru import logger
from redis.asyncio import Redis

from app.core.config import settings
from app.rag.retriever_types import RetrievedChunk
from app.rag.sparse_index import get_sparse_index
from app.rag.utils import json_dumps, json_loads, normalize_query, sha256_text
from app.rag.vector_store import QdrantVectorStore
from app.services.embedding_service import embed_text


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


def _chunk_from_vector_result(item) -> RetrievedChunk | None:
    if not item.payload.get("content"):
        return None
    return RetrievedChunk(
        chunk_id=str(item.payload.get("chunk_id") or item.id),
        source_file=str(item.payload.get("source_file") or ""),
        section_title=item.payload.get("section_title"),
        page_number_start=item.payload.get("page_number_start"),
        page_number_end=item.payload.get("page_number_end"),
        chunk_type=item.payload.get("chunk_type"),
        score=item.score,
        content=str(item.payload.get("content") or ""),
    )


async def _vector_recall(
    query: str,
    *,
    source_file: str | None,
    recall_k: int,
    redis: Redis | None,
) -> list[RetrievedChunk]:
    query_hash = sha256_text(query)
    embedding_key = f"rag:query_embedding:{query_hash}"
    vector = await _get_cached_json(redis, embedding_key)
    if vector is None:
        vector = await embed_text(query)
        await _set_cached_json(redis, embedding_key, vector, settings.RAG_QUERY_EMBEDDING_CACHE_TTL)

    results = await QdrantVectorStore().search(
        vector,
        top_k=recall_k,
        source_file=source_file,
        score_threshold=settings.RAG_SCORE_THRESHOLD,
    )
    chunks: list[RetrievedChunk] = []
    for item in results:
        chunk = _chunk_from_vector_result(item)
        if chunk:
            chunks.append(chunk)
    return chunks


def _sparse_recall(query: str, *, source_file: str | None, recall_k: int) -> list[RetrievedChunk]:
    return [hit.chunk for hit in get_sparse_index().search(query, top_k=recall_k, source_file=source_file)]


def _rrf_score(rank: int, *, weight: float) -> float:
    return weight / (settings.RAG_RRF_K + rank)


def _merge_with_rrf(
    *,
    vector_chunks: list[RetrievedChunk],
    sparse_chunks: list[RetrievedChunk],
) -> dict[str, tuple[RetrievedChunk, float]]:
    merged: dict[str, tuple[RetrievedChunk, float]] = {}

    for rank, chunk in enumerate(vector_chunks, start=1):
        score = _rrf_score(rank, weight=settings.RAG_VECTOR_RRF_WEIGHT)
        existing = merged.get(chunk.chunk_id)
        merged[chunk.chunk_id] = (chunk, (existing[1] if existing else 0.0) + score)

    for rank, chunk in enumerate(sparse_chunks, start=1):
        score = _rrf_score(rank, weight=settings.RAG_SPARSE_RRF_WEIGHT)
        existing = merged.get(chunk.chunk_id)
        merged[chunk.chunk_id] = (existing[0] if existing else chunk, (existing[1] if existing else 0.0) + score)

    return merged


def _rank_fused_candidates(
    candidates: dict[str, tuple[RetrievedChunk, float]],
    *,
    limit: int,
) -> list[RetrievedChunk]:
    if not candidates or limit <= 0:
        return []
    ranked: list[tuple[float, RetrievedChunk]] = []
    for chunk, fused_score in candidates.values():
        ranked.append((fused_score, RetrievedChunk(**{**chunk.to_dict(), "score": fused_score})))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in ranked[:limit]]


def _append_query_job(jobs: list[tuple[str, str]], source: str, query: str) -> None:
    query = query.strip()
    if query and query not in [item[1] for item in jobs]:
        jobs.append((source, query))


def _build_hybrid_query_jobs(rewrite) -> list[tuple[str, str]]:
    jobs: list[tuple[str, str]] = []
    _append_query_job(jobs, "original_query", rewrite.original_query)
    _append_query_job(jobs, "rewritten_query", rewrite.rewritten_query)
    for sub_query in rewrite.sub_queries[:3]:
        _append_query_job(jobs, "sub_query", sub_query)
    return jobs


def _merge_ranked_candidates(
    candidate_scores: dict[str, tuple[RetrievedChunk, float, int]],
    chunks: list[RetrievedChunk],
    *,
    source: str,
) -> None:
    weight = _source_weight(source)
    for rank, chunk in enumerate(chunks, start=1):
        score = _rrf_score(rank, weight=weight)
        existing = candidate_scores.get(chunk.chunk_id)
        if existing is None:
            candidate_scores[chunk.chunk_id] = (chunk, score, len(candidate_scores))
            continue
        existing_chunk, existing_score, first_seen = existing
        best_chunk = chunk if chunk.score > existing_chunk.score else existing_chunk
        candidate_scores[chunk.chunk_id] = (best_chunk, existing_score + score, first_seen)


def _rank_global_candidates(candidate_scores: dict[str, tuple[RetrievedChunk, float, int]]) -> list[RetrievedChunk]:
    ranked = sorted(
        candidate_scores.values(),
        key=lambda item: (item[1], -item[2]),
        reverse=True,
    )
    return [
        RetrievedChunk(**{**chunk.to_dict(), "score": score})
        for chunk, score, _ in ranked[: settings.RAG_FINAL_SEED_TOP_K]
    ]


def _source_weight(source: str) -> float:
    if source == "original_query":
        return settings.RAG_SOURCE_WEIGHT_ORIGINAL_QUERY
    if source == "rewritten_query":
        return settings.RAG_SOURCE_WEIGHT_REWRITTEN_QUERY
    if source == "sub_query":
        return settings.RAG_SOURCE_WEIGHT_SUB_QUERY
    if source == "keywords":
        return settings.RAG_SOURCE_WEIGHT_KEYWORDS
    return 1.0


def _format_page_range(start, end) -> str:
    start_text = str(start) if start is not None and start != "" else ""
    end_text = str(end) if end is not None and end != "" else ""
    if start_text and end_text and start_text != end_text:
        return f"{start_text}-{end_text}"
    return start_text or end_text or "unknown"


def _format_context_window(seed: RetrievedChunk, window_chunks: list[RetrievedChunk]) -> str:
    if not window_chunks:
        return seed.content

    blocks: list[str] = []
    for chunk in window_chunks:
        page = _format_page_range(chunk.page_number_start, chunk.page_number_end)
        role = "seed" if chunk.chunk_id == seed.chunk_id else "neighbor"
        blocks.append(
            "\n".join(
                [
                    f"[{role} chunk_id={chunk.chunk_id} page={page}]",
                    chunk.content,
                ]
            )
        )
    return "\n\n".join(blocks)


def expand_chunk_contexts(seeds: list[RetrievedChunk], *, window: int | None = None) -> list[RetrievedChunk]:
    window = settings.RAG_CHUNK_EXPANSION_WINDOW if window is None else window
    if window <= 0:
        return seeds

    sparse_index = get_sparse_index()
    expanded: list[RetrievedChunk] = []
    for seed in seeds:
        window_chunks = sparse_index.context_window(seed.chunk_id, window=window)
        context_chunk_ids = tuple(chunk.chunk_id for chunk in window_chunks) or (seed.chunk_id,)
        expanded.append(
            RetrievedChunk(
                chunk_id=seed.chunk_id,
                source_file=seed.source_file,
                section_title=seed.section_title,
                page_number_start=seed.page_number_start,
                page_number_end=seed.page_number_end,
                chunk_type=seed.chunk_type,
                score=seed.score,
                content=_format_context_window(seed, window_chunks),
                context_chunk_ids=context_chunk_ids,
            )
        )
    return expanded


async def _retrieve_vector_only(
    query: str,
    *,
    source_file: str | None,
    top_k: int,
    redis: Redis | None,
) -> list[RetrievedChunk]:
    return await _vector_recall(query, source_file=source_file, recall_k=top_k, redis=redis)


async def _retrieve_hybrid(
    query: str,
    *,
    source_file: str | None,
    top_k: int,
    redis: Redis | None,
) -> list[RetrievedChunk]:
    vector_recall_k = max(top_k, settings.RAG_VECTOR_RECALL_K)
    sparse_recall_k = max(top_k, settings.RAG_SPARSE_RECALL_K)
    vector_chunks = await _vector_recall(query, source_file=source_file, recall_k=vector_recall_k, redis=redis)
    sparse_chunks = _sparse_recall(query, source_file=source_file, recall_k=sparse_recall_k)

    candidates = _merge_with_rrf(vector_chunks=vector_chunks, sparse_chunks=sparse_chunks)
    return _rank_fused_candidates(candidates, limit=top_k)


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
    retrieval_key = (
        "rag:retrieval:"
        f"{settings.RAG_RETRIEVAL_STRATEGY}:seed-only:"
        f"{query_hash}:{source_key}:{effective_top_k}"
    )

    cached_results = await _get_cached_json(redis, retrieval_key)
    if cached_results is not None:
        return [RetrievedChunk.from_dict(item) for item in cached_results]

    if settings.RAG_RETRIEVAL_STRATEGY == "vector":
        chunks = await _retrieve_vector_only(
            cleaned_query,
            source_file=source_file,
            top_k=effective_top_k,
            redis=redis,
        )
    else:
        chunks = await _retrieve_hybrid(
            cleaned_query,
            source_file=source_file,
            top_k=effective_top_k,
            redis=redis,
        )

    await _set_cached_json(
        redis,
        retrieval_key,
        [chunk.to_dict() for chunk in chunks],
        settings.RAG_RETRIEVAL_CACHE_TTL,
    )
    logger.info(
        "RAG retrieval strategy={} query_hash={} source_file={} top_k={} hits={}",
        settings.RAG_RETRIEVAL_STRATEGY,
        query_hash,
        source_file,
        effective_top_k,
        [chunk.chunk_id for chunk in chunks],
    )
    return chunks


async def retrieve_sparse_chunks(
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
    retrieval_key = (
        "rag:retrieval:"
        "sparse-only:seed-only:"
        f"{query_hash}:{source_key}:{effective_top_k}"
    )

    cached_results = await _get_cached_json(redis, retrieval_key)
    if cached_results is not None:
        return [RetrievedChunk.from_dict(item) for item in cached_results]

    chunks = _sparse_recall(cleaned_query, source_file=source_file, recall_k=effective_top_k)
    await _set_cached_json(
        redis,
        retrieval_key,
        [chunk.to_dict() for chunk in chunks],
        settings.RAG_RETRIEVAL_CACHE_TTL,
    )
    logger.info(
        "RAG sparse retrieval query_hash={} source_file={} top_k={} hits={}",
        query_hash,
        source_file,
        effective_top_k,
        [chunk.chunk_id for chunk in chunks],
    )
    return chunks


async def retrieve_rewritten_query_seeds(
    rewrite,
    *,
    source_file: str | None = None,
    top_k: int | None = None,
    redis: Redis | None = None,
) -> list[RetrievedChunk]:
    effective_top_k = top_k or settings.RAG_TOP_K
    hybrid_query_jobs = _build_hybrid_query_jobs(rewrite)
    keyword_query = rewrite.keyword_query()

    candidate_scores: dict[str, tuple[RetrievedChunk, float, int]] = {}
    for source, query in hybrid_query_jobs:
        chunks = await retrieve_chunks(
            query,
            source_file=source_file,
            top_k=effective_top_k,
            redis=redis,
        )
        _merge_ranked_candidates(candidate_scores, chunks, source=source)

    if keyword_query:
        chunks = await retrieve_sparse_chunks(
            keyword_query,
            source_file=source_file,
            top_k=effective_top_k,
            redis=redis,
        )
        _merge_ranked_candidates(candidate_scores, chunks, source="keywords")

    seeds = _rank_global_candidates(candidate_scores)
    logger.info(
        "RAG rewritten query seed retrieval hybrid_queries={} keywords={} seed_hits={}",
        hybrid_query_jobs,
        rewrite.keywords,
        [chunk.chunk_id for chunk in seeds],
    )
    return seeds
