from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.services.gym_access import require_active_gym


@pytest.mark.parametrize("role", ["gym_owner", "member", "trainer", "receptionist", "sub_admin"])
@pytest.mark.parametrize("gym", [None, SimpleNamespace(id="gym", is_active=False, status="deleted"), SimpleNamespace(id="gym", is_active=True, status="suspended")])
def test_block_every_tenant_role(role, gym):
    with pytest.raises(HTTPException) as error:
        require_active_gym(SimpleNamespace(get=lambda *args: gym, scalar=lambda *args: None), SimpleNamespace(role=role, gym_id="gym"))
    assert error.value.status_code == 403
    assert "Contact the application owner" in error.value.detail


def test_active_gym_and_platform_admin_allowed():
    db = SimpleNamespace(get=lambda *args: SimpleNamespace(id="gym", is_active=True, status="active"), scalar=lambda *args: None)
    require_active_gym(db, SimpleNamespace(role="member", gym_id="gym"))
    require_active_gym(None, SimpleNamespace(role="super_admin", gym_id=None))


def test_legacy_override_no_longer_bypasses_subscription_check():
    from app.services.gym_access import platform_expired
    gym = SimpleNamespace(id="gym", settings={"platform_access_override": True})
    db = SimpleNamespace(scalar=lambda *args: None)
    assert platform_expired(db, gym) is False


def test_expired_platform_plan_suspends_and_uses_role_specific_message():
    from datetime import UTC, datetime, timedelta
    for role, contact in [("gym_owner", "developer"), ("member", "gym owner")]:
        gym = SimpleNamespace(id="gym", is_active=True, status="active", settings={})
        subscription = SimpleNamespace(status="active", current_period_ends_at=datetime.now(UTC) - timedelta(seconds=1))
        db = SimpleNamespace(get=lambda *args: gym, scalar=lambda *args: subscription, commit=lambda: None)
        with pytest.raises(HTTPException) as error:
            require_active_gym(db, SimpleNamespace(role=role, gym_id="gym"))
        assert contact in error.value.detail
        assert gym.status == "suspended"


def test_unpaid_suspension_messages():
    gym = SimpleNamespace(status="suspended", settings={"suspension_reason": "platform_unpaid"})
    db = SimpleNamespace(get=lambda *args: gym)
    for role, message in [("gym_owner", "pay the platform fee"), ("member", "contact your gym owner")]:
        with pytest.raises(HTTPException) as error:
            require_active_gym(db, SimpleNamespace(role=role, gym_id="gym"))
        assert message in error.value.detail


def test_grace_allows_access_until_deadline_then_suspends():
    from datetime import UTC, datetime, timedelta
    from app.services.gym_access import platform_expired
    gym = SimpleNamespace(status="active", is_active=True, settings={"payment_grace_ends_at": (datetime.now(UTC) + timedelta(days=7)).isoformat()})
    db = SimpleNamespace(commit=lambda: None)
    assert platform_expired(db, gym) is False
    gym.settings["payment_grace_ends_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert platform_expired(db, gym) is True
    assert gym.status == "suspended"
    assert gym.settings["suspension_reason"] == "platform_unpaid"
