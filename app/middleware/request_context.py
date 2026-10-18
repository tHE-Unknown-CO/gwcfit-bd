import json
import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger("pulsefit.api")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return request_id
    supplied = request.headers.get("x-request-id", "")
    if REQUEST_ID_PATTERN.fullmatch(supplied):
        return supplied
    return f"req_{uuid4().hex}"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a safe correlation ID and emit one structured log per request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = get_request_id(request)
        request.state.request_id = request_id
        started_at = perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = round((perf_counter() - started_at) * 1_000, 2)
            status_code = response.status_code if response is not None else 500
            if response is not None:
                response.headers["X-Request-ID"] = request_id
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "client_ip": request.client.host if request.client else None,
                    },
                    separators=(",", ":"),
                )
            )
