from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.permissions import require_super_admin
from app.models.audit import AuditLog
from app.models.billing import Subscription
from app.models.enums import RoleName
from app.models.gym import Gym
from app.models.gym_inquiry import GymInquiry
from app.models.invitation import Invitation
from app.models.login_event import LoginEvent
from app.models.member import Member
from app.models.platform_plan import PlatformPlan
from app.models.trainer import Trainer
from app.models.user import User
from app.schemas.developer_portal import (
    DeveloperGymRead,
    GymInquiryCreate,
    GymInquiryRead,
    GymInquiryUpdate,
    GymSubscriptionRead,
    GymSubscriptionUpdate,
    LoginEventRead,
)
from app.schemas.invitation import InvitationCreateRequest, InvitationCreated
from app.services import invitations as invitation_service

router = APIRouter(tags=["developer-portal"])


def _inquiry_read(
    db: Session,
    inquiry: GymInquiry,
    plan_names: dict[UUID, str] | None = None,
) -> GymInquiryRead:
    plan_name = plan_names.get(inquiry.interested_plan_id) if plan_names and inquiry.interested_plan_id else None
    if plan_name is None and inquiry.interested_plan_id and plan_names is None:
        plan_name = db.scalar(select(PlatformPlan.name).where(PlatformPlan.id == inquiry.interested_plan_id))
    return GymInquiryRead(
        id=inquiry.id, full_name=inquiry.full_name, email=inquiry.email, phone=inquiry.phone,
        gym_name=inquiry.gym_name,
        active_members_range=inquiry.active_members_range, interested_plan_id=inquiry.interested_plan_id,
        interested_plan_name=plan_name, status=inquiry.status, invitation_id=inquiry.invitation_id,
        gym_id=inquiry.gym_id, notes=inquiry.notes, source=inquiry.source,
        created_at=inquiry.created_at, updated_at=inquiry.updated_at,
    )


def _audit(db: Session, actor: User, action: str, resource_type: str, resource_id: UUID, details: dict) -> None:
    serialized_details = {key: str(value) if isinstance(value, UUID) else value for key, value in details.items()}
    db.add(AuditLog(
        gym_id=details.get("gym_id"), actor_user_id=actor.id, action=action,
        resource_type=resource_type, resource_id=resource_id, extra_data=serialized_details,
        created_by=actor.id, updated_by=actor.id,
    ))


@router.post("/gym-inquiries", response_model=GymInquiryRead, status_code=201)
def create_gym_inquiry(payload: GymInquiryCreate, db: Session = Depends(get_db)) -> GymInquiryRead:
    email = str(payload.email).lower()
    phone_digits = payload.phone.lstrip("+")
    duplicate_inquiry = db.scalar(select(GymInquiry.id).where(or_(
        func.lower(GymInquiry.email) == email,
        func.regexp_replace(GymInquiry.phone, "[^0-9]", "", "g") == phone_digits,
    )))
    duplicate_user = db.scalar(select(User.id).where(or_(
        func.lower(User.email) == email,
        func.regexp_replace(User.phone, "[^0-9]", "", "g") == phone_digits,
    )))
    duplicate_gym = db.scalar(select(Gym.id).where(or_(
        func.lower(Gym.email) == email,
        func.regexp_replace(Gym.phone, "[^0-9]", "", "g") == phone_digits,
    )))
    if duplicate_inquiry or duplicate_user or duplicate_gym:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A gym or gym inquiry already exists with this email or mobile number.",
        )
    if payload.interested_plan_id:
        plan = db.scalar(select(PlatformPlan).where(
            PlatformPlan.id == payload.interested_plan_id, PlatformPlan.is_active.is_(True)
        ))
        if plan is None:
            raise HTTPException(status_code=400, detail="The selected plan is not available.")
    inquiry = GymInquiry(
        full_name=payload.full_name, email=email, phone=payload.phone, gym_name=payload.gym_name,
        active_members_range=payload.active_members_range, interested_plan_id=payload.interested_plan_id,
        source=payload.source,
    )
    db.add(inquiry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A gym or gym inquiry already exists with this email or mobile number.",
        ) from None
    db.refresh(inquiry)
    return _inquiry_read(db, inquiry)


