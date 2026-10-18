from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.models.enums import GymStatus, PermissionCode, RoleName
from app.models.gym import Gym
from app.models.user import User
from app.permissions.rbac import has_permission
from app.schemas.common import MessageResponse
from app.schemas.user_management import UserCreate, UserRead, UserRoleCounts, UserUpdate
from app.services.auth import _ensure_member_profile_for_user, _ensure_trainer_profile_for_user

router = APIRouter(prefix="/users", tags=["users"])

GYM_ADMIN_MANAGED_ROLES = (
    RoleName.MEMBER,
    RoleName.TRAINER,
    RoleName.RECEPTIONIST,
    RoleName.SUB_ADMIN,
)
SUPER_ADMIN_MANAGED_ROLES = (*GYM_ADMIN_MANAGED_ROLES, RoleName.GYM_OWNER)


def _is_gym_admin(user: User) -> bool:
    return user.role == RoleName.GYM_OWNER.value


def _is_sub_admin_staff_manager(user: User) -> bool:
    return user.role == RoleName.SUB_ADMIN.value and has_permission(user, PermissionCode.MANAGE_STAFF)


def _is_gym_scoped_user_manager(user: User) -> bool:
    return _is_gym_admin(user) or _is_sub_admin_staff_manager(user)


def _is_super_admin(user: User) -> bool:
    return user.role == RoleName.SUPER_ADMIN.value


def _require_user_manager(user: User) -> None:
    if not (_is_gym_scoped_user_manager(user) or _is_super_admin(user)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User management access is required.")


def _read_user(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        gym_id=user.gym_id,
        gym_name=user.gym_name,
        name=user.full_name,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        role=RoleName(user.role),
        status="active" if user.is_active else "inactive",
        created_at=user.created_at,
        updated_at=user.updated_at,
        created_by=user.created_by,
        updated_by=user.updated_by,
        is_active=user.is_active,
    )


def _get_active_gym(db: Session, gym_id: UUID) -> Gym:
    gym = db.scalar(
        select(Gym).where(
            Gym.id == gym_id,
            Gym.is_active.is_(True),
            Gym.status == GymStatus.ACTIVE.value,
        )
    )
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    return gym


def _gym_for_create(db: Session, current_user: User, payload: UserCreate) -> Gym:
    if _is_gym_scoped_user_manager(current_user):
        if current_user.gym_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gym admin is not linked to a gym.")
        if payload.gym_id is not None and payload.gym_id != current_user.gym_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create users for another gym.")
        return _get_active_gym(db, current_user.gym_id)

    if payload.gym_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="gym_id is required for Super Admin user creation.")
    return _get_active_gym(db, payload.gym_id)


def _validate_create_role(current_user: User, role: RoleName) -> None:
    if _is_gym_scoped_user_manager(current_user) and role not in GYM_ADMIN_MANAGED_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gym Admin can create only gym user roles.")
    if _is_super_admin(current_user) and role not in SUPER_ADMIN_MANAGED_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role cannot be created from this endpoint.")


def _base_list_statement(current_user: User):
    statement = select(User)
    if _is_gym_scoped_user_manager(current_user):
        if current_user.gym_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gym admin is not linked to a gym.")
        statement = statement.where(
            User.gym_id == current_user.gym_id,
            User.role.in_([role.value for role in GYM_ADMIN_MANAGED_ROLES]),
        )
    return statement


def _get_managed_user(db: Session, current_user: User, user_id: UUID) -> User:
    if _is_super_admin(current_user):
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User was not found.")
        return user

    if current_user.gym_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gym admin is not linked to a gym.")

    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.gym_id == current_user.gym_id,
            User.role.in_([role.value for role in GYM_ADMIN_MANAGED_ROLES]),
        )
    )
    if user is not None:
        return user

    other_user = db.scalar(select(User.id).where(User.id == user_id))
    if other_user is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User belongs to another gym.")

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User was not found.")


def _ensure_role_profile(db: Session, user: User, gym: Gym) -> None:
    if user.role == RoleName.MEMBER.value:
        _ensure_member_profile_for_user(db, user, gym)
    elif user.role == RoleName.TRAINER.value:
        _ensure_trainer_profile_for_user(db, user, gym)


def _allowed_roles_for_user_manager(current_user: User) -> tuple[RoleName, ...]:
    return SUPER_ADMIN_MANAGED_ROLES if _is_super_admin(current_user) else GYM_ADMIN_MANAGED_ROLES


