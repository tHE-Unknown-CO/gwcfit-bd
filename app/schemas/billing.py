from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import PaymentStatus
from app.schemas.common import EnterpriseRead
from app.schemas.currency import normalize_currency_code


class PaymentCreate(BaseModel):
    member_id: UUID
    membership_plan_id: UUID | None = None
    amount_cents: int = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    method: str = Field(min_length=2, max_length=80)
    status: PaymentStatus = PaymentStatus.PENDING
    provider_reference: str | None = Field(default=None, max_length=180)
    paid_at: datetime | None = None
    extra_data: dict = Field(default_factory=dict)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> str:
        return normalize_currency_code(value)


class PaymentUpdate(BaseModel):
    membership_plan_id: UUID | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    method: str | None = Field(default=None, min_length=2, max_length=80)
    status: PaymentStatus | None = None
    provider_reference: str | None = Field(default=None, max_length=180)
    paid_at: datetime | None = None
    extra_data: dict | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> str:
        return normalize_currency_code(value)


class PaymentRead(EnterpriseRead):
    gym_id: UUID
    gym_name: str | None = None
    member_id: UUID
    member_name: str | None = None
    membership_plan_id: UUID | None
    membership_plan_name: str | None = None
    amount_cents: int
    currency: str
    method: str
    status: str
    provider_reference: str | None
    paid_at: datetime | None
    extra_data: dict
