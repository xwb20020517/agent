from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=20000)
    source_file: str | None = Field(default=None, max_length=255)
    top_k: int | None = Field(default=None, ge=1, le=20)
    stream: bool = False
