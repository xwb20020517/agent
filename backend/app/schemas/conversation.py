from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.message import MessageRead


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=255)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    model_name: str | None
    system_prompt: str | None
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]
