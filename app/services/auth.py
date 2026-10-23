from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.gym_access import require_active_gym

from app.auth.jwt import create_token, decode_token
from app.auth.passwords import hash_password, hash_token, verify_password, verify_token
from app.core.config import get_settings
from app.models.enums import GymStatus, RoleName
from app.models.gym import Gym
from app.models.gym_inquiry import GymInquiry
from app.models.login_event import LoginEvent
from app.models.member import Member
from app.models.billing import Subscription
from app.models.platform_plan import PlatformPlan
from app.models.trainer import Trainer
from app.models.user import User
from app.permissions.rbac import get_effective_permissions
from app.schemas.auth import (
    AuthenticatedUser,
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordResponse,
    GymUserRegistrationRequest,
    LoginRequest,
    OwnerRegistrationRequest,
    RefreshTokenRequest,
    TokenPair,
)
from app.utils.codes import generate_gym_code, generate_token
from app.services import invitations as invitation_service

settings = get_settings()


def _public_user(user: User) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        gym_id=user.gym_id,
        gym_name=user.gym_name,
        email=user.email,
        full_name=user.full_name,
        role=RoleName(user.role),
        permissions=sorted(get_effective_permissions(user), key=lambda permission: permission.value),
    )


def get_authenticated_user(user: User) -> AuthenticatedUser:
    return _public_user(user)


