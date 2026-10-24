from fastapi import HTTPException
from app.models.gym import Gym
from app.models.enums import RoleName
from app.models.billing import Subscription
from sqlalchemy import select
from datetime import UTC, datetime


def platform_expired(db, gym):
    grace_end = (getattr(gym, "settings", None) or {}).get("payment_grace_ends_at")
    if grace_end:
        end = datetime.fromisoformat(grace_end)
        if end > datetime.now(UTC):
            return False
        if gym.is_active and gym.status == "active":
            gym.status = "suspended"
            gym.settings = {**gym.settings, "suspension_reason": "platform_unpaid"}
            db.commit()
        return True
    subscription = db.scalar(select(Subscription).where(Subscription.gym_id == gym.id))
    if subscription is None:
        return False
    end = subscription.current_period_ends_at
    expired = subscription.status == "expired" or (end is not None and end.replace(tzinfo=UTC) <= datetime.now(UTC))
    if expired and gym.is_active and gym.status == "active":
        gym.status = "suspended"
        gym.settings = {**(gym.settings or {}), "suspension_reason": "platform_expired"}
        db.commit()
    return expired


def require_active_gym(db, user):
    if user.role == RoleName.SUPER_ADMIN.value or user.gym_id is None:
        return
    gym = db.get(Gym, user.gym_id)
    if gym and (getattr(gym, "settings", None) or {}).get("suspension_reason") == "platform_unpaid" and gym.status != "active":
        message = "Your gym is suspended because the platform membership payment is overdue. Please contact the developer, pay the platform fee and request activation." if user.role == "gym_owner" else "Your gym's platform access is suspended. Please contact your gym owner to restore access."
        raise HTTPException(403, message)
    if gym and platform_expired(db, gym):
        message = "Your Platform Membership Plan has expired. Please contact the developer to renew it." if user.role == "gym_owner" else "Your gym's platform membership has expired. Please contact your gym owner."
        raise HTTPException(403, message)
    if gym is None or not gym.is_active or gym.status != "active":
        raise HTTPException(403, "Your gym has been suspended or deactivated by the platform administrators. Contact the application owner to restore access.")
