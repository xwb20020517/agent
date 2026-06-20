from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ManualChunk(Base):
    __tablename__ = "manual_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("manual_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_file: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    page_idx_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_idx_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number_start: Mapped[str | None] = mapped_column(String(50), nullable=True)
    page_number_end: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False)
    section_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    vector_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_status: Mapped[str] = mapped_column(String(50), default="pending", index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
