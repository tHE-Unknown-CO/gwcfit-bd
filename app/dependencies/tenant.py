from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.dependencies.auth import get_current_user
from app.models.enums import RoleName
from app.models.user import User


def get_current_gym_id(current_user: User = Depends(get_current_user)) -> UUID:
    if current_user.role == RoleName.SUPER_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint requires a gym-scoped user.",
        )
    if current_user.gym_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not linked to a gym.",
        )
    return current_user.gym_id


def get_optional_gym_id(current_user: User = Depends(get_current_user)) -> UUID | None:
    """Return the tenant for gym users, or None for platform-wide admin reads."""
    if current_user.role == RoleName.SUPER_ADMIN.value:
        return None
    if current_user.gym_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not linked to a gym.",
        )
    return current_user.gym_id
