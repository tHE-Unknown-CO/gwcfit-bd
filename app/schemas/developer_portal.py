from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


InquiryStatus = Literal["new", "contacted", "invited", "converted", "closed"]
SubscriptionStatus = Literal["trialing", "active", "past_due", "cancelled", "expired"]


class GymInquiryCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=180)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=40)
    gym_name: str = Field(min_length=2, max_length=180)
    active_members_range: str = Field(min_length=1, max_length=40)
    interested_plan_id: UUID | None = None
    source: str = Field(default="owner_site", min_length=1, max_length=80)

    @field_validator("full_name", "gym_name", "active_members_range", "source")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if not 8 <= len(digits) <= 15:
            raise ValueError("Enter a valid mobile number with 8 to 15 digits.")
        return f"+{digits}" if value.strip().startswith("+") else digits


class GymInquiryUpdate(BaseModel):
    status: InquiryStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)
    interested_plan_id: UUID | None = None


class GymInquiryRead(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    phone: str
    gym_name: str
    active_members_range: str
    interested_plan_id: UUID | None
    interested_plan_name: str | None = None
    status: str
    invitation_id: UUID | None
    gym_id: UUID | None
    notes: str | None
    source: str
    created_at: datetime
    updated_at: datetime


class GymSubscriptionUpdate(BaseModel):
    platform_plan_id: UUID
    status: SubscriptionStatus = "active"


class GymSubscriptionRead(BaseModel):
    id: UUID
    platform_plan_id: UUID | None
    plan_name: str
    status: str
    amount_cents: int
    currency: str = "INR"
    trial_started_at: datetime | None
    current_period_ends_at: datetime | None


class DeveloperGymRead(BaseModel):
    id: UUID
    name: str
    code: str
    status: str
    email: str | None
    phone: str | None
    address: str | None
    timezone: str
    settings: dict
    is_active: bool
    created_at: datetime
    owner_name: str | None
    owner_email: str | None
    user_count: int
    member_count: int
    trainer_count: int
    subscription: GymSubscriptionRead | None


class LoginEventRead(BaseModel):
    id: UUID
    user_id: UUID | None
    email: EmailStr
    role: str | None
    success: bool
    failure_reason: str | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
