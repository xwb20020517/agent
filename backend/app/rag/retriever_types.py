from dataclasses import dataclass
from typing import Any


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
    context_chunk_ids: tuple[str, ...] = ()

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
            "context_chunk_ids": list(self.context_chunk_ids),
        }

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> "RetrievedChunk":
        return cls(
            chunk_id=str(item["chunk_id"]),
            source_file=str(item["source_file"]),
            section_title=item.get("section_title"),
            page_number_start=item.get("page_number_start"),
            page_number_end=item.get("page_number_end"),
            chunk_type=item.get("chunk_type"),
            score=float(item.get("score", 0.0)),
            content=str(item.get("content") or ""),
            context_chunk_ids=tuple(str(value) for value in item.get("context_chunk_ids", [])),
        )
