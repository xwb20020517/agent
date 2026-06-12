from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.response import ApiResponse, success
from app.schemas.user import UserRead


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=ApiResponse[UserRead])
async def read_current_user(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[UserRead]:
    return success(
        UserRead.model_validate(current_user),
        request_id=getattr(request.state, "request_id", None),
    )
