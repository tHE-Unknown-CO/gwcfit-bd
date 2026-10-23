from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from app.models.attendance import checkout_ready, require_checkout_ready, daily_visit_limit


def test_checkout_wait_and_boundary():
    record = SimpleNamespace(check_in_at=datetime.now(UTC) - timedelta(minutes=29))
    assert not checkout_ready(record)
    with pytest.raises(HTTPException) as error:
        require_checkout_ready(record)
    assert error.value.status_code == 409
    record.check_in_at = datetime.now(UTC) - timedelta(minutes=30)
    assert checkout_ready(record)


def test_visit_limit_uses_only_members_own_gym_plan():
    gym_id = uuid4()
    member = SimpleNamespace(membership_plan_id=uuid4(), gym_id=gym_id)
    plan = SimpleNamespace(gym_id=gym_id, daily_visit_limit=2)
    db = SimpleNamespace(get=lambda *args: plan)
    assert daily_visit_limit(db, member) == 2
    plan.gym_id = uuid4()
    assert daily_visit_limit(db, member) == 4
