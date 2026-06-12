from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=20000)
    stream: bool = False


class ChatResponse(BaseModel):
    conversation_id: int
    user_message_id: int
    assistant_message_id: int
    answer: str
