"""Durable, deduplicated platform alerts and a retryable mobile push outbox."""
import logging
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import select, func, or_
from sqlalchemy.dialects.postgresql import insert

from app.models.notification import Notification
from app.models.user import User
from app.models.gym_inquiry import GymInquiry
from app.models.gym import Gym
from app.models.billing import Subscription
from app.models.invitation import Invitation
from app.models.login_event import LoginEvent

logger = logging.getLogger(__name__)


def event_id(user_id, key):
    return uuid5(NAMESPACE_URL, f"pulsefit:notification:{user_id}:{key}")


def _save_alert(db, user_id, key, title, body, category, route, gym_id=None, resource_id=None, important=False):
    db.execute(insert(Notification).values(
        id=event_id(user_id, key), user_id=user_id, gym_id=gym_id,
        title=title[:180], body=body[:1200], channel="in_app",
        payload={"category": category, "route": route, "resource_id": str(resource_id) if resource_id else None,
                 "important": important, "push_pending": True}, is_active=True,
    ).on_conflict_do_nothing(index_elements=[Notification.id]))


def enqueue_gym_enquiry_notifications(db, inquiry):
    """Save alerts alongside the enquiry; the caller commits both atomically."""
    recipients = db.scalars(select(User.id).where(User.role == "super_admin", User.is_active.is_(True))).all()
    for user_id in recipients:
        _save_alert(db, user_id, f"enquiry:{inquiry.id}", "New gym enquiry",
                    f"{inquiry.gym_name}: {inquiry.full_name} requested registration.",
                    "enquiry", "Invitations", resource_id=inquiry.id, important=True)


def subscription_alert(subscription, now):
    end = subscription.current_period_ends_at
    if end and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if subscription.status in {"past_due", "cancelled", "expired"}:
        return subscription.status, f"Subscription {subscription.status.replace('_', ' ')}"
    if subscription.status in {"active", "trialing"} and end:
        if end <= now:
            return "expired", "Subscription expired"
        if end <= now + timedelta(days=7):
            return "expiring", "Subscription ends soon"
    return None


def sync_platform_notifications(db, recipient_id=None):
    now = datetime.now(UTC)
    recent = now - timedelta(days=7)
    recipients = select(User).where(User.role == "super_admin", User.is_active.is_(True))
    if recipient_id is not None:
        recipients = recipients.where(User.id == recipient_id)
    admins = list(db.scalars(recipients).all())
    if not admins:
        return

    def emit(key, title, body, category, route, gym_id=None, resource_id=None, important=False):
        for admin in admins:
            _save_alert(db, admin.id, key, title, body, category, route, gym_id, resource_id, important)

    for item in db.scalars(select(GymInquiry).where(or_(GymInquiry.status == "new", GymInquiry.created_at >= recent))).all():
        emit(f"enquiry:{item.id}", "New gym enquiry", f"{item.gym_name}: {item.full_name} requested registration.",
             "enquiry", "Invitations", resource_id=item.id, important=True)
    for gym in db.scalars(select(Gym).where(Gym.created_at >= recent)).all():
        emit(f"gym:{gym.id}", "New gym registered", f"{gym.name} has joined PulseFit.", "gym", "ManageGyms", gym.id)
    for gym in db.scalars(select(Gym).where(Gym.status == "suspended")).all():
        emit(f"gym-suspended:{gym.id}:{gym.updated_at}", "Gym suspended", f"{gym.name} is suspended. Review its access and subscription.",
             "gym", "ManageGyms", gym.id, important=True)
    for sub in db.scalars(select(Subscription).where(Subscription.is_active.is_(True))).all():
        if sub.updated_at and sub.updated_at >= recent and sub.status in {"active", "trialing"}:
            gym = db.get(Gym, sub.gym_id)
            emit(f"subscription-change:{sub.id}:{sub.updated_at}", "Subscription updated",
                 f"{gym.name if gym else 'Gym'}: {sub.plan_name} is {sub.status}.", "subscription", "Payments", sub.gym_id)
        alert = subscription_alert(sub, now)
        if alert:
            status, title = alert
            gym = db.get(Gym, sub.gym_id)
            emit(f"subscription:{sub.id}:{status}:{sub.current_period_ends_at}", title,
                 f"{gym.name if gym else 'Gym'}: {sub.plan_name}. " + (f"Period ends {sub.current_period_ends_at:%d %b %Y}." if sub.current_period_ends_at else "Review the subscription."),
                 "subscription", "Payments", sub.gym_id, important=True)
    for item in db.scalars(select(Invitation).where(Invitation.role == "gym_owner", Invitation.updated_at >= recent)).all():
        state = "expired" if item.status == "active" and item.expires_at <= now else item.status
        if state in {"used", "revoked", "expired"}:
            emit(f"invitation:{item.id}:{state}", f"Owner invitation {state}",
                 f"The gym owner invitation for {item.email or 'any email'} is {state}.", "invitation", "Invitations")
    # Only alerts for known platform accounts; never broadcast arbitrary submitted emails.
    emails = [admin.email.lower() for admin in admins]
    for event in db.scalars(select(LoginEvent).where(LoginEvent.success.is_(False), LoginEvent.created_at >= recent,
                                                     func.lower(LoginEvent.email).in_(emails))).all():
        emit(f"security:{event.id}", "Failed Super Admin sign-in", f"A sign-in attempt for {event.email} failed. Review account activity.",
             "security", "Notifications", important=True)
    db.commit()


