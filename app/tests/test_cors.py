from fastapi.testclient import TestClient

from app.main import app


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
