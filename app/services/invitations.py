import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_token
from app.models.audit import AuditLog
from app.models.enums import GymStatus, InvitationStatus, RoleName
from app.models.gym import Gym
from app.models.invitation import Invitation
from app.models.user import User
from app.schemas.invitation import (
    InvitationCreateRequest,
    InvitationCreated,
    InvitationRead,
    InvitationValidation,
)

GYM_INVITABLE_ROLES = {
    RoleName.SUB_ADMIN,
    RoleName.TRAINER,
    RoleName.RECEPTIONIST,
    RoleName.MEMBER,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _fail(detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> None:
    raise HTTPException(status_code=code, detail=detail)


def _active_gym(db: Session, gym_id) -> Gym:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
    if gym is None:
        _fail("Gym was not found.", status.HTTP_404_NOT_FOUND)
    if gym.status != GymStatus.ACTIVE.value:
        _fail("Invitations are disabled while this gym is suspended.", status.HTTP_403_FORBIDDEN)
    return gym


def _normalize_status(invitation: Invitation) -> None:
    if invitation.status == InvitationStatus.ACTIVE.value and invitation.expires_at <= _now():
        invitation.status = InvitationStatus.EXPIRED.value
        invitation.is_active = False


def _read(invitation: Invitation) -> InvitationRead:
    return InvitationRead(
        id=invitation.id,
        gym_id=invitation.gym_id,
        gym_name=invitation.gym.name if invitation.gym else None,
        role=RoleName(invitation.role),
        email=invitation.email,
        status=InvitationStatus(invitation.status),
        expires_at=invitation.expires_at,
        use_count=invitation.use_count,
        max_uses=invitation.max_uses,
        created_at=invitation.created_at,
        created_by=invitation.created_by,
        used_at=invitation.used_at,
        used_by=invitation.used_by,
        # Raw invitation tokens are returned only once by the create endpoint.
        # List/read responses deliberately never re-expose bearer credentials.
        token=None,
    )


def _audit(db: Session, invitation: Invitation, actor_id, action: str) -> None:
    db.add(
        AuditLog(
            gym_id=invitation.gym_id,
            actor_user_id=actor_id,
            action=action,
            resource_type="invitation",
            resource_id=invitation.id,
            extra_data={"role": invitation.role, "email": invitation.email},
            created_by=actor_id,
            updated_by=actor_id,
        )
    )


def create_invitation(db: Session, actor: User, payload: InvitationCreateRequest) -> InvitationCreated:
    actor_role = RoleName(actor.role)
    if actor_role == RoleName.SUPER_ADMIN:
        if payload.role != RoleName.GYM_OWNER:
            _fail("Application owners can only invite gym owners.", status.HTTP_403_FORBIDDEN)
        gym = None
    elif actor_role == RoleName.GYM_OWNER:
        if payload.role not in GYM_INVITABLE_ROLES:
            _fail("Gym owners can only invite gym-scoped users.", status.HTTP_403_FORBIDDEN)
        if actor.gym_id is None:
            _fail("Gym owner account is not assigned to a gym.", status.HTTP_409_CONFLICT)
        gym = _active_gym(db, actor.gym_id)
    else:
        _fail("Only the application owner or a gym owner can create invitations.", status.HTTP_403_FORBIDDEN)

    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(
        gym_id=gym.id if gym else None,
        role=payload.role.value,
        email=str(payload.email).lower() if payload.email else None,
        token_hash=hash_token(raw_token),
        expires_at=_now() + timedelta(hours=payload.expires_in_hours),
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(invitation)
    db.flush()
    _audit(db, invitation, actor.id, "invitation.created")
    db.commit()
    db.refresh(invitation)
    result = _read(invitation)
    return InvitationCreated(**result.model_dump(exclude={"token"}), token=raw_token)


def list_invitations(
    db: Session, actor: User, *, skip: int = 0, limit: int = 50
) -> list[InvitationRead]:
    actor_role = RoleName(actor.role)
    statement = (
        select(Invitation)
        .order_by(Invitation.created_at.desc())
        .offset(skip)
        .limit(min(limit, 200))
    )
    if actor_role == RoleName.GYM_OWNER:
        if actor.gym_id is None:
            return []
        statement = statement.where(Invitation.gym_id == actor.gym_id)
    elif actor_role != RoleName.SUPER_ADMIN:
        _fail("Only the application owner or a gym owner can view invitations.", status.HTTP_403_FORBIDDEN)

    invitations = list(db.scalars(statement).all())
    changed = False
    for invitation in invitations:
        old_status = invitation.status
        _normalize_status(invitation)
        changed = changed or old_status != invitation.status
    if changed:
        db.commit()
    return [_read(invitation) for invitation in invitations]


def revoke_invitation(db: Session, actor: User, invitation_id) -> InvitationRead:
    invitation = db.scalar(select(Invitation).where(Invitation.id == invitation_id).with_for_update())
    if invitation is None:
        _fail("Invitation was not found.", status.HTTP_404_NOT_FOUND)
    actor_role = RoleName(actor.role)
    if actor_role != RoleName.SUPER_ADMIN and not (
        actor_role == RoleName.GYM_OWNER and actor.gym_id == invitation.gym_id
    ):
        _fail("You cannot revoke this invitation.", status.HTTP_403_FORBIDDEN)
    _normalize_status(invitation)
    if invitation.status != InvitationStatus.ACTIVE.value:
        _fail("Only active invitations can be revoked.", status.HTTP_409_CONFLICT)
    invitation.status = InvitationStatus.REVOKED.value
    invitation.is_active = False
    invitation.updated_by = actor.id
    _audit(db, invitation, actor.id, "invitation.revoked")
    db.commit()
    db.refresh(invitation)
    return _read(invitation)


def get_valid_invitation(db: Session, token: str, *, lock: bool = False) -> Invitation:
    statement = select(Invitation).where(Invitation.token_hash == hash_token(token.strip()))
    if lock:
        statement = statement.with_for_update()
    invitation = db.scalar(statement)
    if invitation is None:
        _fail("Invitation token is invalid.")
    _normalize_status(invitation)
    if invitation.status != InvitationStatus.ACTIVE.value or not invitation.is_active:
        _fail(f"Invitation is {invitation.status}.")
    if invitation.use_count >= invitation.max_uses:
        invitation.status = InvitationStatus.USED.value
        invitation.is_active = False
        _fail("Invitation has already been used.")
    if invitation.gym_id is not None:
        _active_gym(db, invitation.gym_id)
    return invitation


def validate_invitation(db: Session, token: str) -> InvitationValidation:
    invitation = get_valid_invitation(db, token)
    return InvitationValidation(
        role=RoleName(invitation.role),
        gym_id=invitation.gym_id,
        gym_name=invitation.gym.name if invitation.gym else None,
        email=invitation.email,
        expires_at=invitation.expires_at,
    )


def consume_invitation(db: Session, token: str, email: str, expected_role: RoleName) -> Invitation:
    invitation = get_valid_invitation(db, token, lock=True)
    if RoleName(invitation.role) != expected_role:
        _fail("Invitation is not valid for this account type.", status.HTTP_403_FORBIDDEN)
    if invitation.email and invitation.email.lower() != email.lower():
        _fail("Invitation was issued to a different email address.", status.HTTP_403_FORBIDDEN)
    return invitation


def mark_consumed(db: Session, invitation: Invitation, user: User) -> None:
    invitation.use_count += 1
    invitation.used_at = _now()
    invitation.used_by = user.id
    invitation.updated_by = user.id
    invitation.status = InvitationStatus.USED.value
    invitation.is_active = False
    _audit(db, invitation, user.id, "invitation.accepted")
