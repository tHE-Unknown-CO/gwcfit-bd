from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.models.enums import RoleName
from app.models.gym import Gym
from app.models.user import User
from app.schemas.super_admin import GymAdminCreateRequest, GymAdminCreateResponse, GymAdminRead
from app.utils.codes import generate_gym_code


def _email_exists(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email.lower())) is not None


def _unique_gym_code(db: Session, gym_name: str) -> str:
    for _ in range(5):
        code = generate_gym_code(gym_name)
        if db.scalar(select(Gym.id).where(Gym.code == code)) is None:
            return code
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique gym code.",
    )


def create_gym_admin(
    db: Session,
    payload: GymAdminCreateRequest,
    *,
    actor: User,
) -> GymAdminCreateResponse:
    if _email_exists(db, payload.admin_email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Admin email is already registered.")

    gym = Gym(
        name=payload.gym_name,
        code=_unique_gym_code(db, payload.gym_name),
        email=str(payload.gym_email) if payload.gym_email else None,
        phone=payload.gym_phone,
        address=payload.gym_address,
        timezone=payload.gym_timezone,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(gym)
    db.flush()

    gym_admin = User(
        gym_id=gym.id,
        email=str(payload.admin_email).lower(),
        hashed_password=hash_password(payload.admin_password),
        full_name=payload.admin_full_name,
        role=RoleName.GYM_OWNER.value,
        phone=payload.admin_phone,
        is_email_verified=True,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(gym_admin)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gym admin could not be created.") from exc

    db.refresh(gym)
    db.refresh(gym_admin)
    return GymAdminCreateResponse(
        gym=gym,
        gym_admin=GymAdminRead(
            id=gym_admin.id,
            gym_id=gym_admin.gym_id,
            email=gym_admin.email,
            full_name=gym_admin.full_name,
            role=RoleName(gym_admin.role),
            phone=gym_admin.phone,
            is_active=gym_admin.is_active,
        ),
    )
