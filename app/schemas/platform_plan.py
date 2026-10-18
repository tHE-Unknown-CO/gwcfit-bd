from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class PlatformPlanCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    billing_period: str | None = Field(default="month", max_length=40)
    member_limit: str = Field(min_length=1, max_length=120)
    features: list[str] = Field(min_length=1, max_length=30)
    cta_label: str = Field(min_length=1, max_length=120)
    trial_days: int = Field(default=30, ge=0, le=365)
    is_popular: bool = False
    display_order: int = Field(default=0, ge=0, le=1000)
    is_active: bool = True

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("features")
    @classmethod
    def clean_features(cls, value: list[str]) -> list[str]:
        cleaned = [feature.strip() for feature in value if feature.strip()]
        if not cleaned:
            raise ValueError("At least one feature is required.")
        return cleaned


class PlatformPlanRead(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    price_cents: int | None
    currency: str
    billing_period: str | None
    member_limit: str
    features: list[str]
    cta_label: str
    trial_days: int
    is_popular: bool
    display_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class PlatformPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    billing_period: str | None = Field(default=None, max_length=40)
    member_limit: str | None = Field(default=None, min_length=1, max_length=120)
    features: list[str] | None = Field(default=None, min_length=1, max_length=30)
    cta_label: str | None = Field(default=None, min_length=1, max_length=120)
    trial_days: int | None = Field(default=None, ge=0, le=365)
    is_popular: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("features")
    @classmethod
    def clean_features(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [feature.strip() for feature in value if feature.strip()]
        if not cleaned:
            raise ValueError("At least one feature is required.")
        if any(len(feature) > 200 for feature in cleaned):
            raise ValueError("Each feature must be 200 characters or fewer.")
        return cleaned

    @model_validator(mode="after")
    def reject_null_for_required_values(self):
        nullable_fields = {"price_cents", "billing_period"}
        for field in self.model_fields_set - nullable_fields:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        if not self.model_fields_set:
            raise ValueError("At least one plan field must be supplied.")
        return self
