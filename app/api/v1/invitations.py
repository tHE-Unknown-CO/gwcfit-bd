from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.invitation import (
    InvitationCreateRequest,
    InvitationCreated,
    InvitationRead,
    InvitationValidateRequest,
    InvitationValidation,
)
from app.services import invitations as invitation_service

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("/validate", response_model=InvitationValidation)
def validate_invitation(payload: InvitationValidateRequest, db: Session = Depends(get_db)) -> InvitationValidation:
    return invitation_service.validate_invitation(db, payload.token)


@router.post("", response_model=InvitationCreated, status_code=201)
def create_invitation(
    payload: InvitationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvitationCreated:
    return invitation_service.create_invitation(db, current_user, payload)


@router.get("", response_model=list[InvitationRead])
def list_invitations(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InvitationRead]:
    return invitation_service.list_invitations(db, current_user, skip=skip, limit=limit)


@router.post("/{invitation_id}/revoke", response_model=InvitationRead)
def revoke_invitation(
    invitation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvitationRead:
    return invitation_service.revoke_invitation(db, current_user, invitation_id)
