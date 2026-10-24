from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.services.platform_notifications import event_id, subscription_alert, sync_platform_notifications, deliver_mobile_push
from app.schemas.notifications import PushDevice
from app.models.notification import Notification


def test_event_identity_deduplicates_per_recipient_and_event():
    user = uuid4()
    assert event_id(user, "enquiry:1") == event_id(user, "enquiry:1")
    assert event_id(user, "enquiry:1") != event_id(user, "enquiry:2")
    assert event_id(user, "enquiry:1") != event_id(uuid4(), "enquiry:1")


@pytest.mark.parametrize("status,days,expected", [("active", 30, None), ("trialing", 7, "expiring"), ("active", 0, "expired"), ("active", -1, "expired"), ("past_due", 30, "past_due"), ("cancelled", 30, "cancelled")])
def test_subscription_alert_boundaries(status, days, expected):
    now = datetime.now(UTC)
    result = subscription_alert(SimpleNamespace(status=status, current_period_ends_at=now + timedelta(days=days)), now)
    assert (result[0] if result else None) == expected


def test_platform_alerts_allow_no_gym_and_push_token_validation():
    assert Notification.__table__.c.gym_id.nullable
    PushDevice(token="ExponentPushToken[abcdefghijklmnopqrst]")
    with pytest.raises(ValueError):
        PushDevice(token="https://untrusted.example/token")


class Result:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


def test_sync_repeated_enquiry_uses_conflict_safe_insert_without_tokens_in_body():
    now = datetime.now(UTC)
    admin = SimpleNamespace(id=uuid4(), email="admin@example.com")
    enquiry = SimpleNamespace(id=uuid4(), gym_name="Test gym", full_name="Owner")
    statements = []
    class DB:
        def __init__(self): self.rows = [[admin], [enquiry], [], [], [], [], []]
        def scalars(self, stmt): return Result(self.rows.pop(0))
        def execute(self, stmt): statements.append(stmt)
        def commit(self): pass
    sync_platform_notifications(DB())
    sync_platform_notifications(DB())
    values = [stmt.compile(dialect=postgresql.dialect()).params for stmt in statements]
    assert values[0]["id"] == values[1]["id"]
    assert "ON CONFLICT" in str(statements[0].compile(dialect=postgresql.dialect()))
    assert values[0]["payload"]["route"] == "Invitations"
    assert values[0]["payload"]["important"] is True


def test_push_failure_keeps_notification_pending(monkeypatch):
    import httpx
    item = SimpleNamespace(user_id=uuid4(), read_at=None, payload={"push_pending": True}, title="New enquiry", body="Test", id=uuid4())
    class DB:
        def scalars(self, stmt): return Result([item])
        def get(self, model, id): return SimpleNamespace(is_active=True, profile={"push_tokens": ["ExponentPushToken[abcdefghijklmnopqrst]"]})
        def commit(self): pass
    def fail(*args, **kwargs): raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "post", fail)
    deliver_mobile_push(DB())
    assert item.payload["push_pending"] is True


