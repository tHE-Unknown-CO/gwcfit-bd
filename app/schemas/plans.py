from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import EnterpriseRead
from app.schemas.currency import normalize_currency_code


class MembershipPlanCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=800)
    daily_visit_limit: int = Field(default=4, ge=1, le=24)
    duration_days: int = Field(gt=0)
    price_cents: int = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    features: list[str] = Field(default_factory=list)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> str:
        return normalize_currency_code(value)


class MembershipPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=800)
    daily_visit_limit: int | None = Field(default=None, ge=1, le=24)
    duration_days: int | None = Field(default=None, gt=0)
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    features: list[str] | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> str:
        return normalize_currency_code(value)


class MembershipPlanRead(EnterpriseRead):
    gym_id: UUID
    gym_name: str | None = None
    name: str
    description: str | None
    daily_visit_limit: int
    duration_days: int
    price_cents: int
    currency: str
    features: list[str]


class WorkoutPlanCreate(BaseModel):
    member_id: UUID
    trainer_id: UUID | None = None
    title: str = Field(min_length=2, max_length=180)
    goal: str = Field(min_length=2, max_length=120)
    level: str = Field(min_length=2, max_length=80)
    starts_at: date | None = None
    ends_at: date | None = None
    sessions: list[dict] = Field(default_factory=list)


class WorkoutPlanUpdate(BaseModel):
    trainer_id: UUID | None = None
    title: str | None = Field(default=None, min_length=2, max_length=180)
    goal: str | None = Field(default=None, min_length=2, max_length=120)
    level: str | None = Field(default=None, min_length=2, max_length=80)
    starts_at: date | None = None
    ends_at: date | None = None
    sessions: list[dict] | None = None


class WorkoutPlanRead(EnterpriseRead):
    gym_id: UUID
    gym_name: str | None = None
    member_id: UUID
    member_name: str | None = None
    trainer_id: UUID | None
    trainer_name: str | None = None
    title: str
    goal: str
    level: str
    starts_at: date | None
    ends_at: date | None
    sessions: list[dict]


class DietPlanCreate(BaseModel):
    member_id: UUID
    trainer_id: UUID | None = None
    title: str = Field(min_length=2, max_length=180)
    category: Literal["Weight Loss", "Muscle Gain", "Maintenance", "Medical", "Custom"] = "Custom"
    calories_per_day: int = Field(gt=0)
    starts_at: date | None = None
    ends_at: date | None = None
    meals: list[dict] = Field(default_factory=list)


class DietPlanUpdate(BaseModel):
    trainer_id: UUID | None = None
    title: str | None = Field(default=None, min_length=2, max_length=180)
    category: Literal["Weight Loss", "Muscle Gain", "Maintenance", "Medical", "Custom"] | None = None
    calories_per_day: int | None = Field(default=None, gt=0)
    starts_at: date | None = None
    ends_at: date | None = None
    meals: list[dict] | None = None


class DietPlanRead(EnterpriseRead):
    gym_id: UUID
    gym_name: str | None = None
    member_id: UUID
    member_name: str | None = None
    trainer_id: UUID | None
    trainer_name: str | None = None
    title: str
    category: Literal["Weight Loss", "Muscle Gain", "Maintenance", "Medical", "Custom"]
    calories_per_day: int
    starts_at: date | None
    ends_at: date | None
    meals: list[dict]