@router.get("/developer/inquiries", response_model=list[GymInquiryRead])
def list_gym_inquiries(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> list[GymInquiryRead]:
    inquiries = list(
        db.scalars(
            select(GymInquiry)
            .order_by(GymInquiry.created_at.desc())
            .offset(skip)
            .limit(limit)
        ).all()
    )
    plan_ids = {inquiry.interested_plan_id for inquiry in inquiries if inquiry.interested_plan_id}
    plan_names = dict(
        db.execute(select(PlatformPlan.id, PlatformPlan.name).where(PlatformPlan.id.in_(plan_ids))).all()
    ) if plan_ids else {}
    return [_inquiry_read(db, inquiry, plan_names) for inquiry in inquiries]


@router.get("/developer/login-events", response_model=list[LoginEventRead])
def list_login_events(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> list[LoginEvent]:
    statement = select(LoginEvent).order_by(LoginEvent.created_at.desc()).limit(min(max(limit, 1), 500))
    return list(db.scalars(statement).all())


@router.patch("/developer/inquiries/{inquiry_id}", response_model=GymInquiryRead)
def update_gym_inquiry(
    inquiry_id: UUID, payload: GymInquiryUpdate, db: Session = Depends(get_db),
    actor: User = Depends(require_super_admin),
) -> GymInquiryRead:
    inquiry = db.scalar(select(GymInquiry).where(GymInquiry.id == inquiry_id).with_for_update())
    if inquiry is None:
        raise HTTPException(status_code=404, detail="Gym inquiry was not found.")
    changes = payload.model_dump(exclude_unset=True)
    if "interested_plan_id" in changes and changes["interested_plan_id"]:
        if db.scalar(select(PlatformPlan.id).where(PlatformPlan.id == changes["interested_plan_id"])) is None:
            raise HTTPException(status_code=400, detail="Platform plan was not found.")
    for field, value in changes.items():
        setattr(inquiry, field, value)
    inquiry.updated_by = actor.id
    _audit(db, actor, "gym_inquiry.updated", "gym_inquiry", inquiry.id, {"changed_fields": sorted(changes)})
    db.commit()
    db.refresh(inquiry)
    return _inquiry_read(db, inquiry)


@router.post("/developer/inquiries/{inquiry_id}/invite", response_model=InvitationCreated, status_code=201)
def invite_gym_owner_from_inquiry(
    inquiry_id: UUID, db: Session = Depends(get_db), actor: User = Depends(require_super_admin)
) -> InvitationCreated:
    inquiry = db.scalar(select(GymInquiry).where(GymInquiry.id == inquiry_id).with_for_update())
    if inquiry is None:
        raise HTTPException(status_code=404, detail="Gym inquiry was not found.")
    if inquiry.status == "converted":
        raise HTTPException(status_code=409, detail="This inquiry has already converted to a gym.")
    if inquiry.invitation_id:
        previous = db.scalar(select(Invitation).where(Invitation.id == inquiry.invitation_id))
        if previous is not None and previous.status == "active":
            invitation_service.revoke_invitation(db, actor, previous.id)
    created = invitation_service.create_invitation(
        db, actor, InvitationCreateRequest(role=RoleName.GYM_OWNER, email=inquiry.email, expires_in_hours=168)
    )
    inquiry.invitation_id = created.id
    inquiry.status = "invited"
    inquiry.updated_by = actor.id
    db.commit()
    return created


def _subscription_read(subscription: Subscription, plan: PlatformPlan | None) -> GymSubscriptionRead:
    return GymSubscriptionRead(
        id=subscription.id, platform_plan_id=subscription.platform_plan_id,
        plan_name=subscription.plan_name, status=subscription.status,
        amount_cents=subscription.amount_cents, currency=plan.currency if plan else "INR",
        trial_started_at=subscription.trial_started_at,
        current_period_ends_at=subscription.current_period_ends_at,
    )


def _gym_read(
    gym: Gym,
    *,
    owner: User | None,
    subscription: Subscription | None,
    plan: PlatformPlan | None,
    user_count: int,
    member_count: int,
    trainer_count: int,
) -> DeveloperGymRead:
    return DeveloperGymRead(
        id=gym.id, name=gym.name, code=gym.code, status=gym.status, email=gym.email,
        phone=gym.phone, address=gym.address, timezone=gym.timezone, settings=gym.settings,
        is_active=gym.is_active, created_at=gym.created_at,
        owner_name=owner.full_name if owner else None, owner_email=owner.email if owner else None,
        user_count=user_count, member_count=member_count, trainer_count=trainer_count,
        subscription=_subscription_read(subscription, plan) if subscription else None,
    )


def _group_counts(db: Session, model, gym_ids: list[UUID]) -> dict[UUID, int]:
    if not gym_ids:
        return {}
    rows = db.execute(
        select(model.gym_id, func.count()).where(model.gym_id.in_(gym_ids)).group_by(model.gym_id)
    ).all()
    return {gym_id: int(count) for gym_id, count in rows}


def _gym_reads(db: Session, gyms: list[Gym]) -> list[DeveloperGymRead]:
    gym_ids = [gym.id for gym in gyms]
    if not gym_ids:
        return []

    owner_rows = list(db.scalars(
        select(User).where(
            User.gym_id.in_(gym_ids),
            User.role == RoleName.GYM_OWNER.value,
            User.is_active.is_(True),
        ).order_by(User.created_at.asc())
    ).all())
    owners: dict[UUID, User] = {}
    for owner in owner_rows:
        owners.setdefault(owner.gym_id, owner)

    subscriptions = {
        item.gym_id: item
        for item in db.scalars(select(Subscription).where(Subscription.gym_id.in_(gym_ids))).all()
    }
    plan_ids = {item.platform_plan_id for item in subscriptions.values() if item.platform_plan_id}
    plans = {
        item.id: item
        for item in db.scalars(select(PlatformPlan).where(PlatformPlan.id.in_(plan_ids))).all()
    } if plan_ids else {}
    user_counts = _group_counts(db, User, gym_ids)
    member_counts = _group_counts(db, Member, gym_ids)
    trainer_counts = _group_counts(db, Trainer, gym_ids)

    return [
        _gym_read(
            gym,
            owner=owners.get(gym.id),
            subscription=subscriptions.get(gym.id),
            plan=plans.get(subscriptions[gym.id].platform_plan_id) if gym.id in subscriptions else None,
            user_count=user_counts.get(gym.id, 0),
            member_count=member_counts.get(gym.id, 0),
            trainer_count=trainer_counts.get(gym.id, 0),
        )
        for gym in gyms
    ]


@router.get("/developer/gyms", response_model=list[DeveloperGymRead])
def list_developer_gyms(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> list[DeveloperGymRead]:
    gyms = list(
        db.scalars(select(Gym).order_by(Gym.created_at.desc()).offset(skip).limit(limit)).all()
    )
    return _gym_reads(db, gyms)


@router.get("/developer/free-trials", response_model=list[DeveloperGymRead])
def list_free_trial_gyms(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> list[DeveloperGymRead]:
    gyms = list(db.scalars(
        select(Gym).join(Subscription, Subscription.gym_id == Gym.id)
        .where(Subscription.status == "trialing").order_by(Subscription.current_period_ends_at.asc())
        .offset(skip).limit(limit)
    ).all())
    return _gym_reads(db, gyms)


@router.patch("/developer/gyms/{gym_id}/subscription", response_model=GymSubscriptionRead)
@router.put(
    "/developer/gyms/{gym_id}/subscription",
    response_model=GymSubscriptionRead,
    deprecated=True,
)
def set_gym_subscription(
    gym_id: UUID, payload: GymSubscriptionUpdate, db: Session = Depends(get_db),
    actor: User = Depends(require_super_admin),
) -> GymSubscriptionRead:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id))
    if gym is None:
        raise HTTPException(status_code=404, detail="Gym was not found.")
    plan = db.scalar(select(PlatformPlan).where(PlatformPlan.id == payload.platform_plan_id))
    if plan is None:
        raise HTTPException(status_code=404, detail="Platform plan was not found.")
    subscription = db.scalar(select(Subscription).where(Subscription.gym_id == gym.id).with_for_update())
    now = datetime.now(UTC)
    if subscription is None:
        subscription = Subscription(gym_id=gym.id, created_by=actor.id)
        db.add(subscription)
    subscription.platform_plan_id = plan.id
    subscription.plan_name = plan.name
    subscription.status = payload.status
    subscription.amount_cents = plan.price_cents or 0
    subscription.updated_by = actor.id
    if payload.status == "trialing":
        subscription.trial_started_at = now
        subscription.current_period_ends_at = now + timedelta(days=plan.trial_days)
    db.flush()
    _audit(db, actor, "gym_subscription.updated", "subscription", subscription.id, {
        "gym_id": gym.id, "plan": plan.slug, "status": payload.status,
    })
    db.commit()
    db.refresh(subscription)
    return _subscription_read(subscription, plan)
