from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.permissions import require_permission
from app.dependencies.tenant import get_current_gym_id
from app.models.enums import PermissionCode, RoleName
from app.models.user import User
from app.schemas.staff import StaffUserRead

router = APIRouter(prefix="/staff", tags=["staff"])

GYM_USER_ROLES = (
    RoleName.MEMBER,
    RoleName.TRAINER,
    RoleName.RECEPTIONIST,
    RoleName.SUB_ADMIN,
)


@router.get("", response_model=list[StaffUserRead])
def list_staff_users(
    q: str | None = Query(default=None, max_length=120),
    role: RoleName | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    _: User = Depends(require_permission(PermissionCode.MANAGE_STAFF)),
) -> list[User]:
    allowed_roles = {role_name.value for role_name in GYM_USER_ROLES}
    if role is not None and role.value not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role is not a gym user role.")

    statement = select(User).where(
        User.gym_id == gym_id,
        User.is_active.is_(True),
        User.role.in_([role_name.value for role_name in GYM_USER_ROLES]),
    )
    if role is not None:
        statement = statement.where(User.role == role.value)

    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                User.phone.ilike(pattern),
            )
        )

    statement = statement.order_by(User.created_at.desc()).offset(skip).limit(min(limit, 200))
    return list(db.scalars(statement).all())
