from fastapi.testclient import TestClient

from app.main import app
import pytest


def test_cors_preflight_allows_expo_localhost_origin():
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://localhost:8082",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8082"


def test_cors_preflight_allows_expo_lan_origin():
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://192.168.1.50:8081",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://192.168.1.50:8081"


def test_api_v1_root_returns_status():
    with TestClient(app) as client:
        response = client.get("/api/v1/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "v1",
        "docs": "/docs",
        "openapi": "/api/v1/openapi.json",
    }


@pytest.mark.parametrize("origin,allowed", [("http://localhost:8081", True), ("https://untrusted.example", False)])
def test_unhandled_notification_errors_preserve_cors_policy(monkeypatch, origin, allowed):
    from app.api.v1 import notifications
    from app.dependencies.auth import get_current_user
    from app.database.session import get_db
    from types import SimpleNamespace
    from uuid import uuid4
    def fail(*args, **kwargs):
        raise RuntimeError("private database details")
    monkeypatch.setattr(notifications, "_refresh_platform_history", fail)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4(), role="super_admin")
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/notifications/unread-count", headers={"Origin": origin})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
    assert response.status_code == 500
    assert "private database details" not in response.text
    if allowed:
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"
        assert "Origin" in response.headers["vary"]
    else:
        assert "access-control-allow-origin" not in response.headers
