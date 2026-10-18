from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationRead(BaseModel):
    id: UUID
    title: str
    body: str
    channel: str
    read_at: datetime | None = None
    created_at: datetime
    status: str
    gym_name: str | None = None
