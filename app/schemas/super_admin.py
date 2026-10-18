from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.enums import RoleName
from app.schemas.auth import normalize_aliases, validate_password_bytes
from app.schemas.gym import GymRead


class GymAdminCreateRequest(BaseModel):
    gym_name: str = Field(min_length=2, max_length=180)
    gym_email: EmailStr | None = None
    gym_phone: str | None = Field(default=None, max_length=40)
    gym_address: str | None = Field(default=None, max_length=500)
    gym_timezone: str = Field(default="UTC", max_length=80)
    admin_full_name: str = Field(min_length=2, max_length=180)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8, max_length=72)
    admin_phone: str | None = Field(default=None, max_length=40)

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, value: object) -> object:
        return normalize_aliases(
            value,
            {
                "gymName": "gym_name",
                "gymEmail": "gym_email",
                "gymPhone": "gym_phone",
                "gymAddress": "gym_address",
                "gymTimezone": "gym_timezone",
                "adminFullName": "admin_full_name",
                "adminEmail": "admin_email",
                "adminPassword": "admin_password",
                "adminPhone": "admin_phone",
            },
        )

    @field_validator("admin_password")
    @classmethod
    def password_must_fit_bcrypt(cls, value: str) -> str:
        return validate_password_bytes(value)


class GymAdminRead(BaseModel):
    id: UUID
    gym_id: UUID
    email: EmailStr
    full_name: str
    role: RoleName
    phone: str | None
    is_active: bool


class GymAdminCreateResponse(BaseModel):
    gym: GymRead
    gym_admin: GymAdminRead