def deliver_mobile_push(db):
    # Each worker locks its batch; Expo failures leave the item pending for the next cycle.
    pending = db.scalars(select(Notification).where(
        Notification.payload["push_pending"].as_boolean().is_(True),
        or_(Notification.payload["push_check_at"].as_float().is_(None),
            Notification.payload["push_check_at"].as_float() <= datetime.now(UTC).timestamp()),
        Notification.created_at >= datetime.now(UTC) - timedelta(days=1),
    ).order_by(Notification.created_at).limit(100).with_for_update(skip_locked=True)).all()
    for item in pending:
        user = db.get(User, item.user_id)
        if not user or not user.is_active or item.read_at:
            item.payload = {**item.payload, "push_pending": False}
            continue
        tokens = (user.profile or {}).get("push_tokens", [])
        if not tokens:
            item.payload = {**item.payload, "push_pending": False}
            continue
        deliveries = dict(item.payload.get("push_deliveries", {}))
        now = datetime.now(UTC).timestamp()
        try:
            from app.core.config import get_settings
            token = get_settings().expo_push_access_token
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            receipt_tokens = [t for t in tokens if deliveries.get(t, {}).get("state") == "accepted"
                              and deliveries[t].get("check_at", 0) <= now]
            invalid = set()
            if receipt_tokens:
                response = httpx.post("https://exp.host/--/api/v2/push/getReceipts", headers=headers, timeout=10,
                                      json={"ids": [deliveries[t]["ticket_id"] for t in receipt_tokens]})
                response.raise_for_status()
                receipts = response.json().get("data")
                if not isinstance(receipts, dict):
                    raise ValueError("Malformed push receipts")
                for t in receipt_tokens:
                    delivery = deliveries[t]
                    receipt = receipts.get(delivery["ticket_id"])
                    if not receipt:
                        # Do not resend accepted messages just because a receipt is delayed.
                        delivery["check_at"] = now + 60
                        continue
                    error = (receipt.get("details") or {}).get("error")
                    if receipt.get("status") == "ok":
                        deliveries[t] = {"state": "delivered"}
                    elif error == "DeviceNotRegistered":
                        invalid.add(t)
                        deliveries[t] = {"state": "invalid"}
                    else:
                        deliveries[t] = _push_retry(delivery, now, error or "ReceiptError")

            send_tokens = [t for t in tokens if t not in invalid and
                           deliveries.get(t, {}).get("state", "retry") == "retry" and
                           deliveries.get(t, {}).get("next_attempt_at", 0) <= now]
            if send_tokens:
                data = {"notificationId": str(item.id), "receiverId": str(item.user_id),
                        **{k: item.payload[k] for k in ("category", "route", "resource_id", "important") if k in item.payload}}
                response = httpx.post("https://exp.host/--/api/v2/push/send", headers=headers, timeout=10,
                                      json=[{"to": t, "title": item.title, "body": item.body, "sound": "default",
                                             "priority": "high", "ttl": 86400, "channelId": "platform-alerts", "data": data}
                                            for t in send_tokens])
                response.raise_for_status()
                tickets = response.json().get("data")
                if not isinstance(tickets, list) or len(tickets) != len(send_tokens):
                    raise ValueError("Malformed push tickets")
                for t, ticket in zip(send_tokens, tickets):
                    error = (ticket.get("details") or {}).get("error")
                    if ticket.get("status") == "ok" and isinstance(ticket.get("id"), str):
                        deliveries[t] = {"state": "accepted", "ticket_id": ticket["id"], "check_at": now + 900,
                                         "attempts": deliveries.get(t, {}).get("attempts", 0)}
                    elif error == "DeviceNotRegistered":
                        invalid.add(t)
                        deliveries[t] = {"state": "invalid"}
                    elif error == "MessageTooBig":
                        deliveries[t] = {"state": "failed", "error": error}
                        logger.error("Push payload rejected for notification %s: %s", item.id, error)
                    else:
                        deliveries[t] = _push_retry(deliveries.get(t, {}), now, error or "TicketError")
            if invalid:
                user.profile = {**user.profile, "push_tokens": [t for t in tokens if t not in invalid]}
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            for t in tokens:
                if deliveries.get(t, {}).get("state", "retry") == "retry" and deliveries.get(t, {}).get("next_attempt_at", 0) <= now:
                    deliveries[t] = _push_retry(deliveries.get(t, {}), now, "TransportError")
            logger.warning("Mobile push delivery failed; will retry", exc_info=False)
        next_checks = [d.get("check_at", d.get("next_attempt_at", now)) for t, d in deliveries.items()
                       if t in tokens and d.get("state") in {"retry", "accepted"}]
        item.payload = {**item.payload, "push_deliveries": deliveries, "push_check_at": min(next_checks, default=now),
                        "push_pending": any(deliveries.get(t, {}).get("state", "retry") in {"retry", "accepted"} for t in tokens)}
    db.commit()


def _push_retry(previous, now, error):
    attempts = previous.get("attempts", 0) + 1
    logger.warning("Push delivery will retry: %s", error)
    return {"state": "retry", "attempts": attempts, "error": error,
            "next_attempt_at": now + min(300, 2 ** min(attempts, 8))}
