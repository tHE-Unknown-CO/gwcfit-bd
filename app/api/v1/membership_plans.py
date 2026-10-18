from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1._crud import get_or_404
from app.database.session import get_db
from app.dependencies.permissions import require_permission
from app.dependencies.tenant import get_current_gym_id, get_optional_gym_id
from app.models.enums import PermissionCode
from app.models.plans import MembershipPlan
from app.models.user import User
from app.repositories.base import TenantRepository
from app.schemas.common import MessageResponse
from app.schemas.plans import MembershipPlanCreate, MembershipPlanRead, MembershipPlanUpdate

router = APIRouter(prefix="/membership-plans", tags=["membership plans"])


@router.get("", response_model=list[MembershipPlanRead])
def list_membership_plans(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    gym_id: UUID | None = Depends(get_optional_gym_id),
    _: User = Depends(require_permission(PermissionCode.MANAGE_MEMBERSHIP_PLANS)),
):
    if gym_id is None:
        statement = (
            select(MembershipPlan)
            .where(MembershipPlan.is_active.is_(True))
            .order_by(MembershipPlan.created_at.desc())
            .offset(skip)
            .limit(min(limit, 200))
        )
        return list(db.scalars(statement).all())
    return TenantRepository(MembershipPlan, db, gym_id).list(skip=skip, limit=limit)


@router.post("", response_model=MembershipPlanRead, status_code=201)
def create_membership_plan(
    payload: MembershipPlanCreate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_MEMBERSHIP_PLANS)),
):
    return TenantRepository(MembershipPlan, db, gym_id).create(payload.model_dump(), actor_id=current_user.id)


@router.get("/{plan_id}", response_model=MembershipPlanRead)
def get_membership_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    _: User = Depends(require_permission(PermissionCode.MANAGE_MEMBERSHIP_PLANS)),
):
    return get_or_404(TenantRepository(MembershipPlan, db, gym_id), plan_id, "Membership plan")


@router.patch("/{plan_id}", response_model=MembershipPlanRead)
def update_membership_plan(
    plan_id: UUID,
    payload: MembershipPlanUpdate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_MEMBERSHIP_PLANS)),
):
    repo = TenantRepository(MembershipPlan, db, gym_id)
    return repo.update(get_or_404(repo, plan_id, "Membership plan"), payload.model_dump(exclude_unset=True), actor_id=current_user.id)


@router.delete("/{plan_id}", response_model=MessageResponse)
def delete_membership_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_MEMBERSHIP_PLANS)),
) -> MessageResponse:
    repo = TenantRepository(MembershipPlan, db, gym_id)
    repo.deactivate(get_or_404(repo, plan_id, "Membership plan"), actor_id=current_user.id)
    return MessageResponse(message="Membership plan was deactivated.")
