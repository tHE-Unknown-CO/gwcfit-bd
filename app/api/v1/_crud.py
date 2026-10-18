from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.member import Member
from app.repositories.base import TenantRepository


def get_or_404(repo: TenantRepository, resource_id: UUID, label: str):
    record = repo.get(resource_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} was not found.")
    return record


def ensure_assigned_member(db: Session, member_id: UUID, trainer_id: UUID, gym_id: UUID) -> None:
    member_id = db.scalar(select(Member.id).where(
        Member.id == member_id,
        Member.gym_id == gym_id,
        Member.trainer_id == trainer_id,
        Member.is_active.is_(True),
    ))
    if member_id is None:
        raise HTTPException(status_code=403, detail="Trainer may only manage plans for assigned members.")
