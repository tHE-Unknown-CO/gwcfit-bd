from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.rate_limit import InMemoryRateLimitMiddleware


def test_rate_limit_returns_json_response_and_retry_header() -> None:
    app = FastAPI()
    app.add_middleware(InMemoryRateLimitMiddleware, limit_per_minute=1)

    @app.get("/resource")
    def resource() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/resource").status_code == 200

    response = client.get("/resource")
    assert response.status_code == 429
    body = response.json()
    assert body["detail"] == "Too many requests. Please retry shortly."
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["error"]["message"] == body["detail"]
    assert body["error"]["requestId"].startswith("req_")
    assert int(response.headers["Retry-After"]) >= 1
    assert response.headers["X-RateLimit-Limit"] == "1"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert response.headers["X-Request-ID"] == body["error"]["requestId"]
