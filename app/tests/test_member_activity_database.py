"""Opt-in API persistence check against PostgreSQL; every fixture is rolled back.

Run in the API container with RUN_DATABASE_INTEGRATION=1.
"""
import os
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.auth.jwt import create_token
from app.database.session import engine, get_db
from app.main import app
from app.models.enums import RoleName
from app.tests.test_rbac_endpoints import make_db_user, make_gym, make_member

pytestmark = pytest.mark.skipif(os.getenv("RUN_DATABASE_INTEGRATION") != "1", reason="Opt-in PostgreSQL integration check")

def test_real_database_activity_goal_steps_distance_and_history():
    connection = engine.connect()
    transaction = connection.begin()
    overrides = dict(app.dependency_overrides)
    marker = uuid4().hex
    gym = make_gym()
    gym.code = f"ACT-{marker[:12]}"
    user = make_db_user(RoleName.MEMBER, gym_id=gym.id)
    member = make_member(gym_id=gym.id, user_id=user.id)
    def database_session():
        with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
            yield session
    try:
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            session.add(gym); session.flush()
            session.add(user); session.flush()
            session.add(member); session.flush()
            member_id, user_id, gym_id = member.id, user.id, gym.id
            session.commit()
        app.dependency_overrides[get_db] = database_session
        token = create_token(subject=user_id, role=RoleName.MEMBER.value, gym_id=gym_id, token_type="access", expires_delta=timedelta(minutes=5))
        headers = {"Authorization": f"Bearer {token}"}
        today = datetime.now(timezone(timedelta(minutes=330))).date().isoformat()
        with TestClient(app) as client:
            goal = client.post("/api/v1/member/goals", headers=headers, json={"goal_name":"Daily Move", "calories_goal":250})
            assert goal.status_code == 201, goal.text
            payload = {"activity_date":today,"utc_offset_minutes":330,"device_id":"integration-device","source":"android_foreground","hourly_steps":[1234]+[0]*23}
            sent = client.put("/api/v1/member/activity", headers=headers, json=payload)
            assert sent.status_code == 200, sent.text
            log = client.post("/api/v1/member/progress", headers=headers, json={"calories_burned":100})
            assert log.status_code == 201, log.text
            sent_again = client.put("/api/v1/member/activity", headers=headers, json=payload)
            assert sent_again.status_code == 200, sent_again.text
            raw = connection.execute(text("SELECT metadata FROM members WHERE id=:id"), {"id":member_id}).scalar_one()
            saved = raw["daily_activity"][today]
            assert saved["steps"] == 1234
            assert saved["distance_km"] == .9255
            assert saved["calories_target"] == 250
            assert saved["calories_completed"] == 100
            assert saved["calories_remaining"] == 150
            assert saved["completion_percentage"] == 40
            history = client.get("/api/v1/member/activity?utc_offset_minutes=330", headers=headers)
            assert history.status_code == 200, history.text
            assert history.json()["items"][0]["steps"] == 1234
            assert history.json()["today"]["distance_km"] == .9255
            changed = client.patch(f"/api/v1/member/goals/{goal.json()['goal_uuid']}", headers=headers, json={"calories_goal":400})
            assert changed.status_code == 200, changed.text
            raw = connection.execute(text("SELECT metadata FROM members WHERE id=:id"), {"id":member_id}).scalar_one()
            assert raw["daily_activity"][today]["calories_target"] == 400
            assert raw["daily_activity"][today]["calories_remaining"] == 300
        assert transaction.is_active
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(overrides)
        transaction.rollback(); connection.close()
