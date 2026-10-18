import logging

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.router import api_router
from app.core.config import get_settings
from app.core.security import SecurityHeadersMiddleware
from app.database.session import get_db
from app.middleware.rate_limit import InMemoryRateLimitMiddleware
from app.middleware.request_metrics import RequestMetricsMiddleware
from app.middleware.request_context import RequestContextMiddleware, get_request_id
from app.middleware.request_size import RequestSizeLimitMiddleware

settings = get_settings()
logger = logging.getLogger("pulsefit.api")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=1_000)
app.add_middleware(InMemoryRateLimitMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RequestMetricsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["Location", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-Request-ID"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestContextMiddleware)


ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "ACCESS_DENIED",
    404: "RESOURCE_NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "RESOURCE_CONFLICT",
    410: "RESOURCE_GONE",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    503: "SERVICE_UNAVAILABLE",
}


def _error_response(request: Request, status_code: int, message: str, *, code: str | None = None, details=None):
    request_id = get_request_id(request)
    error = {
        "code": code or ERROR_CODES.get(status_code, "INTERNAL_SERVER_ERROR"),
        "message": message,
        "requestId": request_id,
    }
    if details:
        error["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"detail": message, "error": error},
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    response = _error_response(request, exc.status_code, message)
    response.headers.update(exc.headers or {})
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = [
        {
            "field": ".".join(str(part) for part in error["loc"] if part not in {"body", "query", "path"}),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    return _error_response(
        request,
        422,
        "The supplied data is invalid.",
        code="VALIDATION_ERROR",
        details=details,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = get_request_id(request)
    logger.exception("Unhandled API error request_id=%s", request_id, exc_info=exc)
    return _error_response(request, 500, "An unexpected error occurred.")


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
def readiness_check(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("Database readiness check failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not ready.",
        ) from exc
    return {"status": "ready"}


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


app.include_router(api_router, prefix=settings.api_v1_prefix)
