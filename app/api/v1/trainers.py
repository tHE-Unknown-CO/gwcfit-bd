from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1._crud import get_or_404
from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import require_permission
from app.dependencies.tenant import get_current_gym_id
from app.models.enums import PermissionCode
from app.models.trainer import Trainer
from app.models.user import User
from app.permissions.rbac import has_permission
from app.repositories.base import TenantRepository
from app.schemas.common import MessageResponse
from app.schemas.trainer import TrainerCreate, TrainerRead, TrainerUpdate

router = APIRouter(prefix="/trainers", tags=["trainers"])


@router.get("", response_model=list[TrainerRead])
def list_trainers(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not (
        has_permission(current_user, PermissionCode.MANAGE_TRAINERS)
        or has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer or attendance access is required.")
    return TenantRepository(Trainer, db, gym_id).list(skip=skip, limit=limit)


@router.post("", response_model=TrainerRead, status_code=201)
def create_trainer(
    payload: TrainerCreate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_TRAINERS)),
):
    return TenantRepository(Trainer, db, gym_id).create(payload.model_dump(), actor_id=current_user.id)


@router.get("/{trainer_id}", response_model=TrainerRead)
def get_trainer(
    trainer_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    _: User = Depends(require_permission(PermissionCode.MANAGE_TRAINERS)),
):
    return get_or_404(TenantRepository(Trainer, db, gym_id), trainer_id, "Trainer")


@router.patch("/{trainer_id}", response_model=TrainerRead)
def update_trainer(
    trainer_id: UUID,
    payload: TrainerUpdate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_TRAINERS)),
):
    repo = TenantRepository(Trainer, db, gym_id)
    return repo.update(get_or_404(repo, trainer_id, "Trainer"), payload.model_dump(exclude_unset=True), actor_id=current_user.id)


@router.delete("/{trainer_id}", response_model=MessageResponse)
def delete_trainer(
    trainer_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_TRAINERS)),
) -> MessageResponse:
    repo = TenantRepository(Trainer, db, gym_id)
    repo.deactivate(get_or_404(repo, trainer_id, "Trainer"), actor_id=current_user.id)
    return MessageResponse(message="Trainer was deactivated.")
