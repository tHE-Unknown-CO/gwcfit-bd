import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, EnterpriseMixin, TenantMixin


class Notification(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "notifications"

    gym_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=True, index=True)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    body: Mapped[str] = mapped_column(String(1200), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), default="in_app", nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