@router.get("", response_model=list[UserRead])
def list_users(
    q: str | None = Query(default=None, max_length=120),
    role: RoleName | None = Query(default=None),
    gym_id: UUID | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UserRead]:
    _require_user_manager(current_user)
    if _is_gym_scoped_user_manager(current_user) and gym_id is not None and gym_id != current_user.gym_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view users for another gym.")

    statement = _base_list_statement(current_user)
    if _is_super_admin(current_user) and gym_id is not None:
        statement = statement.where(User.gym_id == gym_id)

    if role is not None:
        allowed_roles = _allowed_roles_for_user_manager(current_user)
        if role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role filter is not allowed.")
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
    return [_read_user(user) for user in db.scalars(statement).all()]


@router.get("/counts", response_model=UserRoleCounts)
def count_users(
    gym_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserRoleCounts:
    _require_user_manager(current_user)
    if _is_gym_scoped_user_manager(current_user):
        if current_user.gym_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Gym admin is not linked to a gym.")
        if gym_id is not None and gym_id != current_user.gym_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view users for another gym.")
        target_gym_id = current_user.gym_id
    else:
        target_gym_id = gym_id

    allowed_roles = _allowed_roles_for_user_manager(current_user)
    statement = select(User.role, func.count(User.id)).where(User.role.in_([role.value for role in allowed_roles]))
    if target_gym_id is not None:
        statement = statement.where(User.gym_id == target_gym_id)
    statement = statement.group_by(User.role)

    counts = {role.value: 0 for role in SUPER_ADMIN_MANAGED_ROLES}
    total = 0
    for role, count in db.execute(statement).all():
        if role in counts:
            counts[role] = count
            total += count

    return UserRoleCounts(total=total, **counts)


@router.post("", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserRead:
    _require_user_manager(current_user)
    _validate_create_role(current_user, payload.role)
    gym = _gym_for_create(db, current_user, payload)

    existing_user = db.scalar(select(User.id).where(User.email == payload.email.lower()))
    if existing_user is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    user = User(
        gym_id=gym.id,
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role.value,
        phone=payload.phone,
        is_active=payload.status == "active",
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(user)
    db.flush()
    _ensure_role_profile(db, user, gym)
    db.commit()
    db.refresh(user)
    return _read_user(user)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserRead:
    _require_user_manager(current_user)
    user = _get_managed_user(db, current_user, user_id)
    if user.role == RoleName.SUPER_ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin accounts are protected and can only be changed in the codebase.")
    fields_set = payload.model_fields_set

    target_gym_id = user.gym_id
    if _is_gym_scoped_user_manager(current_user):
        if "gym_id" in fields_set and payload.gym_id is not None and payload.gym_id != current_user.gym_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot move users to another gym.")
        if "role" in fields_set and payload.role is not None and payload.role not in GYM_ADMIN_MANAGED_ROLES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gym Admin can assign only gym user roles.")
        target_gym_id = current_user.gym_id
    else:
        if "role" in fields_set and payload.role is not None and payload.role not in SUPER_ADMIN_MANAGED_ROLES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role cannot be assigned from this endpoint.")
        if "gym_id" in fields_set and payload.gym_id is not None:
            target_gym_id = payload.gym_id

    if target_gym_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="gym_id is required.")
    gym = _get_active_gym(db, target_gym_id)

    if "email" in fields_set and payload.email is not None and payload.email.lower() != user.email.lower():
        existing_user = db.scalar(select(User.id).where(User.email == payload.email.lower(), User.id != user.id))
        if existing_user is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")
        user.email = payload.email.lower()

    if "full_name" in fields_set and payload.full_name is not None:
        user.full_name = payload.full_name
    if "phone" in fields_set:
        user.phone = payload.phone
    if "password" in fields_set and payload.password is not None:
        user.hashed_password = hash_password(payload.password)
        user.refresh_token_hash = None
    if "role" in fields_set and payload.role is not None:
        user.role = payload.role.value
    if "status" in fields_set and payload.status is not None:
        user.is_active = payload.status == "active"
    if user.gym_id != gym.id:
        user.gym_id = gym.id
    user.updated_by = current_user.id

    db.flush()
    _ensure_role_profile(db, user, gym)
    db.commit()
    db.refresh(user)
    return _read_user(user)


@router.delete("/{user_id}", response_model=MessageResponse)
def deactivate_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    _require_user_manager(current_user)
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account.")

    user = _get_managed_user(db, current_user, user_id)
    if user.role == RoleName.SUPER_ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin accounts are protected and can only be changed in the codebase.")
    user.is_active = False
    user.refresh_token_hash = None
    user.updated_by = current_user.id
    db.commit()
    return MessageResponse(message="User was deactivated.")
