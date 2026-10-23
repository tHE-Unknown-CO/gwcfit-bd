from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.api.v1 import member as endpoint
from app.models.billing import Payment
from app.tests.test_rbac_endpoints import FakeSession, make_member


def fixture(monkeypatch, status="paid"):
    member = make_member(gym_id=uuid4())
    payment = Payment(id=uuid4(), gym_id=member.gym_id, member_id=member.id,
        amount_cents=199900, currency="INR", method="manual_qr", status=status,
        provider_reference="123456789012", paid_at=datetime(2026, 10, 20, 10, tzinfo=UTC),
        created_at=datetime(2026, 10, 19, 10, tzinfo=UTC),
        extra_data={"plan_name": "Standard Plan", "start_date": "2026-10-20", "expiry_date": "2027-01-17"})
    monkeypatch.setattr(endpoint, "_get_current_member", lambda db, user: member)
    gym = SimpleNamespace(name="Test Gym", address="Gym address", phone="555-0100")
    return member, payment, gym


def test_receipt_has_confirmed_server_details_and_stable_number(monkeypatch):
    member, payment, gym = fixture(monkeypatch)
    first = endpoint.get_member_receipt(payment.id, FakeSession(scalar_results=[payment, gym]), None)
    second = endpoint.get_member_receipt(payment.id, FakeSession(scalar_results=[payment, gym]), None)
    assert first == second
    assert first["receipt_number"] == "RCP-" + str(payment.id).upper()
    assert first["member_name"] == member.member_name
    assert first["amount_cents"] == 199900 and first["currency"] == "INR"
    assert first["plan_name"] == "Standard Plan" and first["gym_name"] == "Test Gym"
    assert first["transaction_reference"] == "123456789012"
    assert first["expiry_date"] == "2027-01-17"


@pytest.mark.parametrize("status", ["pending", "failed", "refunded"])
def test_unconfirmed_and_refunded_payments_cannot_issue_receipts(monkeypatch, status):
    member, payment, gym = fixture(monkeypatch, status)
    with pytest.raises(HTTPException) as error:
        endpoint.get_member_receipt(payment.id, FakeSession(scalar_results=[payment]), None)
    assert error.value.status_code == 409


def test_receipt_query_requires_both_current_member_and_gym(monkeypatch):
    member, payment, gym = fixture(monkeypatch)
    class ScopedSession:
        def scalar(self, statement):
            compiled = statement.compile()
            assert member.id in compiled.params.values()
            assert member.gym_id in compiled.params.values()
            assert "payments.is_active IS true" in str(compiled)
            return None
    with pytest.raises(HTTPException) as error:
        endpoint.get_member_receipt(uuid4(), ScopedSession(), None)
    assert error.value.status_code == 404
