from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import require_permission, require_member
from app.models.enums import PermissionCode, RoleName
from app.models.gym import Gym
from app.models.member import Member
from app.models.trainer import Trainer
from app.models.user import User
from app.permissions.rbac import has_permission
from app.repositories.base import TenantRepository
from app.schemas.common import MessageResponse
from app.schemas.member import MemberCreate, MemberRead, MemberUpdate
from app.services.auth import _ensure_member_profile_for_user

router = APIRouter(prefix="/members", tags=["members"])


def _require_gym_id(user: User) -> UUID:
    if user.gym_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not linked to a gym.")
    return user.gym_id


def _member_search_statement(gym_id: UUID, q: str | None = None) -> Select[tuple[Member]]:
    statement = select(Member).where(Member.gym_id == gym_id, Member.is_active.is_(True))
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Member.member_code.ilike(pattern),
                Member.first_name.ilike(pattern),
                Member.last_name.ilike(pattern),
                Member.email.ilike(pattern),
                Member.phone.ilike(pattern),
            )
        )
    return statement


def _get_member_for_gym_admin(db: Session, member_id: UUID, gym_id: UUID) -> Member:
    member = db.scalar(
        select(Member).where(
            Member.id == member_id,
            Member.gym_id == gym_id,
            Member.is_active.is_(True),
        )
    )
    if member is not None:
        return member

    other_tenant_member = db.scalar(
        select(Member.id).where(
            Member.id == member_id,
            Member.gym_id != gym_id,
            Member.is_active.is_(True),
        )
    )
    if other_tenant_member is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Member belongs to another gym.")

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member was not found.")


def _get_current_trainer(db: Session, current_user: User) -> Trainer | None:
    if current_user.role != RoleName.TRAINER.value or current_user.gym_id is None:
        return None

    return db.scalar(
        select(Trainer).where(
            Trainer.user_id == current_user.id,
            Trainer.gym_id == current_user.gym_id,
            Trainer.is_active.is_(True),
        )
    )


def _require_member_access(current_user: User) -> User:
    if current_user.role == RoleName.SUPER_ADMIN.value:
        return current_user
    if (
        has_permission(current_user, PermissionCode.MANAGE_MEMBERS)
        or has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE)
        or current_user.role == RoleName.TRAINER.value
    ):
        if current_user.gym_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not linked to a gym.")
        return current_user

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Member management access is required.")


@router.get("", response_model=list[MemberRead])
def list_members(
    q: str | None = Query(default=None, max_length=120),
    trainer_id: UUID | None = Query(default=None),
    gym_id: UUID | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_member_access(current_user)
    if current_user.role == RoleName.SUPER_ADMIN.value:
        statement = select(Member).where(Member.is_active.is_(True))
        if gym_id is not None:
            statement = statement.where(Member.gym_id == gym_id)
        if q:
            pattern = f"%{q.strip()}%"
            statement = statement.where(
                or_(
                    Member.member_code.ilike(pattern),
                    Member.first_name.ilike(pattern),
                    Member.last_name.ilike(pattern),
                    Member.email.ilike(pattern),
                    Member.phone.ilike(pattern),
                )
            )
    else:
        gym_id = _require_gym_id(current_user)
        statement = _member_search_statement(gym_id, q)

    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer profile is not configured.")
        statement = statement.where(Member.trainer_id == trainer.id)
    elif trainer_id is not None:
        statement = statement.where(Member.trainer_id == trainer_id)

    statement = statement.offset(skip).limit(min(limit, 200))
    return list(db.scalars(statement).all())


@router.post("", response_model=MemberRead, status_code=201)
def create_member(
    payload: MemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_MEMBERS)),
):
    gym_id = _require_gym_id(current_user)
    existing_member_code = db.scalar(
        select(Member.id).where(
            Member.gym_id == gym_id,
            Member.member_code == payload.member_code,
        )
    )
    if existing_member_code is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Member code already exists for this gym.")
    member_payload = payload.model_dump()
    return TenantRepository(Member, db, gym_id).create(member_payload, actor_id=current_user.id)


@router.get("/me", response_model=MemberRead)
def get_my_member_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> Member:
    gym_id = _require_gym_id(current_user)
    member = db.scalar(
        select(Member).where(
            Member.user_id == current_user.id,
            Member.gym_id == gym_id,
            Member.is_active.is_(True),
        )
    )
    if member is None:
        gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
        if gym is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")

        member = _ensure_member_profile_for_user(db, current_user, gym)
        db.commit()
        db.refresh(member)
    return member


@router.get("/search", response_model=list[MemberRead], deprecated=True)
def search_members(
    q: str = Query(min_length=1, max_length=120),
    trainer_id: UUID | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Member]:
    _require_member_access(current_user)
    gym_id = _require_gym_id(current_user)
    statement = _member_search_statement(gym_id, q)

    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer profile is not configured.")
        statement = statement.where(Member.trainer_id == trainer.id)
    elif trainer_id is not None:
        statement = statement.where(Member.trainer_id == trainer_id)

    statement = statement.offset(skip).limit(min(limit, 200))
    return list(db.scalars(statement).all())


@router.get("/{member_id}", response_model=MemberRead)
def get_member(
    member_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if has_permission(current_user, PermissionCode.MANAGE_MEMBERS):
        return _get_member_for_gym_admin(db, member_id, _require_gym_id(current_user))

    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer profile is not configured.")

        member = _get_member_for_gym_admin(db, member_id, _require_gym_id(current_user))
        if member.trainer_id != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only access assigned members.")
        return member

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Member access is denied.")


@router.patch("/{member_id}", response_model=MemberRead)
def update_member(
    member_id: UUID,
    payload: MemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_MEMBERS)),
):
    gym_id = _require_gym_id(current_user)
    repo = TenantRepository(Member, db, gym_id)
    member = _get_member_for_gym_admin(db, member_id, gym_id)
    member_payload = payload.model_dump(exclude_unset=True)
    return repo.update(
        member,
        member_payload,
        actor_id=current_user.id,
    )


@router.delete("/{member_id}", response_model=MessageResponse)
def delete_member(
    member_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_MEMBERS)),
) -> MessageResponse:
    gym_id = _require_gym_id(current_user)
    repo = TenantRepository(Member, db, gym_id)
    repo.deactivate(_get_member_for_gym_admin(db, member_id, gym_id), actor_id=current_user.id)
    return MessageResponse(message="Member was deactivated.")
