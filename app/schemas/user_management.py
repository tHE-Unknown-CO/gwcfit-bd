from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.enums import RoleName
from app.schemas.auth import validate_password_bytes
from app.schemas.common import EnterpriseRead

UserStatus = Literal["active", "inactive"]


def normalize_user_field_names(value: object) -> object:
    if not isinstance(value, dict):
        return value

    normalized = value.copy()
    aliases = {
        "name": "full_name",
        "fullName": "full_name",
        "gymId": "gym_id",
    }
    for source, target in aliases.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized[source]
    return normalized


class UserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=180)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str | None = Field(default=None, max_length=40)
    role: RoleName = RoleName.MEMBER
    gym_id: UUID | None = None
    status: UserStatus = "active"

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, value: object) -> object:
        return normalize_user_field_names(value)

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, value: str) -> str:
        return validate_password_bytes(value)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=180)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)
    phone: str | None = Field(default=None, max_length=40)
    role: RoleName | None = None
    gym_id: UUID | None = None
    status: UserStatus | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, value: object) -> object:
        return normalize_user_field_names(value)

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, value: str | None) -> str | None:
        return validate_password_bytes(value) if value is not None else value


class UserRead(EnterpriseRead):
    gym_id: UUID | None
    gym_name: str | None = None
    name: str
    full_name: str
    email: EmailStr
    phone: str | None
    role: RoleName
    status: UserStatus


class UserRoleCounts(BaseModel):
    total: int = 0
    member: int = 0
    trainer: int = 0
    receptionist: int = 0
    sub_admin: int = 0
    gym_owner: int = 0
