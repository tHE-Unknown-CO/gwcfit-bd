from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.schemas.member_dashboard import MemberActivitySync
from app.services.member_activity import activity_day, merge_activity, snapshot_today
from app.models.enums import RoleName
from app.tests.test_rbac_endpoints import FakeSession, client_as, make_member, make_user

NOW = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)

def payload(steps=1000, **kwargs):
    hours = [0] * 24
    hours[12] = steps
    return MemberActivitySync(activity_date=date(2026, 10, 17), utc_offset_minutes=330, device_id="phone-a", hourly_steps=hours, **kwargs)

def test_sync_is_idempotent_and_does_not_regress_or_double_count_devices():
    extra, first = merge_activity({}, payload(), NOW)
    extra, again = merge_activity(extra, payload(), NOW)
    extra, stale = merge_activity(extra, payload(500), NOW)
    assert first.steps == again.steps == stale.steps == 1000
    second = payload(800).model_copy(update={"device_id": "phone-b"})
    extra, result = merge_activity(extra, second, NOW)
    assert result.steps == 1000
    assert result.distance_km == .75
    _, grown = merge_activity(extra, payload(1200), NOW)
    assert grown.steps == 1200

def test_kcal_uses_local_day_and_archives_goal_and_progress():
    extra = {"fitness_goals": [{"status": "active", "calories_goal": 250}], "progress_logs": [
        {"logged_at": "2026-10-16T20:00:00Z", "calories_burned": 75},
        {"logged_at": "2026-10-17T10:00:00Z", "calories_burned": 125},
        {"logged_at": "2026-10-16T10:00:00Z", "calories_burned": 999},
    ]}
    extra, result = merge_activity(extra, payload(), NOW)
    assert (result.calories_completed, result.calories_remaining, result.completion_percentage) == (200, 50, 80)
    assert extra["daily_activity"]["2026-10-17"]["calories_remaining"] == 50
    extra["fitness_goals"][0]["calories_goal"] = 500
    current = activity_day(extra, date(2026,10,17), 330, date(2026,10,17))
    assert current.calories_target == 500
    extra["progress_logs"] = []
    historical = activity_day(extra, date(2026,10,17), 330, date(2026,10,18))
    assert historical.calories_target == 250
    assert historical.calories_completed == 200

def test_goal_changes_update_only_today_and_over_goal_has_zero_remaining():
    extra = {"fitness_goals": [{"status": "active", "calories_goal": 100}], "progress_logs": [{"logged_at": NOW.isoformat(), "calories_burned": 200}]}
    extra, result = merge_activity(extra, payload(), NOW)
    assert result.calories_remaining == 0
    assert result.completion_percentage == 200
    extra["fitness_goals"][0]["calories_goal"] = 500
    updated = snapshot_today(extra, NOW)
    assert updated["daily_activity"]["2026-10-17"]["calories_remaining"] == 300
    assert updated["daily_activity"]["2026-10-17"]["steps"] == 1000
    _, next_day = merge_activity(updated, payload(0).model_copy(update={"activity_date": date(2026,10,18)}), NOW + timedelta(days=1))
    assert next_day.steps == next_day.calories_completed == 0

@pytest.mark.parametrize('hours', [[0]*23, [-1]+[0]*23, [100001]+[0]*23])
def test_invalid_sensor_data_is_rejected(hours):
    with pytest.raises(ValidationError):
        MemberActivitySync(activity_date=date.today(), utc_offset_minutes=330, device_id="phone", hourly_steps=hours)

def test_activity_api_persists_then_reads_paginated_member_history():
    user = make_user(RoleName.MEMBER, gym_id=uuid4())
    member = make_member(gym_id=user.gym_id, user_id=user.id)
    day = datetime.now(UTC).date().isoformat()
    db = FakeSession(scalar_results=[member, member])
    with client_as(user, db) as client:
        response = client.put('/api/v1/member/activity', json={"activity_date":day,"utc_offset_minutes":0,"device_id":"phone","hourly_steps":[10]*24})
    assert response.status_code == 200, response.text
    assert db.committed
    assert member.extra_data["daily_activity"][day]["steps"] == 240
    with client_as(user, FakeSession(scalar_results=[member])) as client:
        response = client.get('/api/v1/member/activity?limit=1&offset=0')
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["steps"] == 240
    assert response.json()["total"] == 1

def test_activity_rejects_future_dates_and_non_member_roles():
    user = make_user(RoleName.MEMBER, gym_id=uuid4())
    member = make_member(gym_id=user.gym_id, user_id=user.id)
    db = FakeSession(scalar_results=[member, member])
    with client_as(user, db) as client:
        response = client.put('/api/v1/member/activity', json={"activity_date":"2099-01-01","utc_offset_minutes":0,"device_id":"phone"})
    assert response.status_code == 422
    assert not db.committed
    with client_as(make_user(RoleName.TRAINER, gym_id=uuid4()), FakeSession()) as client:
        assert client.get('/api/v1/member/activity').status_code == 403

def test_late_offline_upload_uses_goal_from_that_day_not_a_new_goal():
    from app.services.member_activity import record_calorie_target
    extra = {"fitness_goals": [{"status": "active", "calories_goal": 250}]}
    extra = record_calorie_target(extra, NOW)
    extra["fitness_goals"][0]["calories_goal"] = 500
    extra = record_calorie_target(extra, NOW + timedelta(days=1))
    extra, result = merge_activity(extra, payload(), NOW + timedelta(days=1))
    assert result.calories_target == 250
    assert result.steps == 1000
    # Viewing from a different time zone must not alter archived kcal.
    extra["progress_logs"] = [{"logged_at": "2026-10-16T10:00:00Z", "calories_burned": 999}]
    archived = activity_day(extra, date(2026,10,17), 840, date(2026,10,18))
    assert archived.calories_completed == result.calories_completed

def test_steps_automatically_increase_active_energy_with_explicit_default_weight():
    extra = {"fitness_goals": [{"status":"active", "calories_goal":250}]}
    extra, result = merge_activity(extra, payload(664), NOW)
    assert result.calories_completed == result.calories_estimated == 17
    assert result.calories_logged == 0
    assert result.calories_remaining == 233
    assert result.calories_source == "steps"
    assert result.calorie_estimate_weight_kg == 70
    assert result.calorie_estimate_uses_default_weight is True
    assert extra["daily_activity"]["2026-10-17"]["calories_completed"] == 17


def test_walking_estimate_uses_real_weight_and_does_not_add_overlapping_logs():
    extra = {"weight":80, "progress_logs":[{"logged_at":NOW.isoformat(), "calories_burned":20}]}
    extra, result = merge_activity(extra, payload(2000), NOW)
    assert result.calories_estimated == 60
    assert result.calories_completed == 60
    assert result.calorie_estimate_uses_default_weight is False
    extra["progress_logs"][0]["calories_burned"] = 100
    extra, result = merge_activity(extra, payload(2000), NOW)
    assert result.calories_completed == 100
    assert result.calories_source == "logged"
    extra["weight"] = 60
    archived = activity_day(extra, date(2026,10,17), 330, date(2026,10,18))
    assert archived.calorie_estimate_weight_kg == 80
    assert archived.calories_estimated == 60
