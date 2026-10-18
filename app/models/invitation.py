import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, EnterpriseMixin
from app.models.enums import InvitationStatus


class Invitation(EnterpriseMixin, Base):
    __tablename__ = "invitations"

    gym_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=InvitationStatus.ACTIVE.value, server_default="active", nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    gym = relationship("Gym")
    used_by_user = relationship("User", foreign_keys=[used_by])
