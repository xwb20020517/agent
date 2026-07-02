import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import settings
from app.rag.retriever_types import PageNumber, RetrievedChunk


_ALNUM_RE = re.compile(r"[a-zA-Z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class SparseHit:
    chunk: RetrievedChunk
    score: float


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    source_file: str
    section_title: str | None
    page_number_start: PageNumber
    page_number_end: PageNumber
    chunk_type: str | None
    content: str

    def to_retrieved(self, score: float = 0.0) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=self.chunk_id,
            source_file=self.source_file,
            section_title=self.section_title,
            page_number_start=self.page_number_start,
            page_number_end=self.page_number_end,
            chunk_type=self.chunk_type,
            score=score,
            content=self.content,
        )


def tokenize(text: str) -> list[str]:
    normalized = text.lower()
    tokens: list[str] = []
    tokens.extend(match.group(0) for match in _ALNUM_RE.finditer(normalized))
    for match in _CJK_RE.finditer(normalized):
        chars = match.group(0)
        tokens.extend(chars)
        if len(chars) > 1:
            tokens.extend(chars[index : index + 2] for index in range(len(chars) - 1))
    return tokens


class SparseChunkIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: list[ChunkRecord] = []
        self.record_by_id: dict[str, ChunkRecord] = {}
        self.position_by_id: dict[str, tuple[str, int]] = {}
        self.ids_by_source: dict[str, list[str]] = defaultdict(list)
        self.doc_lengths: list[int] = []
        self.inverted_index: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.doc_freq: dict[str, int] = {}
        self.avg_doc_length = 0.0
        self._load()
        self._build()

    def _load(self) -> None:
        if not self.path.exists():
            logger.warning("Sparse chunk index file does not exist: {}", self.path)
            return
        with self.path.open("r", encoding="utf-8") as file:
            for line_no, line in enumerate(file, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    item = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    logger.warning("Skip invalid chunk JSON file={} line={} error={}", self.path, line_no, exc)
                    continue
                record = self._record_from_json(item)
                if not record:
                    continue
                self.position_by_id[record.chunk_id] = (record.source_file, len(self.ids_by_source[record.source_file]))
                self.ids_by_source[record.source_file].append(record.chunk_id)
                self.record_by_id[record.chunk_id] = record
                self.records.append(record)
        logger.info("Loaded {} chunks for sparse index from {}", len(self.records), self.path)

    def _record_from_json(self, item: dict[str, Any]) -> ChunkRecord | None:
        chunk_id = str(item.get("chunk_id") or "").strip()
        source_file = str(item.get("source_file") or "").strip()
        content = str(item.get("content") or "").strip()
        if not chunk_id or not source_file or not content:
            return None
        return ChunkRecord(
            chunk_id=chunk_id,
            source_file=source_file,
            section_title=item.get("section_title"),
            page_number_start=item.get("page_number_start"),
            page_number_end=item.get("page_number_end"),
            chunk_type=item.get("chunk_type"),
            content=content,
        )

    def _build(self) -> None:
        doc_freq_counter: Counter[str] = Counter()
        term_frequencies: list[Counter[str]] = []
        for record in self.records:
            counts = Counter(tokenize(f"{record.section_title or ''}\n{record.content}"))
            term_frequencies.append(counts)
            self.doc_lengths.append(sum(counts.values()))
            doc_freq_counter.update(counts.keys())

        self.doc_freq = dict(doc_freq_counter)
        self.avg_doc_length = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 0.0
        for doc_index, counts in enumerate(term_frequencies):
            for term, freq in counts.items():
                self.inverted_index[term].append((doc_index, freq))

    def search(self, query: str, *, top_k: int, source_file: str | None = None) -> list[SparseHit]:
        if not self.records or top_k <= 0:
            return []
        query_terms = Counter(tokenize(query))
        if not query_terms:
            return []

        scores: dict[int, float] = defaultdict(float)
        total_docs = len(self.records)
        k1 = 1.5
        b = 0.75
        for term, query_freq in query_terms.items():
            postings = self.inverted_index.get(term)
            if not postings:
                continue
            idf = math.log(1 + (total_docs - self.doc_freq.get(term, 0) + 0.5) / (self.doc_freq.get(term, 0) + 0.5))
            for doc_index, term_freq in postings:
                record = self.records[doc_index]
                if source_file and record.source_file != source_file:
                    continue
                doc_length = self.doc_lengths[doc_index] or 1
                denominator = term_freq + k1 * (1 - b + b * doc_length / (self.avg_doc_length or 1))
                scores[doc_index] += query_freq * idf * (term_freq * (k1 + 1)) / denominator

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return [SparseHit(chunk=self.records[index].to_retrieved(score=score), score=score) for index, score in ranked]

    def get_chunk(self, chunk_id: str, *, score: float = 0.0) -> RetrievedChunk | None:
        record = self.record_by_id.get(chunk_id)
        return record.to_retrieved(score=score) if record else None

    def expand_neighbors(self, chunk_ids: list[str], *, window: int) -> list[RetrievedChunk]:
        if window <= 0:
            return []
        expanded: list[RetrievedChunk] = []
        seen: set[str] = set()
        for chunk_id in chunk_ids:
            position = self.position_by_id.get(chunk_id)
            if not position:
                continue
            source_file, index = position
            ids = self.ids_by_source[source_file]
            start = max(0, index - window)
            end = min(len(ids), index + window + 1)
            for neighbor_id in ids[start:end]:
                if neighbor_id in seen or neighbor_id in chunk_ids:
                    continue
                neighbor = self.get_chunk(neighbor_id)
                if neighbor:
                    expanded.append(neighbor)
                    seen.add(neighbor_id)
        return expanded

    def context_window(self, chunk_id: str, *, window: int) -> list[RetrievedChunk]:
        position = self.position_by_id.get(chunk_id)
        if not position:
            chunk = self.get_chunk(chunk_id)
            return [chunk] if chunk else []

        source_file, index = position
        ids = self.ids_by_source[source_file]
        start = max(0, index - max(0, window))
        end = min(len(ids), index + max(0, window) + 1)
        chunks: list[RetrievedChunk] = []
        for neighbor_id in ids[start:end]:
            chunk = self.get_chunk(neighbor_id)
            if chunk:
                chunks.append(chunk)
        return chunks


@lru_cache(maxsize=1)
def get_sparse_index() -> SparseChunkIndex:
    return SparseChunkIndex(Path(settings.RAG_CHUNKS_JSONL_PATH))
