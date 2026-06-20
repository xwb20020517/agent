import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.manual_chunk import ManualChunk
from app.models.manual_document import ManualDocument
from app.rag.utils import sha256_text


REQUIRED_FIELDS = ("chunk_id", "source_file", "content", "chunk_type")


@dataclass
class ImportStats:
    file_path: str
    source_files: set[str] = field(default_factory=set)
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0


def _read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                yield line_no, json.loads(text)
            except json.JSONDecodeError as exc:
                logger.warning("Invalid JSONL row file={} line={} error={}", path, line_no, exc)
                yield line_no, None


def _validate_record(record: dict[str, Any] | None) -> str | None:
    if record is None:
        return "invalid_json"
    for field_name in REQUIRED_FIELDS:
        if not str(record.get(field_name) or "").strip():
            return f"missing_{field_name}"
    return None


async def _get_or_create_document(session: AsyncSession, source_file: str) -> ManualDocument:
    result = await session.execute(select(ManualDocument).where(ManualDocument.source_file == source_file))
    document = result.scalar_one_or_none()
    if document:
        return document
    document = ManualDocument(
        source_file=source_file,
        display_name=source_file,
        embedding_status="pending",
    )
    session.add(document)
    await session.flush()
    return document


async def import_jsonl_file(session: AsyncSession, path: str | Path) -> ImportStats:
    jsonl_path = Path(path)
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file does not exist: {jsonl_path}")
    if not jsonl_path.is_file():
        raise ValueError(f"JSONL path is not a file: {jsonl_path}")

    started_at = perf_counter()
    stats = ImportStats(file_path=str(jsonl_path))
    logger.info("Import chunks started: {}", jsonl_path)

    documents: dict[str, ManualDocument] = {}
    touched_source_files: set[str] = set()

    for line_no, record in _read_jsonl(jsonl_path):
        error = _validate_record(record)
        if error:
            stats.failed += 1
            logger.warning("Skip invalid chunk file={} line={} reason={}", jsonl_path, line_no, error)
            continue

        assert record is not None
        chunk_id = str(record["chunk_id"]).strip()
        source_file = str(record["source_file"]).strip()
        content = str(record["content"]).strip()
        content_hash = sha256_text(content)
        stats.source_files.add(source_file)
        touched_source_files.add(source_file)

        document = documents.get(source_file)
        if document is None:
            document = await _get_or_create_document(session, source_file)
            documents[source_file] = document

        result = await session.execute(select(ManualChunk).where(ManualChunk.chunk_id == chunk_id))
        chunk = result.scalar_one_or_none()
        metadata = record.get("metadata")
        metadata_json = metadata if isinstance(metadata, dict) else {}

        if chunk is None:
            session.add(
                ManualChunk(
                    chunk_id=chunk_id,
                    document_id=document.id,
                    source_file=source_file,
                    page_idx_start=record.get("page_idx_start"),
                    page_idx_end=record.get("page_idx_end"),
                    page_number_start=record.get("page_number_start"),
                    page_number_end=record.get("page_number_end"),
                    chunk_type=str(record["chunk_type"]).strip(),
                    section_title=record.get("section_title"),
                    content=content,
                    content_hash=content_hash,
                    metadata_json=metadata_json,
                    embedding_status="pending",
                )
            )
            stats.inserted += 1
            continue

        if chunk.content_hash == content_hash:
            stats.skipped += 1
            continue

        chunk.document_id = document.id
        chunk.source_file = source_file
        chunk.page_idx_start = record.get("page_idx_start")
        chunk.page_idx_end = record.get("page_idx_end")
        chunk.page_number_start = record.get("page_number_start")
        chunk.page_number_end = record.get("page_number_end")
        chunk.chunk_type = str(record["chunk_type"]).strip()
        chunk.section_title = record.get("section_title")
        chunk.content = content
        chunk.content_hash = content_hash
        chunk.metadata_json = metadata_json
        chunk.vector_id = None
        chunk.embedding_status = "pending"
        stats.updated += 1

    await session.flush()
    for source_file in touched_source_files:
        document = documents[source_file]
        count_result = await session.execute(
            select(func.count()).select_from(ManualChunk).where(ManualChunk.source_file == source_file)
        )
        document.chunk_count = int(count_result.scalar_one() or 0)
        if stats.inserted or stats.updated:
            document.embedding_status = "pending"

    await session.commit()
    stats.elapsed_seconds = perf_counter() - started_at
    logger.info(
        "Import chunks finished: file={} inserted={} updated={} skipped={} failed={} elapsed={:.2f}s",
        jsonl_path,
        stats.inserted,
        stats.updated,
        stats.skipped,
        stats.failed,
        stats.elapsed_seconds,
    )
    return stats


async def import_jsonl_dir(session: AsyncSession, path: str | Path) -> list[ImportStats]:
    dir_path = Path(path)
    if not dir_path.exists():
        raise FileNotFoundError(f"JSONL directory does not exist: {dir_path}")
    if not dir_path.is_dir():
        raise ValueError(f"JSONL path is not a directory: {dir_path}")
    stats: list[ImportStats] = []
    for jsonl_file in sorted(dir_path.glob("*.jsonl")):
        stats.append(await import_jsonl_file(session, jsonl_file))
    return stats
