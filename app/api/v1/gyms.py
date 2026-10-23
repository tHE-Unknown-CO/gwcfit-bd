from math import asin, cos, radians, sin, sqrt
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import require_permission, require_super_admin
from app.dependencies.tenant import get_current_gym_id
from app.models.enums import GymStatus, PermissionCode
from app.models.billing import Subscription
from app.models.gym import Gym
from app.models.platform_plan import PlatformPlan
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.gym import GymCreate, GymOption, GymRead, GymUpdate, PublicGymDirectoryRead
from app.services import auth as auth_service
from app.services import gym_website as website_service
from app.schemas.gym_website import GymWebsiteEdit, GymWebsiteRead, GymWebsiteEditorRead
from app.utils.codes import generate_gym_code

router = APIRouter(prefix="/gyms", tags=["gyms"])


from pydantic import BaseModel
from typing import Literal
from datetime import UTC, datetime, timedelta

class GymActivation(BaseModel):
    platform_plan_id: UUID
    activation_type: Literal["paid", "free"]

@router.post("/{gym_id}/reactivate", response_model=GymRead)
def reactivate_gym(gym_id: UUID, payload: GymActivation, db: Session = Depends(get_db), current_user: User = Depends(require_super_admin)):
    gym = db.scalar(select(Gym).where(Gym.id == gym_id).with_for_update())
    if gym is None:
        raise HTTPException(404, "Gym was not found.")
    plan = db.scalar(select(PlatformPlan).where(PlatformPlan.id == payload.platform_plan_id, PlatformPlan.is_active.is_(True)))
    if plan is None:
        raise HTTPException(422, "Select an active Platform Membership Plan.")
    if plan.billing_period not in {"month", "year"}:
        raise HTTPException(422, "This plan needs a monthly or yearly billing period before activation.")
    if payload.activation_type == "paid" and plan.price_cents is None:
        raise HTTPException(422, "Set a plan price before recording paid activation.")
    subscription = db.scalar(select(Subscription).where(Subscription.gym_id == gym_id).with_for_update())
    if subscription is None:
        subscription = Subscription(gym_id=gym_id, created_by=current_user.id)
        db.add(subscription)
    now = datetime.now(UTC)
    subscription.platform_plan_id = plan.id
    subscription.plan_name = plan.name
    subscription.status = "active"
    subscription.is_active = True
    subscription.amount_cents = 0 if payload.activation_type == "free" else plan.price_cents or 0
    subscription.billing_provider = "admin_free" if payload.activation_type == "free" else "admin_paid"
    subscription.current_period_ends_at = now + timedelta(days=365 if plan.billing_period == "year" else 30)
    subscription.updated_by = current_user.id
    gym.is_active = True
    gym.status = "active"
    gym.settings = {k: v for k, v in (gym.settings or {}).items() if k not in {"suspension_reason", "platform_access_override", "platform_access_override_by"}}
    gym.settings = {**gym.settings, "platform_activation_type": payload.activation_type, "platform_activation_plan": plan.name, "platform_activation_by": str(current_user.id), "platform_activation_at": now.isoformat()}
    gym.updated_by = current_user.id
    db.commit()
    db.refresh(gym)
    return gym


@router.get("/public/options", response_model=list[GymOption])
def list_public_gym_options(db: Session = Depends(get_db)) -> list[GymOption]:
    return [GymOption(id=gym.id, name=gym.name) for gym in auth_service.list_gym_options(db)]


def _distance_km(latitude: float, longitude: float, gym_latitude: float, gym_longitude: float) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (latitude, longitude, gym_latitude, gym_longitude))
    lat_delta, lon_delta = lat2 - lat1, lon2 - lon1
    value = sin(lat_delta / 2) ** 2 + cos(lat1) * cos(lat2) * sin(lon_delta / 2) ** 2
    return round(6371 * 2 * asin(sqrt(value)), 1)