def _issue_tokens(user: User) -> TokenPair:
    permissions = [permission.value for permission in get_effective_permissions(user)]
    access_token = create_token(
        subject=user.id,
        gym_id=user.gym_id,
        role=user.role,
        token_type="access",
        permissions=permissions,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh_token = create_token(
        subject=user.id,
        gym_id=user.gym_id,
        role=user.role,
        token_type="refresh",
        permissions=permissions,
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


def _existing_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def _split_member_name(full_name: str) -> tuple[str, str]:
    normalized = " ".join(full_name.split())
    if not normalized:
        return "Member", ""

    first_name, _, last_name = normalized.partition(" ")
    return first_name, last_name


def _member_code_for_user(user: User) -> str:
    return f"MBR-{user.id.hex.upper()}"


def _ensure_member_profile_for_user(db: Session, user: User, gym: Gym) -> Member:
    member = db.scalar(
        select(Member).where(
            Member.gym_id == gym.id,
            Member.user_id == user.id,
            Member.is_active.is_(True),
        )
    )
    if member is not None:
        return member

    member = db.scalar(
        select(Member).where(
            Member.gym_id == gym.id,
            func.lower(Member.email) == user.email.lower(),
            Member.user_id.is_(None),
            Member.is_active.is_(True),
        )
    )
    if member is not None:
        member.user_id = user.id
        member.updated_by = user.id
        return member

    first_name, last_name = _split_member_name(user.full_name)
    member = Member(
        gym_id=gym.id,
        user_id=user.id,
        member_code=_member_code_for_user(user),
        first_name=first_name,
        last_name=last_name,
        email=user.email,
        phone=getattr(user, "phone", None),
        status="active",
        joined_at=datetime.now(UTC),
        emergency_contact={},
        extra_data={},
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(member)
    return member


def _ensure_trainer_profile_for_user(db: Session, user: User, gym: Gym) -> Trainer:
    trainer = db.scalar(
        select(Trainer).where(
            Trainer.gym_id == gym.id,
            Trainer.user_id == user.id,
            Trainer.is_active.is_(True),
        )
    )
    if trainer is not None:
        return trainer

    trainer = db.scalar(
        select(Trainer).where(
            Trainer.gym_id == gym.id,
            func.lower(Trainer.email) == user.email.lower(),
            Trainer.user_id.is_(None),
            Trainer.is_active.is_(True),
        )
    )
    if trainer is not None:
        trainer.user_id = user.id
        trainer.updated_by = user.id
        return trainer

    trainer = Trainer(
        gym_id=gym.id,
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone=getattr(user, "phone", None),
        specialties=[],
        hourly_rate_cents=0,
        commission_rate=0,
        extra_data={},
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(trainer)
    return trainer


def list_gym_options(db: Session) -> list[Gym]:
    statement = (
        select(Gym)
        .where(Gym.is_active.is_(True), Gym.status == GymStatus.ACTIVE.value)
        .order_by(Gym.name.asc())
        .limit(200)
    )
    return list(db.scalars(statement).all())


def register_owner(db: Session, payload: OwnerRegistrationRequest) -> AuthResponse:
    if _existing_user(db, payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    invitation = invitation_service.consume_invitation(
        db, payload.invitation_token, payload.email, RoleName.GYM_OWNER
    )
    if invitation.gym_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Gym owner invitations cannot be assigned to an existing gym.",
        )

    gym = Gym(
        name=payload.gym_name,
        code=generate_gym_code(payload.gym_name),
        email=payload.email,
        phone=payload.phone,
    )
    db.add(gym)
    db.flush()

    owner = User(
        gym_id=gym.id,
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=RoleName.GYM_OWNER.value,
        phone=payload.phone,
        is_email_verified=False,
    )
    db.add(owner)
    db.flush()

    invitation_service.mark_consumed(db, invitation, owner)

    inquiry = db.scalar(select(GymInquiry).where(GymInquiry.invitation_id == invitation.id).with_for_update())
    selected_plan_id = inquiry.interested_plan_id if inquiry else None
    plan = db.scalar(select(PlatformPlan).where(PlatformPlan.id == selected_plan_id)) if selected_plan_id else None
    if plan is None:
        plan = db.scalar(select(PlatformPlan).where(PlatformPlan.slug == "launch", PlatformPlan.is_active.is_(True)))
    if plan is not None:
        trial_started_at = datetime.now(UTC)
        db.add(Subscription(
            gym_id=gym.id,
            platform_plan_id=plan.id,
            plan_name=plan.name,
            status="trialing",
            amount_cents=plan.price_cents or 0,
            trial_started_at=trial_started_at,
            current_period_ends_at=trial_started_at + timedelta(days=plan.trial_days),
            limits={"member_limit": plan.member_limit},
            created_by=owner.id,
            updated_by=owner.id,
        ))
    if inquiry is not None:
        inquiry.status = "converted"
        inquiry.gym_id = gym.id
        inquiry.updated_by = owner.id

    gym.created_by = owner.id
    gym.updated_by = owner.id
    tokens = _issue_tokens(owner)
    owner.refresh_token_hash = hash_token(tokens.refresh_token)
    db.commit()
    db.refresh(owner)
    return AuthResponse(user=_public_user(owner), tokens=tokens)


def register_existing_gym_user(db: Session, payload: GymUserRegistrationRequest) -> AuthResponse:
    if _existing_user(db, payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    invitation = invitation_service.get_valid_invitation(db, payload.invitation_token, lock=True)
    invitation_role = RoleName(invitation.role)
    if invitation_role not in invitation_service.GYM_INVITABLE_ROLES or invitation.gym_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invitation is not valid for a gym user.")
    if payload.role is not None and payload.role != invitation_role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invitation does not grant the requested role.")
    if invitation.email and invitation.email.lower() != payload.email.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invitation was issued to a different email address.")
    gym = db.scalar(
        select(Gym).where(
            Gym.id == invitation.gym_id,
            Gym.is_active.is_(True),
            Gym.status == GymStatus.ACTIVE.value,
        )
    )
    if gym is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The invited gym is unavailable.")

    user = User(
        gym_id=gym.id,
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=invitation_role.value,
    )
    db.add(user)
    db.flush()
    if invitation_role == RoleName.MEMBER:
        _ensure_member_profile_for_user(db, user, gym)
    elif invitation_role == RoleName.TRAINER:
        _ensure_trainer_profile_for_user(db, user, gym)

    invitation_service.mark_consumed(db, invitation, user)

    require_active_gym(db, user)
    tokens = _issue_tokens(user)
    user.refresh_token_hash = hash_token(tokens.refresh_token)
    db.commit()
    db.refresh(user)
    return AuthResponse(user=_public_user(user), tokens=tokens)


def _record_login(
    db: Session,
    *,
    email: str,
    user: User | None,
    success: bool,
    failure_reason: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    db.add(LoginEvent(
        user_id=user.id if user else None,
        email=email.lower(),
        role=user.role if user else None,
        success=success,
        failure_reason=failure_reason,
        ip_address=ip_address,
        user_agent=user_agent,
    ))


def login(
    db: Session,
    payload: LoginRequest,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuthResponse:
    user = _existing_user(db, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        _record_login(
            db, email=str(payload.email), user=user, success=False,
            failure_reason="invalid_credentials", ip_address=ip_address, user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    if not user.is_active:
        _record_login(
            db, email=user.email, user=user, success=False,
            failure_reason="inactive_account", ip_address=ip_address, user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive.")

    require_active_gym(db, user)
    tokens = _issue_tokens(user)
    user.refresh_token_hash = hash_token(tokens.refresh_token)
    _record_login(
        db, email=user.email, user=user, success=True, failure_reason=None,
        ip_address=ip_address, user_agent=user_agent,
    )
    db.commit()
    db.refresh(user)
    return AuthResponse(user=_public_user(user), tokens=tokens)


def refresh(db: Session, payload: RefreshTokenRequest) -> TokenPair:
    token_payload = decode_token(payload.refresh_token, expected_type="refresh")
    try:
        user_id = UUID(token_payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is invalid.") from exc
    user = db.scalar(
        select(User).where(User.id == user_id, User.is_active.is_(True)).with_for_update()
    )
    if user is None or not user.refresh_token_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is invalid.")
    if not verify_token(payload.refresh_token, user.refresh_token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is invalid.")

    require_active_gym(db, user)
    tokens = _issue_tokens(user)
    user.refresh_token_hash = hash_token(tokens.refresh_token)
    db.commit()
    return tokens


def logout(db: Session, user: User) -> None:
    user.refresh_token_hash = None
    db.commit()


def forgot_password(db: Session, email: str) -> ForgotPasswordResponse:
    user = _existing_user(db, email)
    if user is None or user.role == RoleName.SUPER_ADMIN.value:
        return ForgotPasswordResponse(message="If the account exists, password reset instructions were sent.")

    token = generate_token()
    user.password_reset_token_hash = hash_token(token)
    user.password_reset_token_expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.password_reset_token_expire_minutes
    )
    db.commit()
    return ForgotPasswordResponse(
        message="Password reset token generated. Send it through email in production.",
        reset_token=token if settings.environment == "local" else None,
    )


def reset_password(db: Session, token: str, new_password: str) -> None:
    token_hash = hash_token(token.strip())
    user = db.scalar(
        select(User)
        .where(
            User.password_reset_token_hash == token_hash,
            User.password_reset_token_expires_at > datetime.now(UTC),
            User.role != RoleName.SUPER_ADMIN.value,
            User.is_active.is_(True),
        )
        .with_for_update()
    )
    if user is not None and verify_token(token.strip(), user.password_reset_token_hash):
        user.hashed_password = hash_password(new_password)
        user.password_reset_token_hash = None
        user.password_reset_token_expires_at = None
        user.refresh_token_hash = None
        db.commit()
        return
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token is invalid or expired.")


def change_password(db: Session, user: User, payload: ChangePasswordRequest) -> None:
    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Old password is incorrect.")
    user.hashed_password = hash_password(payload.new_password)
    user.refresh_token_hash = None
    db.commit()


def verify_email(db: Session, token: str) -> None:
    token_hash = hash_token(token.strip())
    user = db.scalar(
        select(User)
        .where(
            User.email_verification_token_hash == token_hash,
            User.email_verification_token_expires_at > datetime.now(UTC),
            User.is_active.is_(True),
        )
        .with_for_update()
    )
    if user is not None and verify_token(token.strip(), user.email_verification_token_hash):
        user.is_email_verified = True
        user.email_verification_token_hash = None
        user.email_verification_token_expires_at = None
        db.commit()
        return
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification token is invalid or expired.")
