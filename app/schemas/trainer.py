from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import EnterpriseRead


class TrainerCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=180)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    bio: str | None = Field(default=None, max_length=1200)
    specialties: list[str] = Field(default_factory=list)
    hourly_rate_cents: int = Field(default=0, ge=0)
    commission_rate: float = Field(default=0, ge=0, le=100)
    user_id: UUID | None = None
    extra_data: dict = Field(default_factory=dict)


class TrainerUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=180)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    bio: str | None = Field(default=None, max_length=1200)
    specialties: list[str] | None = None
    hourly_rate_cents: int | None = Field(default=None, ge=0)
    commission_rate: float | None = Field(default=None, ge=0, le=100)
    extra_data: dict | None = None


class TrainerRead(EnterpriseRead):
    gym_id: UUID
    gym_name: str | None = None
    user_id: UUID | None
    user_name: str | None = None
    trainer_name: str
    full_name: str
    email: str | None
    phone: str | None
    bio: str | None
    specialties: list[str]
    hourly_rate_cents: int
    commission_rate: float
    extra_data: dict
