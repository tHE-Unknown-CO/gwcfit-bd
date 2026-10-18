from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import EnterpriseRead


class MemberCreate(BaseModel):
    member_code: str = Field(min_length=2, max_length=40)
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    status: str = Field(default="active", max_length=40)
    trainer_id: UUID | None = None
    membership_plan_id: UUID | None = None
    joined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    membership_starts_at: date | None = None
    membership_ends_at: date | None = None
    emergency_contact: dict = Field(default_factory=dict)
    extra_data: dict = Field(default_factory=dict)


class MemberUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=40)
    trainer_id: UUID | None = None
    membership_plan_id: UUID | None = None
    membership_starts_at: date | None = None
    membership_ends_at: date | None = None
    emergency_contact: dict | None = None
    extra_data: dict | None = None


class MemberRead(EnterpriseRead):
    gym_id: UUID
    gym_name: str | None = None
    user_id: UUID | None
    user_name: str | None = None
    trainer_id: UUID | None
    trainer_name: str | None = None
    membership_plan_id: UUID | None
    membership_plan_name: str | None = None
    member_name: str
    member_code: str
    first_name: str
    last_name: str
    email: str | None
    phone: str | None
    status: str
    joined_at: datetime
    membership_starts_at: date | None
    membership_ends_at: date | None
    emergency_contact: dict
    extra_data: dict
