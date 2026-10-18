from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.middleware.request_context import get_request_id


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject declared request bodies that exceed the configured API limit."""

    def __init__(self, app, max_bytes: int | None = None):
        super().__init__(app)
        self.max_bytes = max_bytes or get_settings().max_request_body_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        declared_size = 0
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = -1
            if declared_size < 0:
                return self._error(request, 400, "INVALID_CONTENT_LENGTH", "Content-Length must be a non-negative integer.")
            if declared_size > self.max_bytes:
                return self._error(request, 413, "PAYLOAD_TOO_LARGE", "The request body is too large.")

        if request.method in {"POST", "PUT", "PATCH"} and request.url.path.startswith("/api/"):
            if declared_size > 0:
                media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
                if media_type != "application/json":
                    return self._error(
                        request,
                        415,
                        "UNSUPPORTED_MEDIA_TYPE",
                        "API request bodies must use application/json.",
                    )

            # Content-Length is optional (for example with chunked transfer encoding),
            # so verify the body itself before validation and database work begin.
            body = await request.body()
            if len(body) > self.max_bytes:
                return self._error(request, 413, "PAYLOAD_TOO_LARGE", "The request body is too large.")
        return await call_next(request)

    def _error(self, request: Request, status_code: int, code: str, message: str) -> JSONResponse:
        request_id = get_request_id(request)
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": message,
                "error": {"code": code, "message": message, "requestId": request_id},
            },
            headers={"X-Request-ID": request_id},
        )
