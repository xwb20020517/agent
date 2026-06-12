from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


MessageRole = Literal["user", "assistant", "system"]
MessageStatus = Literal["success", "streaming", "failed"]


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    user_id: int
    role: MessageRole
    content: str
    status: MessageStatus
    token_count: int | None
    latency_ms: int | None
    created_at: datetime
