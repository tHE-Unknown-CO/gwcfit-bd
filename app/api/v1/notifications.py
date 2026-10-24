import logging
import asyncio
import time
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database.session import SessionLocal
from app.auth.jwt import decode_token
from app.core.config import get_settings
from app.dependencies.auth import get_current_user
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notifications import NotificationRead, PushDevice
from app.services.platform_notifications import sync_platform_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])
logger = logging.getLogger(__name__)


def _authenticate_socket(token):
    claims = decode_token(token, expected_type="access")
    with SessionLocal() as db:
        user = get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
        return str(user.id), float(claims["exp"])


@router.websocket("/live")
async def live_notifications(socket: WebSocket):
    settings = get_settings()
    origin = socket.headers.get("origin")
    policy = CORSMiddleware(socket.app, allow_origins=settings.cors_origins, allow_origin_regex=settings.cors_origin_regex)
    if origin and not policy.is_allowed_origin(origin):
        await socket.close(code=4403)
        return
    await socket.accept()
    try:
        # Keep bearer tokens out of URLs, browser history, and access logs.
        message = await asyncio.wait_for(socket.receive_json(), timeout=10)
        token = message.get("access_token") if isinstance(message, dict) else None
        if not isinstance(token, str) or len(token) > 8192:
            await socket.close(code=4401)
            return
        user_id, expires = await asyncio.to_thread(_authenticate_socket, token)
        hub = socket.app.state.notification_hub
        if len(hub.subscribers.get(user_id, ())) >= 10:
            await socket.close(code=4429)
            return
        with hub.subscribe(user_id) as queue:
            await socket.send_json({"type": "ready"})
            last_auth = time.monotonic()
            while True:
                remaining = expires - time.time()
                if remaining <= 0:
                    await socket.close(code=4401)
                    return
                try:
                    await asyncio.wait_for(queue.get(), timeout=min(20, remaining))
                    kind = "notifications_changed"
                except TimeoutError:
                    kind = "heartbeat"
                if time.monotonic() - last_auth >= 20:
                    await asyncio.to_thread(_authenticate_socket, token)
                    last_auth = time.monotonic()
                await socket.send_json({"type": kind})
    except (HTTPException, ValueError, TimeoutError):
        await socket.close(code=4401)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Live notification connection failed")
        await socket.close(code=1011)


def _refresh_platform_history(db: Session, current_user: User) -> None:
    if current_user.role != "super_admin":
        return
    try:
        sync_platform_notifications(db, recipient_id=current_user.id)
    except Exception:
        # A failure in one event source must not hide already-saved alerts.
        # Roll back the failed transaction before querying notification storage.
        db.rollback()
        logger.exception("Platform notification refresh failed; serving saved history")


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
        category=(notification.payload or {}).get("category", "general"),
        important=(notification.payload or {}).get("important", False),
        route=(notification.payload or {}).get("route"),
        resource_id=(notification.payload or {}).get("resource_id"),
    )


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NotificationRead]:
    # Materialize current platform events before reading the history. The bell
    # must also work when the periodic background monitor hasn't run yet.
    _refresh_platform_history(db, current_user)
    statement = select(Notification).where(
        Notification.user_id == current_user.id,
        Notification.is_active.is_(True),
    )
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    statement = statement.order_by(Notification.created_at.desc()).limit(limit)
    return [_read(item) for item in db.scalars(statement).all()]


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _refresh_platform_history(db, current_user)
    count = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == current_user.id, Notification.is_active.is_(True), Notification.read_at.is_(None)))
    return {"count": count or 0}


@router.post("/push-device", status_code=204)
def register_push_device(payload: PushDevice, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # One physical token belongs to the currently signed-in account only.
    owners = db.scalars(select(User).where(User.profile["push_tokens"].contains([payload.token])).with_for_update()).all()
    for owner in owners:
        owner.profile = {**owner.profile, "push_tokens": [t for t in owner.profile.get("push_tokens", []) if t != payload.token]}
    profile = dict(current_user.profile or {})
    profile["push_tokens"] = list(dict.fromkeys([*profile.get("push_tokens", []), payload.token]))[-10:]
    current_user.profile = profile
    db.commit()


@router.delete("/push-device", status_code=204)
def unregister_push_device(payload: PushDevice, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.profile = {**(current_user.profile or {}), "push_tokens": [t for t in (current_user.profile or {}).get("push_tokens", []) if t != payload.token]}
    db.commit()


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
