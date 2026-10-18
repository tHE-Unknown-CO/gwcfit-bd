from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import InvitationStatus, RoleName


class InvitationCreateRequest(BaseModel):
    role: RoleName
    email: EmailStr | None = None
    expires_in_hours: int = Field(default=168, ge=1, le=720)


class InvitationRead(BaseModel):
    id: UUID
    gym_id: UUID | None
    gym_name: str | None = None
    role: RoleName
    email: EmailStr | None
    status: InvitationStatus
    expires_at: datetime
    use_count: int
    max_uses: int
    created_at: datetime
    created_by: UUID | None
    used_at: datetime | None
    used_by: UUID | None
    token: str | None = None

    model_config = {"from_attributes": True}


class InvitationCreated(InvitationRead):
    token: str


class InvitationValidateRequest(BaseModel):
    token: str = Field(min_length=20, max_length=500)

    @field_validator("token")
    @classmethod
    def strip_token(cls, value: str) -> str:
        return value.strip()


class InvitationValidation(BaseModel):
    valid: bool = True
    role: RoleName
    gym_id: UUID | None
    gym_name: str | None
    email: EmailStr | None
    expires_at: datetime
