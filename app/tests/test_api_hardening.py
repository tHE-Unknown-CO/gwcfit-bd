from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt

from app.auth.jwt import create_token, decode_token
from app.core.config import Settings, get_settings
from app.main import app, readiness_check


def test_request_id_is_propagated_and_api_responses_are_not_cached() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/", headers={"X-Request-ID": "integration-test-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "integration-test-123"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_validation_errors_have_a_stable_machine_readable_shape() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "The supplied data is invalid."
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["requestId"] == response.headers["X-Request-ID"]
    assert {item["field"] for item in body["error"]["details"]} == {"email", "password"}


def test_oversized_declared_body_is_rejected_before_route_execution() -> None:
    limit = get_settings().max_request_body_bytes
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": str(limit + 1)},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_non_json_api_body_is_rejected() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            content="email=user@example.com",
            headers={"Content-Type": "text/plain"},
        )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_collection_page_size_is_bounded_by_validation() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/platform-plans/public?limit=101")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_jwt_enforces_issuer_audience_type_and_unique_id() -> None:
    settings = get_settings()
    subject = uuid4()
    token = create_token(
        subject=subject,
        token_type="access",
        role="member",
        gym_id=uuid4(),
        expires_delta=timedelta(minutes=5),
    )

    payload = decode_token(token)
    assert payload["sub"] == str(subject)
    assert payload["iss"] == settings.jwt_issuer
    assert payload["aud"] == settings.jwt_audience
    assert payload["jti"]

    missing_contract_claims = jwt.encode(
        {"sub": str(subject), "type": "access"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as error:
        decode_token(missing_contract_claims)
    assert error.value.status_code == 401


def test_readiness_check_reports_database_failure_without_internal_details() -> None:
    class UnavailableDatabase:
        def execute(self, _statement):
            from sqlalchemy.exc import OperationalError

            raise OperationalError("SELECT 1", {}, RuntimeError("private connection details"))

    with pytest.raises(HTTPException) as error:
        readiness_check(UnavailableDatabase())  # type: ignore[arg-type]

    assert error.value.status_code == 503
    assert error.value.detail == "Service is not ready."


def test_production_settings_reject_development_defaults() -> None:
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            jwt_secret_key="a-production-secret-with-at-least-32-characters",
            database_url="postgresql+psycopg://app:secret@database/pulsefit",
            cors_origin_regex=None,
        )

    settings = Settings(
        environment="production",
        jwt_secret_key="a-production-secret-with-at-least-32-characters",
        database_url="postgresql+psycopg://app:secret@database/pulsefit",
        cors_origins=["https://app.pulsefit.example"],
        cors_origin_regex=None,
    )
    assert settings.environment == "production"
