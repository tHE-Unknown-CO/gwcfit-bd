import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, EnterpriseMixin


class GymInquiry(EnterpriseMixin, Base):
    __tablename__ = "gym_inquiries"

    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    gym_name: Mapped[str] = mapped_column(String(180), nullable=False)
    active_members_range: Mapped[str] = mapped_column(String(40), nullable=False)
    interested_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="new", server_default="new", nullable=False, index=True)
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invitations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    gym_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="owner_site", server_default="owner_site", nullable=False)
