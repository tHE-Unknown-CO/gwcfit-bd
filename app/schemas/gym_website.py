"""Public website fields only; never serialize private staff/account records."""
import re
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator, model_validator


def validate_image_url(value: str | None) -> str | None:
    if not value:
        return value
    if not re.match(r'^(https?://[^\s]+|/(?!/)[^\s]+|data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+)$', value):
        raise ValueError('Use an image URL or a PNG, JPEG or WebP upload.')
    return value


class WebsitePhoto(BaseModel):
    url: str = Field(min_length=1, max_length=3000000)
    caption: str | None = Field(default=None, max_length=240)
    _url = field_validator('url')(validate_image_url)


class WebsitePersonOverride(BaseModel):
    id: UUID
    photo_url: str | None = Field(default=None, max_length=3000000)
    bio: str | None = Field(default=None, max_length=1200)
    _photo = field_validator('photo_url')(validate_image_url)


class WebsiteOpeningHours(BaseModel):
    closed: bool = False
    open: str | None = Field(default=None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    close: str | None = Field(default=None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')

    @model_validator(mode='after')
    def require_times(self):
        if not self.closed and (not self.open or not self.close):
            raise ValueError('Provide opening and closing times, or mark the day closed.')
        return self


class WebsiteSocialLink(BaseModel):
    platform: Literal['instagram', 'facebook', 'youtube', 'whatsapp', 'x', 'linkedin', 'threads', 'tiktok', 'telegram', 'website', 'other']
    url: HttpUrl = Field(max_length=2000)
    label: str | None = Field(default=None, max_length=60)


class GymWebsiteEdit(BaseModel):
    social_links: list[WebsiteSocialLink] = Field(default_factory=list, max_length=20)
    name: str | None = Field(default=None, min_length=2, max_length=180)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    pincode: str | None = Field(default=None, max_length=20)
    business_phone: str | None = Field(default=None, max_length=40)
    business_email: EmailStr | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    opening_hours: dict[str, str | WebsiteOpeningHours] = Field(default_factory=dict, max_length=14)

    @model_validator(mode='after')
    def require_coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('Provide both latitude and longitude, or leave both empty.')
        return self

    @field_validator('opening_hours')
    @classmethod
    def validate_hours(cls, hours):
        for day, value in hours.items():
            if not day.strip() or len(day) > 40 or (isinstance(value, str) and (not value.strip() or len(value) > 100)):
                raise ValueError('Use a day label and valid opening hours.')
        return hours

    description: str | None = Field(default=None, max_length=4000)
    categories: list[str] = Field(default_factory=list, max_length=60)
    facilities: list[str] = Field(default_factory=list, max_length=100)
    gallery_photos: list[WebsitePhoto] = Field(default_factory=list, max_length=40)
    hero_photos: list[WebsitePhoto] = Field(default_factory=list, max_length=10)
    trainer_overrides: list[WebsitePersonOverride] = Field(default_factory=list, max_length=200)
    owner_overrides: list[WebsitePersonOverride] = Field(default_factory=list, max_length=50)
    hidden_trainer_ids: list[UUID] = Field(default_factory=list, max_length=200)
    hidden_owner_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator('categories', 'facilities')
    @classmethod
    def clean_labels(cls, values):
        if any(not value.strip() or len(value) > 160 for value in values):
            raise ValueError('Each item must contain 1–160 characters.')
        return list(dict.fromkeys(value.strip() for value in values))


class WebsitePerson(BaseModel):
    id: UUID
    full_name: str
    photo_url: str | None = None
    bio: str | None = None
    specialties: list[str] = Field(default_factory=list)


class WebsiteMembershipPlan(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    duration_days: int
    price_cents: int
    currency: str
    features: list[str] = Field(default_factory=list)


class GymWebsiteRead(BaseModel):
    social_links: list[WebsiteSocialLink] = Field(default_factory=list)
    id: UUID
    name: str
    address: str | None = None
    business_phone: str | None = None
    business_email: str | None = None
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    categories: list[str] = Field(default_factory=list)
    facilities: list[str] = Field(default_factory=list)
    gallery_photos: list[WebsitePhoto] = Field(default_factory=list)
    hero_photos: list[WebsitePhoto] = Field(default_factory=list)
    opening_hours: dict = Field(default_factory=dict)
    gender_policy: str | None = None
    verified: bool = False
    trial_available: bool = False
    trainers: list[WebsitePerson] = Field(default_factory=list)
    owners: list[WebsitePerson] = Field(default_factory=list)
    membership_plans: list[WebsiteMembershipPlan] = Field(default_factory=list)


class GymWebsiteEditorRead(BaseModel):
    profile: GymWebsiteEdit
    trainers: list[WebsitePerson]
    owners: list[WebsitePerson]
