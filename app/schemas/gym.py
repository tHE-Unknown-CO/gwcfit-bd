from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import EnterpriseRead


class GymCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    timezone: str = Field(default="UTC", max_length=80)


class GymUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    timezone: str | None = Field(default=None, max_length=80)
    settings: dict | None = None


class GymRead(EnterpriseRead):
    name: str
    code: str
    status: str
    email: str | None
    phone: str | None
    address: str | None
    timezone: str
    settings: dict


class GymSummary(BaseModel):
    id: UUID
    name: str
    code: str
    status: str


class GymOption(BaseModel):
    id: UUID
    name: str


class GymGalleryPhoto(BaseModel):
    url: str
    caption: str | None = None


class PublicGymDirectoryRead(BaseModel):
    id: UUID
    name: str
    code: str
    status: str
    business_email: EmailStr | None
    business_phone: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    distance_km: float | None = None
    description: str | None
    facilities: list[str]
    categories: list[str]
    gallery_photos: list[GymGalleryPhoto] = Field(default_factory=list)
    gender_policy: str | None
    opening_hours: dict
    starting_price_cents: int | None
    rating: float | None
    review_count: int
    trial_available: bool
    verified: bool
    plan_name: str | None
    subscription_status: str | None
    created_at: datetime
