import argparse
import asyncio
from uuid import NAMESPACE_URL, uuid5
from itertools import islice
from time import perf_counter

from loguru import logger
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.core.exceptions import AppException
from app.models.manual_chunk import ManualChunk
from app.models.manual_document import ManualDocument
from app.rag.vector_store import QdrantVectorStore
from app.services.embedding_service import embed_texts


def vector_id_for_chunk(chunk_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"car-manual-rag:{chunk_id}"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Qdrant embeddings for imported manual chunks.")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--source-file", help="Only build chunks from one manual source file.")
    target.add_argument(
        "--all",
        action="store_true",
        help="Build all pending or failed chunks. This is now the default when no source filter is provided.",
    )
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size.")
    return parser.parse_args()


def batched(items: list[ManualChunk], size: int):
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def point_from_chunk(chunk: ManualChunk, vector: list[float]) -> dict:
    vector_id = vector_id_for_chunk(chunk.chunk_id)
    return {
        "id": vector_id,
        "vector": vector,
        "payload": {
            "chunk_id": chunk.chunk_id,
            "source_file": chunk.source_file,
            "page_idx_start": chunk.page_idx_start,
            "page_idx_end": chunk.page_idx_end,
            "page_number_start": chunk.page_number_start,
            "page_number_end": chunk.page_number_end,
            "chunk_type": chunk.chunk_type,
            "section_title": chunk.section_title,
            "content": chunk.content,
        },
    }


async def update_document_statuses(session, source_files: set[str]) -> None:
    for source_file in source_files:
        remaining = await session.execute(
            select(func.count())
            .select_from(ManualChunk)
            .where(
                ManualChunk.source_file == source_file,
                ManualChunk.embedding_status.in_(["pending", "processing", "failed"]),
            )
        )
        document = (
            await session.execute(select(ManualDocument).where(ManualDocument.source_file == source_file))
        ).scalar_one_or_none()
        if document:
            document.embedding_status = "completed" if int(remaining.scalar_one() or 0) == 0 else "failed"


async def main() -> None:
    args = parse_args()
    batch_size = max(1, args.batch_size)
    started_at = perf_counter()
    vector_store = QdrantVectorStore()

    async with AsyncSessionLocal() as session:
        query = select(ManualChunk).where(ManualChunk.embedding_status.in_(["pending", "failed"]))
        if args.source_file:
            query = query.where(ManualChunk.source_file == args.source_file)
        chunks = list((await session.execute(query.order_by(ManualChunk.id.asc()))).scalars().all())
        source_files = {chunk.source_file for chunk in chunks}

        for source_file in source_files:
            document = (
                await session.execute(select(ManualDocument).where(ManualDocument.source_file == source_file))
            ).scalar_one_or_none()
            if document:
                document.embedding_status = "processing"
        await session.commit()

        completed = 0
        failed = 0
        for batch in batched(chunks, batch_size):
            batch_started = perf_counter()
            try:
                vectors = await embed_texts([chunk.content for chunk in batch])
                await vector_store.upsert_points(
                    [point_from_chunk(chunk, vector) for chunk, vector in zip(batch, vectors, strict=True)]
                )
                for chunk in batch:
                    chunk.vector_id = vector_id_for_chunk(chunk.chunk_id)
                    chunk.embedding_status = "completed"
                completed += len(batch)
                await session.commit()
                logger.info("Embedding batch completed size={} elapsed={:.2f}s", len(batch), perf_counter() - batch_started)
            except Exception as exc:
                failed += len(batch)
                logger.exception("Embedding batch failed size={}", len(batch))
                for chunk in batch:
                    chunk.embedding_status = "failed"
                await session.commit()
                if isinstance(exc, AppException):
                    print(f"批次失败：{exc.message} {exc.data or ''}")
                else:
                    print(f"批次失败：{exc}")

        await update_document_statuses(session, source_files)
        await session.commit()

    print(f"待处理 chunks：{len(chunks)}")
    print(f"完成 chunks：{completed}")
    print(f"失败 chunks：{failed}")
    print(f"总耗时：{perf_counter() - started_at:.2f} 秒")


if __name__ == "__main__":
    asyncio.run(main())
    # uv run python -m app.scripts.build_embeddings --batch-size 32
