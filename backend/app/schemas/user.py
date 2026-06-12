from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
