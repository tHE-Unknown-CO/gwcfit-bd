from math import asin, cos, radians, sin, sqrt
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import require_permission
from app.dependencies.tenant import get_current_gym_id
from app.models.enums import GymStatus, PermissionCode
from app.models.billing import Subscription
from app.models.gym import Gym
from app.models.platform_plan import PlatformPlan
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.gym import GymCreate, GymOption, GymRead, GymUpdate, PublicGymDirectoryRead
from app.services import auth as auth_service
from app.utils.codes import generate_gym_code

router = APIRouter(prefix="/gyms", tags=["gyms"])


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
            business_email=profile.get("business_email") or item.pop("email"),
            business_phone=profile.get("business_phone") or item.pop("phone"),
            latitude=gym_latitude,
            longitude=gym_longitude,
            distance_km=distance,
            description=profile.get("description"),
            facilities=profile.get("facilities", []),
            categories=profile.get("categories", []),
            gender_policy=profile.get("gender_policy"),
            opening_hours=profile.get("opening_hours", {}),
            starting_price_cents=profile.get("starting_price_cents"),
            rating=profile.get("rating"),
            review_count=profile.get("review_count", 0),
            trial_available=profile.get("trial_available", False),
            verified=profile.get("verified", False),
        ))
    return sorted(gyms, key=lambda gym: (gym.distance_km is None, gym.distance_km or 0, gym.name.lower()))


@router.get("", response_model=list[GymRead])
def list_gyms(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.MANAGE_GYMS)),
) -> list[Gym]:
    statement = select(Gym).where(Gym.is_active.is_(True)).offset(skip).limit(min(limit, 200))
    return list(db.scalars(statement).all())


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
        setattr(gym, key, value)
    gym.updated_by = current_user.id
    db.commit()
    db.refresh(gym)
    return gym


@router.get("/{gym_id}", response_model=GymRead)
def get_gym(
    gym_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.MANAGE_GYMS)),
) -> Gym:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    return gym


@router.post("/{gym_id}/suspend", response_model=GymRead)
def suspend_gym(
    gym_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_GYMS)),
) -> Gym:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    gym.status = GymStatus.SUSPENDED.value
    gym.updated_by = current_user.id
    db.commit()
    db.refresh(gym)
    return gym


@router.delete("/{gym_id}", response_model=MessageResponse)
def delete_gym(
    gym_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_GYMS)),
) -> MessageResponse:
    gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    gym.status = GymStatus.DELETED.value
    gym.is_active = False
    gym.updated_by = current_user.id
    db.commit()
    return MessageResponse(message="Gym was deleted.")
