from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.enums import PermissionCode, RoleName

MAX_PASSWORD_BYTES = 72


def validate_password_bytes(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be {MAX_PASSWORD_BYTES} bytes or fewer.")
    return value


def normalize_aliases(value: object, aliases: dict[str, str]) -> object:
    if not isinstance(value, dict):
        return value

    normalized = value.copy()
    for source, target in aliases.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized[source]
    return normalized


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthenticatedUser(BaseModel):
    id: UUID
    gym_id: UUID | None
    gym_name: str | None = None
    email: EmailStr
    full_name: str
    role: RoleName
    permissions: list[PermissionCode]


class AuthResponse(BaseModel):
    user: AuthenticatedUser
    tokens: TokenPair


class OwnerRegistrationRequest(BaseModel):
    gym_name: str = Field(min_length=2, max_length=180)
    full_name: str = Field(min_length=2, max_length=180)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    phone: str | None = Field(default=None, max_length=40)
    invitation_token: str = Field(min_length=20, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, value: object) -> object:
        return normalize_aliases(
            value,
            {
                "gymName": "gym_name",
                "fullName": "full_name",
                "invitationToken": "invitation_token",
            },
        )

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, value: str) -> str:
        return validate_password_bytes(value)


class GymUserRegistrationRequest(BaseModel):
    gym_id: UUID | None = None
    gym_name: str | None = Field(default=None, min_length=2, max_length=180)
    full_name: str = Field(min_length=2, max_length=180)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: RoleName | None = None
    invitation_token: str = Field(min_length=20, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, value: object) -> object:
        return normalize_aliases(
            value,
            {
                "gymId": "gym_id",
                "gymName": "gym_name",
                "fullName": "full_name",
                "invitationToken": "invitation_token",
            },
        )

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, value: str) -> str:
        return validate_password_bytes(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, value: str) -> str:
        return validate_password_bytes(value)


class RefreshTokenRequest(BaseModel):
    refresh_token: str

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, value: object) -> object:
        return normalize_aliases(value, {"refreshToken": "refresh_token"})


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_token: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=72)

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, value: object) -> object:
        return normalize_aliases(value, {"newPassword": "new_password"})

    @field_validator("new_password")
    @classmethod
    def password_must_fit_bcrypt(cls, value: str) -> str:
        return validate_password_bytes(value)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(max_length=72)
    new_password: str = Field(min_length=8, max_length=72)

    @model_validator(mode="before")
    @classmethod
    def normalize_field_names(cls, value: object) -> object:
        return normalize_aliases(value, {"oldPassword": "old_password", "newPassword": "new_password"})

    @field_validator("old_password", "new_password")
    @classmethod
    def password_must_fit_bcrypt(cls, value: str) -> str:
        return validate_password_bytes(value)


class VerifyEmailRequest(BaseModel):
    token: str
