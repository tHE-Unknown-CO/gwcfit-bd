from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notifications import NotificationRead

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _read(notification: Notification) -> NotificationRead:
    return NotificationRead(
        id=notification.id,
        title=notification.title,
        body=notification.body,
        channel=notification.channel,
        read_at=notification.read_at,
        created_at=notification.created_at,
        status="read" if notification.read_at else "unread",
        gym_name=notification.gym_name,
    )


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NotificationRead]:
    statement = select(Notification).where(
        Notification.user_id == current_user.id,
        Notification.is_active.is_(True),
    )
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    statement = statement.order_by(Notification.created_at.desc()).limit(limit)
    return [_read(item) for item in db.scalars(statement).all()]


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationRead:
    notification = db.scalar(select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
        Notification.is_active.is_(True),
    ))
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification was not found.")
    notification.read_at = notification.read_at or datetime.now(UTC)
    notification.updated_by = current_user.id
    db.commit()
    db.refresh(notification)
    return _read(notification)