@router.get("/public/directory", response_model=list[PublicGymDirectoryRead])
def list_public_gym_directory(
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    db: Session = Depends(get_db),
) -> list[PublicGymDirectoryRead]:
    rows = db.execute(
        select(
            Gym.id, Gym.name, Gym.code, Gym.status, Gym.email, Gym.phone,
            Gym.address, Gym.settings, PlatformPlan.name.label("plan_name"),
            Subscription.status.label("subscription_status"), Gym.created_at,
        )
        .outerjoin(Subscription, Subscription.gym_id == Gym.id)
        .outerjoin(PlatformPlan, PlatformPlan.id == Subscription.platform_plan_id)
        .where(Gym.is_active.is_(True))
        .order_by(Gym.created_at.desc())
    ).all()
    gyms = []
    for row in rows:
        item = dict(row._mapping)
        profile = item.pop("settings") or {}
        gym_latitude, gym_longitude = profile.get("latitude"), profile.get("longitude")
        address_parts = [item.get("address"), profile.get("city"), profile.get("state"), profile.get("pincode")]
        item["address"] = ", ".join(str(part).strip() for part in address_parts if part and str(part).strip()) or None
        distance = None
        if latitude is not None and longitude is not None and gym_latitude is not None and gym_longitude is not None:
            distance = _distance_km(latitude, longitude, float(gym_latitude), float(gym_longitude))
        gyms.append(PublicGymDirectoryRead(
            **item,
            business_email=profile.get("business_email", item.pop("email")),
            business_phone=profile.get("business_phone", item.pop("phone")),
            latitude=gym_latitude,
            longitude=gym_longitude,
            distance_km=distance,
            description=profile.get("description"),
            facilities=profile.get("facilities", []),
            categories=profile.get("categories", []),
            gallery_photos=profile.get("gallery_photos", []),
            gender_policy=profile.get("gender_policy"),
            opening_hours=profile.get("opening_hours", {}),
            starting_price_cents=profile.get("starting_price_cents"),
            rating=profile.get("rating"),
            review_count=profile.get("review_count", 0),
            trial_available=profile.get("trial_available", False),
            verified=profile.get("verified", False),
        ))
    return sorted(gyms, key=lambda gym: (gym.distance_km is None, gym.distance_km or 0, gym.name.lower()))


@router.get("/public/{gym_id}/website", response_model=GymWebsiteRead)
def get_public_gym_website(gym_id: UUID, db: Session = Depends(get_db)):
    return website_service.public_website(db, gym_id)


@router.get("/{gym_id}/website", response_model=GymWebsiteEditorRead)
def get_gym_website_editor(gym_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    website_service.authorize_website_editor(current_user, gym_id)
    gym = website_service.website_gym(db, gym_id)
    trainers, owners = website_service.website_team(db, gym_id, gym.settings or {}, include_hidden=True)
    return GymWebsiteEditorRead(profile=website_service.edit_profile(gym.settings, trainers, owners, gym), trainers=trainers, owners=owners)


@router.patch("/{gym_id}/website", response_model=GymWebsiteRead)
def update_gym_website(gym_id: UUID, payload: GymWebsiteEdit, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return website_service.save_website(db, gym_id, payload, current_user)


@router.get("", response_model=list[GymRead])
def list_gyms(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> list[Gym]:
    statement = select(Gym).order_by(Gym.created_at.desc(), Gym.id).offset(skip).limit(min(limit, 200))
    from app.services.gym_access import platform_expired
    gyms = list(db.scalars(statement).all())
    for gym in gyms:
        platform_expired(db, gym)
    return gyms


@router.post("", response_model=GymRead, status_code=201)
def create_gym(
    payload: GymCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_GYMS)),
) -> Gym:
    gym = Gym(
        name=payload.name,
        code=generate_gym_code(payload.name),
        email=payload.email,
        phone=payload.phone,
        address=payload.address,
        timezone=payload.timezone,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(gym)
    db.commit()
    db.refresh(gym)
    return gym


@router.get("/me", response_model=GymRead)
def get_my_gym(
    gym_id: UUID = Depends(get_current_gym_id),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Gym:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    return gym


@router.patch("/me", response_model=GymRead)
def update_my_gym(
    payload: GymUpdate,
    gym_id: UUID = Depends(get_current_gym_id),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PermissionCode.CONFIGURE_GYM)),
) -> Gym:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "settings" and current_user.role != "super_admin":
            reserved = {"platform_access_override", "platform_access_override_by", "suspension_reason", "platform_activation_type", "platform_activation_plan", "platform_activation_by", "platform_activation_at"}
            value = {**{k: v for k, v in (value or {}).items() if k not in reserved}, **{k: v for k, v in (gym.settings or {}).items() if k in reserved}}
        setattr(gym, key, value)
    gym.updated_by = current_user.id
    db.commit()
    db.refresh(gym)
    return gym


@router.get("/{gym_id}", response_model=GymRead)
def get_gym(
    gym_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> Gym:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id))
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    return gym


@router.post("/{gym_id}/suspend", response_model=GymRead)
def suspend_gym(
    gym_id: UUID,
    reason: str = Query(default="manual", pattern="^(manual|platform_unpaid)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> Gym:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    gym.status = GymStatus.SUSPENDED.value
    gym.settings = {**(gym.settings or {}), "suspension_reason": reason}
    gym.updated_by = current_user.id
    db.commit()
    db.refresh(gym)
    return gym


@router.delete("/{gym_id}", response_model=MessageResponse)
def delete_gym(
    gym_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> MessageResponse:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    gym.status = GymStatus.DELETED.value
    gym.is_active = False
    gym.updated_by = current_user.id
    db.commit()
    return MessageResponse(message="Gym was deleted.")
