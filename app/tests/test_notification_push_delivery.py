from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.services.platform_notifications import deliver_mobile_push


class Result:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class DB:
    def __init__(self, deliveries=None):
        self.tokens = ["ExponentPushToken[aaaaaaaaaaaaaaaaaaaa]", "ExponentPushToken[bbbbbbbbbbbbbbbbbbbb]"]
        self.item = SimpleNamespace(id=uuid4(), user_id=uuid4(), read_at=None, title="New enquiry", body="Test gym",
                                    payload={"push_pending": True, "push_deliveries": deliveries or {}, "category": "enquiry"})
        self.user = SimpleNamespace(is_active=True, profile={"push_tokens": list(self.tokens)})
    def scalars(self, statement): return Result([self.item])
    def get(self, model, id): return self.user
    def commit(self): pass


def response(data):
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": data})


def test_partial_ticket_failure_only_retries_the_failed_device(monkeypatch):
    db = DB()
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return response([{"status": "ok", "id": "ticket-a"}, {"status": "error", "details": {"error": "MessageRateExceeded"}}])
        return response([{"status": "ok", "id": "ticket-b"}])
    monkeypatch.setattr("httpx.post", post)
    deliver_mobile_push(db)
    states = db.item.payload["push_deliveries"]
    assert states[db.tokens[0]]["state"] == "accepted"
    assert states[db.tokens[1]]["state"] == "retry"
    states[db.tokens[1]]["next_attempt_at"] = 0
    deliver_mobile_push(db)
    assert [m["to"] for m in calls[1]] == [db.tokens[1]]
    assert db.item.payload["push_pending"] is True, "Tickets require receipt verification"
    assert "push_deliveries" not in calls[0][0]["data"]
    assert "push_pending" not in calls[0][0]["data"]


def test_receipts_complete_delivery_and_remove_unregistered_devices(monkeypatch):
    db = DB()
    db.item.payload["push_deliveries"] = {t: {"state": "accepted", "ticket_id": f"ticket-{i}", "check_at": 0} for i, t in enumerate(db.tokens)}
    def post(url, **kwargs):
        assert url.endswith("getReceipts")
        return response({"ticket-0": {"status": "ok"}, "ticket-1": {"status": "error", "details": {"error": "DeviceNotRegistered"}}})
    monkeypatch.setattr("httpx.post", post)
    deliver_mobile_push(db)
    assert db.item.payload["push_pending"] is False
    assert db.user.profile["push_tokens"] == [db.tokens[0]]


def test_missing_receipt_waits_without_resending_accepted_push(monkeypatch):
    db = DB()
    db.item.payload["push_deliveries"] = {t: {"state": "accepted", "ticket_id": str(i), "check_at": 0} for i, t in enumerate(db.tokens)}
    monkeypatch.setattr("httpx.post", lambda url, **kwargs: response({}) if url.endswith("getReceipts") else (_ for _ in ()).throw(AssertionError("Do not resend accepted pushes")))
    deliver_mobile_push(db)
    assert db.item.payload["push_pending"] is True
    assert db.item.payload["push_check_at"] > datetime.now(UTC).timestamp()


def test_credentials_error_is_preserved_for_retry_and_not_reported_delivered(monkeypatch):
    db = DB()
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: response([
        {"status": "error", "details": {"error": "InvalidCredentials"}} for _ in db.tokens]))
    deliver_mobile_push(db)
    assert db.item.payload["push_pending"] is True
    assert all(d["error"] == "InvalidCredentials" and d["state"] == "retry" for d in db.item.payload["push_deliveries"].values())
