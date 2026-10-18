from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.enums import RoleName
from app.models.plans import WorkoutPlan
from app.tests.test_rbac_endpoints import FakeSession, client_as, make_db_user, make_member, make_user


@pytest.mark.parametrize("route, payload", [
    ("payments", {"amount_cents": 1500, "method": "cash"}),
    ("workout-plans", {"title": "Strength", "goal": "Build strength", "level": "Beginner"}),
    ("diet-plans", {"title": "Weekly meals", "calories_per_day": 2200}),
    ("attendance", {"check_in_at": "2026-10-11T09:00:00Z"}),
])
def test_writes_reject_members_outside_current_gym(route, payload):
    gym_id = uuid4()
    db = FakeSession(scalar_results=[None])
    with client_as(make_user(RoleName.GYM_OWNER, gym_id=gym_id), db) as client:
        response = client.post(f"/api/v1/{route}", json={"member_id": str(uuid4()), **payload})
    assert response.status_code == 400
    assert response.json()["detail"] == "Member must belong to the current gym."
    assert db.added == []
    assert not db.committed


@pytest.mark.parametrize("route, field", [
    ("members", "first_name"), ("members", "extra_data"),
    ("trainers", "specialties"), ("payments", "amount_cents"),
    ("membership-plans", "name"), ("workout-plans", "sessions"),
    ("diet-plans", "category"), ("attendance", "source"),
])
def test_patch_rejects_null_required_fields_without_mutating_record(route, field):
    record = SimpleNamespace(id=uuid4(), **{field: "unchanged"})
    db = FakeSession(scalar_results=[record])
    with client_as(make_user(RoleName.GYM_OWNER, gym_id=uuid4()), db) as client:
        response = client.patch(f"/api/v1/{route}/{record.id}", json={field: None})
    assert response.status_code == 422
    assert getattr(record, field) == "unchanged"
    assert not db.committed


@pytest.mark.parametrize("route, payload", [
    ("workout-plans", {"title": "Strength", "goal": "Build strength", "level": "Beginner"}),
    ("diet-plans", {"title": "Weekly meals", "calories_per_day": 2200}),
])
def test_trainer_cannot_create_plans_for_unassigned_members(route, payload):
    trainer = SimpleNamespace(id=uuid4())
    db = FakeSession(scalar_results=[trainer, None])
    with client_as(make_user(RoleName.TRAINER, gym_id=uuid4()), db) as client:
        response = client.post(f"/api/v1/{route}", json={"member_id": str(uuid4()), **payload})
    assert response.status_code == 403
    assert "assigned members" in response.json()["detail"]
    assert db.added == []


@pytest.mark.parametrize("route", ["workout-plans", "diet-plans", "attendance"])
@pytest.mark.parametrize("replacement", [None, str(uuid4())])
def test_trainer_cannot_remove_or_transfer_their_own_record_assignment(route, replacement):
    trainer = SimpleNamespace(id=uuid4())
    record = SimpleNamespace(id=uuid4(), trainer_id=trainer.id)
    db = FakeSession(scalar_results=[record, trainer])
    with client_as(make_user(RoleName.TRAINER, gym_id=uuid4()), db) as client:
        response = client.patch(f"/api/v1/{route}/{record.id}", json={"trainer_id": replacement})
    assert response.status_code == 403
    assert record.trainer_id == trainer.id
    assert not db.committed


@pytest.mark.parametrize("route", ["workout-plans", "diet-plans", "attendance"])
def test_owner_cannot_link_a_trainer_from_another_gym(route):
    record = SimpleNamespace(id=uuid4(), trainer_id=None)
    db = FakeSession(scalar_results=[record, None])
    with client_as(make_user(RoleName.GYM_OWNER, gym_id=uuid4()), db) as client:
        response = client.patch(f"/api/v1/{route}/{record.id}", json={"trainer_id": str(uuid4())})
    assert response.status_code == 400
    assert record.trainer_id is None
    assert not db.committed


def test_member_nullable_contact_can_still_be_cleared():
    member = make_member(gym_id=uuid4())
    db = FakeSession(scalar_results=[member])
    with client_as(make_user(RoleName.GYM_OWNER, gym_id=member.gym_id), db) as client:
        response = client.patch(f"/api/v1/members/{member.id}", json={"email": None})
    assert response.status_code == 200
    assert member.email is None


def test_partial_date_edit_is_validated_against_existing_start_date():
    plan = SimpleNamespace(id=uuid4(), starts_at=date(2026, 10, 11), ends_at=date(2026, 10, 20))
    db = FakeSession(scalar_results=[plan])
    with client_as(make_user(RoleName.GYM_OWNER, gym_id=uuid4()), db) as client:
        response = client.patch(f"/api/v1/workout-plans/{plan.id}", json={"ends_at": "2026-10-10"})
    assert response.status_code == 422
    assert plan.ends_at == date(2026, 10, 20)
    assert not db.committed


def test_attendance_rejects_a_timestamp_without_timezone():
    db = FakeSession()
    with client_as(make_user(RoleName.RECEPTIONIST, gym_id=uuid4()), db) as client:
        response = client.post("/api/v1/attendance", json={
            "member_id": str(uuid4()), "check_in_at": "2026-10-11T09:00:00",
        })
    assert response.status_code == 422
    assert db.added == []


def test_trainer_can_create_workout_for_their_assigned_member():
    gym_id = uuid4()
    member_id = uuid4()
    trainer = SimpleNamespace(id=uuid4())
    db = FakeSession(scalar_results=[trainer, member_id, member_id, trainer.id])
    with client_as(make_user(RoleName.TRAINER, gym_id=gym_id), db) as client:
        response = client.post("/api/v1/workout-plans", json={
            "member_id": str(member_id), "title": "Strength", "goal": "Build strength", "level": "Beginner",
        })
    assert response.status_code == 201
    assert response.json()["trainer_id"] == str(trainer.id)
    assert isinstance(db.added[0], WorkoutPlan)


def test_super_admin_accounts_are_protected_from_deletion():
    target = make_db_user(RoleName.SUPER_ADMIN, gym_id=None)
    db = FakeSession()
    db.get = lambda *_args: target
    with client_as(make_user(RoleName.SUPER_ADMIN), db) as client:
        response = client.delete(f"/api/v1/users/{target.id}")
    assert response.status_code == 403
    assert target.is_active
    assert not db.committed


def test_duplicate_records_are_rolled_back_and_return_conflict():
    class ConflictingSession(FakeSession):
        def commit(self):
            raise IntegrityError("insert", {}, ValueError("private database details"))

    db = ConflictingSession()
    with client_as(make_user(RoleName.GYM_OWNER, gym_id=uuid4()), db) as client:
        response = client.post("/api/v1/membership-plans", json={
            "name": "Monthly", "duration_days": 30, "price_cents": 2500,
        })
    assert response.status_code == 409
    assert db.rolled_back
    assert "private" not in response.text


@pytest.mark.parametrize("values", [{"hourly_rate_cents": -1}, {"commission_rate": -1}, {"commission_rate": 101}])
def test_trainer_compensation_must_be_in_range(values):
    db = FakeSession()
    with client_as(make_user(RoleName.GYM_OWNER, gym_id=uuid4()), db) as client:
        response = client.post("/api/v1/trainers", json={"full_name": "Alex Coach", **values})
    assert response.status_code == 422
    assert db.added == []
