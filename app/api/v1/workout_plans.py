from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1._crud import ensure_assigned_member, get_or_404
from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import require_permission
from app.dependencies.tenant import get_current_gym_id
from app.models.enums import PermissionCode, RoleName
from app.models.plans import WorkoutPlan
from app.models.trainer import Trainer
from app.models.user import User
from app.permissions.rbac import has_permission
from app.repositories.base import TenantRepository
from app.schemas.common import MessageResponse
from app.schemas.plans import WorkoutPlanCreate, WorkoutPlanRead, WorkoutPlanUpdate

router = APIRouter(prefix="/workout-plans", tags=["workout plans"])


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


def _apply_trainer_filter(statement, current_user: User, db: Session):
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer profile is not configured.")
        return statement.where(WorkoutPlan.trainer_id == trainer.id)
    return statement


@router.get("", response_model=list[WorkoutPlanRead])
def list_workout_plans(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_WORKOUTS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workout access is required.")

    statement = TenantRepository(WorkoutPlan, db, gym_id).base_query()
    statement = _apply_trainer_filter(statement, current_user, db)
    statement = statement.offset(skip).limit(min(limit, 200))
    return list(db.scalars(statement).all())


@router.post("", response_model=WorkoutPlanRead, status_code=201)
def create_workout_plan(
    payload: WorkoutPlanCreate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_WORKOUTS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workout access is required.")

    payload_data = payload.model_dump()
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer profile is not configured.")
        if payload_data.get("trainer_id") and payload_data["trainer_id"] != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only assign workouts to themselves.")
        payload_data["trainer_id"] = trainer.id
        ensure_assigned_member(db, payload.member_id, trainer.id, gym_id)

    return TenantRepository(WorkoutPlan, db, gym_id).create(payload_data, actor_id=current_user.id)


@router.get("/{plan_id}", response_model=WorkoutPlanRead)
def get_workout_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_WORKOUTS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workout access is required.")

    plan = get_or_404(TenantRepository(WorkoutPlan, db, gym_id), plan_id, "Workout plan")
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None or plan.trainer_id != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only access assigned workouts.")
    return plan


@router.patch("/{plan_id}", response_model=WorkoutPlanRead)
def update_workout_plan(
    plan_id: UUID,
    payload: WorkoutPlanUpdate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_WORKOUTS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workout access is required.")

    repo = TenantRepository(WorkoutPlan, db, gym_id)
    plan = get_or_404(repo, plan_id, "Workout plan")
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None or plan.trainer_id != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only edit assigned workouts.")
        payload_data = payload.model_dump(exclude_unset=True)
        if "trainer_id" in payload_data and payload_data["trainer_id"] != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only assign workouts to themselves.")
    else:
        payload_data = payload.model_dump(exclude_unset=True)

    return repo.update(plan, payload_data, actor_id=current_user.id)


@router.delete("/{plan_id}", response_model=MessageResponse)
def delete_workout_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    if not has_permission(current_user, PermissionCode.MANAGE_WORKOUTS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workout access is required.")

    repo = TenantRepository(WorkoutPlan, db, gym_id)
    plan = get_or_404(repo, plan_id, "Workout plan")
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None or plan.trainer_id != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only delete assigned workouts.")

    repo.deactivate(plan, actor_id=current_user.id)
    return MessageResponse(message="Workout plan was deactivated.")
