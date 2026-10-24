from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/pulsefit"

LOCAL_CORS_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|"
    r"127(?:\.\d{1,3}){3}|"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}"
    r"):\d+$"
)
LOCAL_CORS_ORIGINS = [
    "http://localhost:19006",
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:3000",
    "http://127.0.0.1:8081",
    "http://127.0.0.1:8082",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PulseFit Enterprise API"
    environment: str = "local"
    api_v1_prefix: str = "/api/v1"
    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = Field(default="change-this-in-production")
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "pulsefit-api"
    jwt_audience: str = "pulsefit-clients"
    access_token_expire_minutes: int = Field(default=15, gt=0)
    refresh_token_expire_days: int = Field(default=30, gt=0)
    password_reset_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    email_verification_token_expire_hours: int = Field(default=24, ge=1, le=168)

    cors_origins: list[str] = LOCAL_CORS_ORIGINS.copy()
    cors_origin_regex: str | None = LOCAL_CORS_ORIGIN_REGEX
    rate_limit_per_minute: int = Field(default=120, gt=0)
    auth_rate_limit_per_minute: int = Field(default=10, gt=0)
    public_write_rate_limit_per_minute: int = Field(default=30, gt=0)
    max_request_body_bytes: int = Field(default=1_048_576, ge=16_384, le=10_485_760)
    storage_provider: str = "s3"
    expo_push_access_token: str | None = None
    s3_bucket_name: str | None = None
    cloudinary_cloud_name: str | None = None

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.environment.lower() in {"production", "prod"}:
            insecure_secrets = {"change-this-in-production", "replace-with-a-long-random-secret"}
            if self.jwt_secret_key in insecure_secrets or len(self.jwt_secret_key) < 32:
                raise ValueError("JWT_SECRET_KEY must be a unique value of at least 32 characters in production.")
            if self.database_url == DEFAULT_DATABASE_URL:
                raise ValueError("DATABASE_URL must be explicitly configured for production.")
            if self.cors_origin_regex == LOCAL_CORS_ORIGIN_REGEX:
                raise ValueError("CORS_ORIGIN_REGEX must be explicitly configured for production.")
            if not self.cors_origins or any(origin == "*" for origin in self.cors_origins):
                raise ValueError("CORS_ORIGINS must contain an explicit production allowlist.")
            if self.cors_origins == LOCAL_CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS must not use the development allowlist in production.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