def test_unread_count_is_scoped_to_user_without_list_limit():
    from app.api.v1.notifications import unread_count
    user = SimpleNamespace(id=uuid4(), role="trainer")
    class DB:
        def scalar(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            assert user.id in compiled.params.values()
            assert "read_at IS NULL" in str(compiled)
            assert "LIMIT" not in str(compiled)
            return 145
    assert unread_count(DB(), user) == {"count": 145}


@pytest.mark.parametrize("endpoint", ["list", "count"])
def test_platform_history_and_bell_sync_events_before_reading(monkeypatch, endpoint):
    from app.api.v1 import notifications
    user = SimpleNamespace(id=uuid4(), role="super_admin")
    synced = []
    db = SimpleNamespace()
    def sync(session, recipient_id):
        assert session is db
        synced.append(recipient_id)
    def read(statement):
        assert synced == [user.id], "Events must be persisted before fetching the history/count"
        assert user.id in statement.compile(dialect=postgresql.dialect()).params.values()
        return Result([])
    db.scalars = read
    db.scalar = lambda statement: (read(statement), 0)[1]
    monkeypatch.setattr(notifications, "sync_platform_notifications", sync)
    if endpoint == "list":
        assert notifications.list_notifications(False, 100, db, user) == []
    else:
        assert notifications.unread_count(db, user) == {"count": 0}


def test_history_sync_only_selects_the_authenticated_platform_recipient():
    recipient_id = uuid4()
    class DB:
        def scalars(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            assert recipient_id in compiled.params.values()
            assert "super_admin" in compiled.params.values()
            return Result([])
    sync_platform_notifications(DB(), recipient_id=recipient_id)


@pytest.mark.parametrize("endpoint", ["list", "count"])
def test_failed_event_sync_rolls_back_and_still_serves_saved_notifications(monkeypatch, endpoint):
    from app.api.v1 import notifications
    from sqlalchemy.exc import SQLAlchemyError
    user = SimpleNamespace(id=uuid4(), role="super_admin")
    rolled_back = []
    saved = SimpleNamespace(
        id=uuid4(), title="Saved enquiry", body="Already persisted", channel="in_app",
        read_at=None, created_at=datetime.now(UTC), gym_name=None, payload={},
    )
    def fail(*args, **kwargs):
        raise SQLAlchemyError("event source unavailable")
    def read(statement):
        assert rolled_back == [True], "Failed transactions must be rolled back before reading"
        return Result([saved])
    db = SimpleNamespace(rollback=lambda: rolled_back.append(True), scalars=read,
                         scalar=lambda statement: (read(statement), 1)[1])
    monkeypatch.setattr(notifications, "sync_platform_notifications", fail)
    if endpoint == "list":
        result = notifications.list_notifications(False, 100, db, user)
        assert result[0].id == saved.id
        assert result[0].status == "unread"
    else:
        assert notifications.unread_count(db, user) == {"count": 1}


def test_new_enquiry_saves_super_admin_alerts_in_the_same_transaction():
    from app.api.v1.developer_portal import create_gym_inquiry
    from app.schemas.developer_portal import GymInquiryCreate
    recipients = [uuid4(), uuid4()]
    statements = []
    class DB:
        committed = False
        def begin_nested(self): return nullcontext()
        def scalar(self, statement): return None  # no duplicate enquiry/user/gym
        def add(self, inquiry): self.inquiry = inquiry
        def flush(self):
            self.inquiry.id = uuid4()
            self.inquiry.status = "new"
            self.inquiry.created_at = self.inquiry.updated_at = datetime.now(UTC)
        def scalars(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            assert "super_admin" in compiled.params.values()
            assert "users.is_active IS true" in str(compiled)
            return Result(recipients)
        def execute(self, statement):
            assert not self.committed
            statements.append(statement)
        def commit(self):
            assert len(statements) == len(recipients)
            self.committed = True
        def refresh(self, inquiry): pass
    db = DB()
    result = create_gym_inquiry(GymInquiryCreate(
        full_name="New Owner", email="new@example.com", phone="9876543210",
        gym_name="New Fitness", active_members_range="Under 100",
    ), db)
    assert db.committed
    for recipient, statement in zip(recipients, statements):
        compiled = statement.compile(dialect=postgresql.dialect())
        values = compiled.params
        assert values["user_id"] == recipient
        assert values["id"] == event_id(recipient, f"enquiry:{result.id}")
        assert values["title"] == "New gym enquiry"
        assert "New Fitness" in values["body"]
        assert values["payload"] == {
            "category": "enquiry", "route": "Invitations", "resource_id": str(result.id),
            "important": True, "push_pending": True,
        }
        assert "ON CONFLICT" in str(compiled)


def test_cannot_mark_someone_elses_notification_read():
    from fastapi import HTTPException
    from app.api.v1.notifications import mark_notification_read
    user = SimpleNamespace(id=uuid4())
    requested_id = uuid4()
    class DB:
        def scalar(self, statement):
            values = statement.compile(dialect=postgresql.dialect()).params.values()
            assert user.id in values and requested_id in values
            return None
    with pytest.raises(HTTPException) as exc:
        mark_notification_read(requested_id, DB(), user)
    assert exc.value.status_code == 404


def test_register_device_preserves_profile_and_removes_other_account_owner():
    from app.api.v1.notifications import register_push_device
    token = "ExponentPushToken[abcdefghijklmnopqrst]"
    previous = SimpleNamespace(profile={"push_tokens": [token], "name": "old"})
    current = SimpleNamespace(profile={"push_tokens": [], "name": "current"})
    class DB:
        def scalars(self, statement): return Result([previous])
        def commit(self): pass
    register_push_device(PushDevice(token=token), DB(), current)
    assert previous.profile == {"push_tokens": [], "name": "old"}
    assert current.profile == {"push_tokens": [token], "name": "current"}
