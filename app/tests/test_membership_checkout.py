from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.api.v1 import membership_checkout as checkout
from app.models.billing import Payment
from app.models.enums import RoleName
from app.tests.test_rbac_endpoints import FakeSession, make_member, make_user, client_as


def setup_checkout(monkeypatch, *, enabled=True):
    gym_id = uuid4()
    member = make_member(gym_id=gym_id)
    user = make_user(RoleName.MEMBER, gym_id=gym_id)
    plan = SimpleNamespace(id=uuid4(), gym_id=gym_id, name="Monthly", price_cents=99900, currency="INR", duration_days=30)
    gym = SimpleNamespace(id=gym_id, settings={"membership_payment_qr": {"payee_name": "Gym", "upi_id": "gym@bank", "enabled": enabled}})
    monkeypatch.setattr(checkout, "_get_current_member", lambda db, user: member)
    payload = checkout.CheckoutRequest(plan_uuid=plan.id, method="manual_qr", quoted_amount_cents=99900,
        quoted_currency="INR", transaction_reference="123456789012")
    return gym, member, user, plan, payload


def make_payment(member, plan_id=None, method="manual_qr"):
    return Payment(id=uuid4(), gym_id=member.gym_id, member_id=member.id,
        membership_plan_id=plan_id or uuid4(), amount_cents=99900, currency="INR", method=method,
        status="pending", provider_reference="123456789012", is_active=True,
        extra_data={"source": "member_checkout", "duration_days": 30, "plan_name": "Monthly"})


def test_manual_submission_is_pending_and_does_not_activate(monkeypatch):
    gym, member, user, plan, payload = setup_checkout(monkeypatch)
    db = FakeSession(scalar_results=[gym, plan, None, None])
    result = checkout.submit_checkout(payload, db, user)
    assert result["status"] == "pending"
    assert result["amount_cents"] == 99900
    assert member.membership_plan_id is None
    assert member.membership_ends_at is None
    assert len(db.added) == 1 and db.committed


def test_plan_lookup_uses_members_gym_not_supplied_user_gym(monkeypatch):
    gym, member, user, plan, payload = setup_checkout(monkeypatch)
    user.gym_id = uuid4()
    class ScopedSession(FakeSession):
        def scalar(self, statement):
            compiled = statement.compile()
            if "membership_plans" in str(compiled):
                assert member.gym_id in compiled.params.values()
                assert "membership_plans.is_active IS true" in str(compiled)
                return None
            return gym
    with pytest.raises(HTTPException) as error:
        checkout.submit_checkout(payload, ScopedSession(), user)
    assert error.value.status_code == 404


@pytest.mark.parametrize("changes", [{"quoted_amount_cents": 1}, {"quoted_currency": "USD"}])
def test_changed_price_or_currency_is_rejected(monkeypatch, changes):
    gym, member, user, plan, payload = setup_checkout(monkeypatch)
    db = FakeSession(scalar_results=[gym, plan])
    with pytest.raises(HTTPException) as error:
        checkout.submit_checkout(payload.model_copy(update=changes), db, user)
    assert error.value.status_code == 409
    assert not db.added


def test_disabled_qr_cannot_be_used(monkeypatch):
    gym, member, user, plan, payload = setup_checkout(monkeypatch, enabled=False)
    with pytest.raises(HTTPException) as error:
        checkout.submit_checkout(payload, FakeSession(scalar_results=[gym, plan]), user)
    assert error.value.status_code == 409


def test_duplicate_reference_is_idempotent_for_same_member(monkeypatch):
    gym, member, user, plan, payload = setup_checkout(monkeypatch)
    payment = make_payment(member, plan.id)
    db = FakeSession(scalar_results=[gym, plan, payment])
    result = checkout.submit_checkout(payload, db, user)
    assert result["id"] == str(payment.id)
    assert not db.added


def test_another_members_reference_cannot_be_reused(monkeypatch):
    gym, member, user, plan, payload = setup_checkout(monkeypatch)
    payment = make_payment(make_member(gym_id=gym.id), plan.id)
    with pytest.raises(HTTPException) as error:
        checkout.submit_checkout(payload, FakeSession(scalar_results=[gym, plan, payment]), user)
    assert error.value.status_code == 409


def test_owner_approval_assigns_plan_and_cannot_extend_twice(monkeypatch):
    gym, member, user, plan, payload = setup_checkout(monkeypatch)
    payment = make_payment(member, plan.id)
    db = FakeSession(scalar_results=[payment, member, payment])
    owner = make_user(RoleName.GYM_OWNER, gym_id=gym.id)
    result = checkout.review(payment.id, checkout.ReviewRequest(decision="approve"), db, gym.id, owner)
    assert result["status"] == "paid" and member.membership_plan_id == plan.id
    assert member.membership_ends_at == datetime.now(UTC).date() + timedelta(days=29)
    expiry = member.membership_ends_at
    with pytest.raises(HTTPException) as error:
        checkout.review(payment.id, checkout.ReviewRequest(decision="approve"), db, gym.id, owner)
    assert error.value.status_code == 409 and member.membership_ends_at == expiry


def test_renewal_preserves_remaining_days_and_original_start():
    member = make_member(gym_id=uuid4())
    payment = make_payment(member)
    today = datetime.now(UTC).date()
    member.membership_plan_id = payment.membership_plan_id
    member.membership_starts_at = today - timedelta(days=10)
    member.membership_ends_at = today + timedelta(days=5)
    checkout.activate(FakeSession(scalar_results=[member]), payment)
    assert member.membership_starts_at == today - timedelta(days=10)
    assert member.membership_ends_at == today + timedelta(days=35)


def test_rejection_does_not_assign_membership(monkeypatch):
    gym, member, user, plan, payload = setup_checkout(monkeypatch)
    payment = make_payment(member, plan.id)
    result = checkout.review(payment.id, checkout.ReviewRequest(decision="reject", note="Reference not found"),
        FakeSession(scalar_results=[payment]), gym.id, user)
    assert result["status"] == "failed" and member.membership_plan_id is None


def test_cross_tenant_review_cannot_find_payment():
    gym_id = uuid4()
    class ScopedSession(FakeSession):
        def scalar(self, statement):
            assert gym_id in statement.compile().params.values()
            return None
    with pytest.raises(HTTPException) as error:
        checkout.review(uuid4(), checkout.ReviewRequest(decision="approve"), ScopedSession(), gym_id, SimpleNamespace(id=uuid4()))
    assert error.value.status_code == 404


@pytest.mark.parametrize("route,method,payload", [("settings", "put", {"enabled": False}), ("reviews", "get", None)])
def test_member_cannot_configure_or_review_payments(route, method, payload):
    with client_as(make_user(RoleName.MEMBER, gym_id=uuid4()), FakeSession()) as client:
        response = getattr(client, method)(f"/api/v1/membership-checkout/{route}", **({"json": payload} if payload else {}))
    assert response.status_code == 403


@pytest.mark.parametrize("field,value", [("upi_id", "bad&am=1"), ("qr_image_url", "http://insecure/image.png")])
def test_qr_configuration_validation(field, value):
    with pytest.raises(ValidationError):
        checkout.QrSettings(**{field: value})


def test_checkout_accepts_only_gym_qr_payments():
    with pytest.raises(ValidationError):
        checkout.CheckoutRequest(plan_uuid=uuid4(), method="unsupported_provider", quoted_amount_cents=99900, quoted_currency="INR")
