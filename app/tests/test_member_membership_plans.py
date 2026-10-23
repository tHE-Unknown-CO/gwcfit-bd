from types import SimpleNamespace
from uuid import uuid4
from app.api.v1 import member as endpoint
from app.tests.test_rbac_endpoints import make_member, FakeScalarResult


def test_membership_catalog_uses_member_gym_and_only_active_plans(monkeypatch):
    gym_id = uuid4()
    member = make_member(gym_id=gym_id)
    plan = SimpleNamespace(id=uuid4(), gym_id=gym_id, name="Monthly", description="Gym access", duration_days=30, price_cents=150000, currency="INR", features=["Gym floor"])
    member.membership_plan = plan
    member.membership_plan_id = plan.id
    monkeypatch.setattr(endpoint, "_get_current_member", lambda db, user: member)
    monkeypatch.setattr(endpoint, "_get_payments", lambda db, member: [])
    class CatalogSession:
        def scalars(self, statement):
            compiled = statement.compile()
            assert gym_id in compiled.params.values()
            assert "membership_plans.gym_id =" in str(compiled)
            assert "membership_plans.is_active IS true" in str(compiled)
            return FakeScalarResult([plan])
    result = endpoint.get_member_membership(db=CatalogSession(), current_user=SimpleNamespace(gym_id=uuid4()))
    assert result.membership_plan_uuid == plan.id
    assert result.available_plans[0].plan_uuid == plan.id
    assert result.available_plans[0].benefits == ["Gym floor"]
    assert result.available_plans[0].price_cents == 150000
