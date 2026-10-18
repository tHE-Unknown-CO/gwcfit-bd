from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.permissions import require_super_admin
from app.models.audit import AuditLog
from app.models.platform_plan import PlatformPlan
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.platform_plan import PlatformPlanCreate, PlatformPlanRead, PlatformPlanUpdate

router = APIRouter(prefix="/platform-plans", tags=["platform-plans"])


def _ordered(active_only: bool = False):
    statement = select(PlatformPlan)
    if active_only:
        statement = statement.where(PlatformPlan.is_active.is_(True))
    return statement.order_by(PlatformPlan.display_order.asc(), PlatformPlan.name.asc())


@router.get("/public", response_model=list[PlatformPlanRead])
def public_platform_plans(
    limit: int = Query(default=50, ge=1, le=100), db: Session = Depends(get_db)
) -> list[PlatformPlan]:
    return list(db.scalars(_ordered(active_only=True).limit(limit)).all())


@router.get("", response_model=list[PlatformPlanRead])
def list_platform_plans(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> list[PlatformPlan]:
    return list(db.scalars(_ordered().offset(skip).limit(limit)).all())


@router.post("", response_model=PlatformPlanRead, status_code=201)
def create_platform_plan(
    payload: PlatformPlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformPlan:
    plan = PlatformPlan(**payload.model_dump(), created_by=current_user.id, updated_by=current_user.id)
    db.add(plan)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A platform plan with this slug already exists.") from exc
    db.refresh(plan)
    return plan


@router.patch("/{plan_id}", response_model=PlatformPlanRead)
def update_platform_plan(
    plan_id: UUID,
    payload: PlatformPlanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformPlan:
    plan = db.scalar(select(PlatformPlan).where(PlatformPlan.id == plan_id).with_for_update())
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform plan was not found.")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(plan, field, value)
    plan.updated_by = current_user.id
    db.add(
        AuditLog(
            gym_id=None,
            actor_user_id=current_user.id,
            action="platform_plan.updated",
            resource_type="platform_plan",
            resource_id=plan.id,
            extra_data={"changed_fields": sorted(changes)},
            created_by=current_user.id,
            updated_by=current_user.id,
        )
    )
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}", response_model=MessageResponse)
def delete_platform_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> MessageResponse:
    plan = db.scalar(select(PlatformPlan).where(PlatformPlan.id == plan_id).with_for_update())
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform plan was not found.")
    plan.is_active = False
    plan.updated_by = current_user.id
    db.commit()
    return MessageResponse(message="Platform plan was removed from public pricing.")
