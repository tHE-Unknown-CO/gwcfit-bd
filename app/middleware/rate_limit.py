from time import monotonic
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.middleware.request_context import get_request_id


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """Small local rate limiter. Use Redis-backed limits in clustered deployments."""

    def __init__(self, app, limit_per_minute: int | None = None, max_buckets: int = 10_000):
        super().__init__(app)
        settings = get_settings()
        self.limit_per_minute = limit_per_minute or settings.rate_limit_per_minute
        self.auth_limit_per_minute = min(self.limit_per_minute, settings.auth_rate_limit_per_minute)
        self.public_write_limit_per_minute = min(
            self.limit_per_minute, settings.public_write_rate_limit_per_minute
        )
        self.max_buckets = max_buckets
        self.requests: dict[str, deque[float]] = defaultdict(deque)
        self.last_seen: dict[str, float] = {}

    def _policy(self, request: Request) -> tuple[str, int]:
        path = request.url.path.rstrip("/")
        if path in {
            "/api/v1/auth/login",
            "/api/v1/auth/forgot-password",
            "/api/v1/auth/reset-password",
            "/api/v1/auth/refresh",
            "/api/v1/auth/register",
            "/api/v1/auth/register/owner",
            "/api/v1/invitations/validate",
        }:
            return "auth", self.auth_limit_per_minute
        if request.method == "POST" and path == "/api/v1/gym-inquiries":
            return "public-write", self.public_write_limit_per_minute
        return "general", self.limit_per_minute

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        bucket, limit = self._policy(request)
        key = f"{client_ip}:{bucket}"
        now = monotonic()
        if key not in self.requests and len(self.requests) >= self.max_buckets:
            oldest_key = min(self.last_seen, key=self.last_seen.__getitem__)
            self.requests.pop(oldest_key, None)
            self.last_seen.pop(oldest_key, None)
        self.last_seen[key] = now
        window = self.requests[key]

        while window and now - window[0] > 60:
            window.popleft()

        if len(window) >= limit:
            retry_after = max(1, int(60 - (now - window[0])))
            request_id = get_request_id(request)
            message = "Too many requests. Please retry shortly."
            return JSONResponse(
                status_code=429,
                content={
                    "detail": message,
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": message,
                        "requestId": request_id,
                    },
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-Request-ID": request_id,
                },
            )

        window.append(now)
        response = await call_next(request)
        response.headers.setdefault("X-RateLimit-Limit", str(limit))
        response.headers.setdefault("X-RateLimit-Remaining", str(max(0, limit - len(window))))
        return response
