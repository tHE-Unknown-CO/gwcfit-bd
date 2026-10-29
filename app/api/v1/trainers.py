from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1._crud import get_or_404
from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import require_permission
from app.dependencies.tenant import get_current_gym_id
from app.models.enums import PermissionCode
from app.models.member import Member
from app.models.trainer import Trainer
from app.models.trainer_feedback import TrainerFeedback
from app.models.user import User
from app.permissions.rbac import has_permission
from app.repositories.base import TenantRepository
from app.schemas.common import MessageResponse
from app.schemas.trainer import TrainerCreate, TrainerRead, TrainerUpdate
from app.schemas.trainer_feedback import TrainerFeedbackRead, TrainerRatingSummary

router = APIRouter(prefix="/trainers", tags=["trainers"])


def _attach_rating_summaries(db: Session, trainers: list[Trainer], gym_id: UUID) -> list[Trainer]:
    if not trainers:
        return trainers
    aggregates = db.execute(
        select(TrainerFeedback.trainer_id, func.avg(TrainerFeedback.rating), func.count(TrainerFeedback.id))
        .where(
            TrainerFeedback.gym_id == gym_id,
            TrainerFeedback.trainer_id.in_([trainer.id for trainer in trainers]),
            TrainerFeedback.is_active.is_(True),
        )
        .group_by(TrainerFeedback.trainer_id)
    ).all()
    ratings = {trainer_id: (float(average), int(total)) for trainer_id, average, total in aggregates}
    for trainer in trainers:
        average, total = ratings.get(trainer.id, (0.0, 0))
        trainer.average_rating = round(average, 1)
        trainer.total_reviews = total
    return trainers


@router.get("/{trainer_id}/feedback", response_model=TrainerRatingSummary)
def get_trainer_feedback(
    trainer_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    _: User = Depends(require_permission(PermissionCode.MANAGE_TRAINERS)),
):
    get_or_404(TenantRepository(Trainer, db, gym_id), trainer_id, "Trainer")
    rows = list(db.scalars(select(TrainerFeedback).where(
        TrainerFeedback.gym_id == gym_id, TrainerFeedback.trainer_id == trainer_id,
        TrainerFeedback.is_active.is_(True),
    ).order_by(TrainerFeedback.created_at.desc()).limit(200)).all())
    distribution = {star: 0 for star in range(1, 6)}
    for row in rows:
        distribution[row.rating] += 1
    members = {member.id: member.member_name for member in db.scalars(select(Member).where(
        Member.gym_id == gym_id, Member.id.in_([row.member_id for row in rows]),
    )).all()} if rows else {}
    reviews = [TrainerFeedbackRead(id=row.id, trainer_id=row.trainer_id, member_id=row.member_id,
        member_name=members.get(row.member_id, "Former member"), review_month=row.review_month, rating=row.rating,
        feedback_option=row.feedback_option, feedback_text=row.feedback_text, created_at=row.created_at, updated_at=row.updated_at) for row in rows]
    return TrainerRatingSummary(average_rating=round(sum(row.rating for row in rows) / len(rows), 1) if rows else 0,
                                total_reviews=len(rows), star_distribution=distribution, reviews=reviews)


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
    return _attach_rating_summaries(db, TenantRepository(Trainer, db, gym_id).list(skip=skip, limit=limit), gym_id)


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
    return _attach_rating_summaries(db, [get_or_404(TenantRepository(Trainer, db, gym_id), trainer_id, "Trainer")], gym_id)[0]


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
