from fastapi import APIRouter, Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_redis_client
from app.db.session import get_db_session
from app.models.manual_chunk import ManualChunk
from app.models.manual_document import ManualDocument
from app.models.user import User
from app.rag.retriever import retrieve_chunks
from app.rag.utils import content_preview
from app.schemas.rag import (
    ManualChunkPage,
    ManualChunkRead,
    ManualDocumentRead,
    RAGSearchRequest,
    RAGSearchResponse,
    RAGSearchResult,
)
from app.schemas.response import ApiResponse, success


router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search", response_model=ApiResponse[RAGSearchResponse])
async def search_manual_chunks(
    payload: RAGSearchRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis_client),
) -> ApiResponse[RAGSearchResponse]:
    del current_user
    chunks = await retrieve_chunks(
        payload.query,
        source_file=payload.source_file,
        top_k=payload.top_k,
        redis=redis,
    )
    return success(
        RAGSearchResponse(
            query=payload.query,
            results=[
                RAGSearchResult(
                    chunk_id=chunk.chunk_id,
                    source_file=chunk.source_file,
                    section_title=chunk.section_title,
                    page_number_start=chunk.page_number_start,
                    page_number_end=chunk.page_number_end,
                    chunk_type=chunk.chunk_type,
                    score=chunk.score,
                    content=chunk.content,
                )
                for chunk in chunks
            ],
        ),
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/documents", response_model=ApiResponse[list[ManualDocumentRead]])
async def list_manual_documents(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[list[ManualDocumentRead]]:
    del current_user
    result = await session.execute(select(ManualDocument).order_by(ManualDocument.source_file.asc()))
    return success(
        [ManualDocumentRead.model_validate(item) for item in result.scalars().all()],
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/documents/{document_id}/chunks", response_model=ApiResponse[ManualChunkPage])
async def list_manual_document_chunks(
    document_id: int,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[ManualChunkPage]:
    del current_user
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(ManualChunk).where(ManualChunk.document_id == document_id)
            )
        ).scalar_one()
        or 0
    )
    result = await session.execute(
        select(ManualChunk)
        .where(ManualChunk.document_id == document_id)
        .order_by(ManualChunk.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    chunks = result.scalars().all()
    return success(
        ManualChunkPage(
            items=[
                ManualChunkRead(
                    chunk_id=chunk.chunk_id,
                    source_file=chunk.source_file,
                    section_title=chunk.section_title,
                    page_number_start=chunk.page_number_start,
                    page_number_end=chunk.page_number_end,
                    chunk_type=chunk.chunk_type,
                    content_preview=content_preview(chunk.content),
                    embedding_status=chunk.embedding_status,
                )
                for chunk in chunks
            ],
            total=total,
            page=page,
            page_size=page_size,
        ),
        request_id=getattr(request.state, "request_id", None),
    )
