from pydantic import BaseModel, Field


class RAGSource(BaseModel):
    chunk_id: str
    source_file: str
    section_title: str | None = None
    page_number_start: str | None = None
    page_number_end: str | None = None
    score: float
    content_preview: str


class RAGSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    source_file: str | None = Field(default=None, max_length=255)
    top_k: int | None = Field(default=None, ge=1, le=20)


class RAGSearchResult(BaseModel):
    chunk_id: str
    source_file: str
    section_title: str | None = None
    page_number_start: str | None = None
    page_number_end: str | None = None
    chunk_type: str | None = None
    score: float
    content: str


class RAGSearchResponse(BaseModel):
    query: str
    results: list[RAGSearchResult]


class ManualDocumentRead(BaseModel):
    id: int
    source_file: str
    display_name: str | None = None
    car_model_name: str | None = None
    chunk_count: int
    embedding_status: str

    model_config = {"from_attributes": True}


class ManualChunkRead(BaseModel):
    chunk_id: str
    source_file: str
    section_title: str | None = None
    page_number_start: str | None = None
    page_number_end: str | None = None
    chunk_type: str
    content_preview: str
    embedding_status: str


class ManualChunkPage(BaseModel):
    items: list[ManualChunkRead]
    total: int
    page: int
    page_size: int
