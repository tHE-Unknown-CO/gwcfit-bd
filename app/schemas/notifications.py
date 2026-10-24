from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationRead(BaseModel):
    id: UUID
    title: str
    body: str
    channel: str
    read_at: datetime | None = None
    created_at: datetime
    status: str
    gym_name: str | None = None
    category: str = "general"
    important: bool = False
    route: str | None = None
    resource_id: str | None = None


class PushDevice(BaseModel):
    token: str = Field(min_length=20, max_length=250, pattern=r"^(ExponentPushToken|ExpoPushToken)\[[A-Za-z0-9_-]+\]$")
