import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, EnterpriseMixin, TenantMixin


class Trainer(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "trainers"
    __table_args__ = (UniqueConstraint("gym_id", "email", name="uq_trainers_gym_email"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    specialties: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    hourly_rate_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    commission_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    extra_data: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    user = relationship("User", foreign_keys=[user_id])

    @property
    def trainer_name(self) -> str:
        return self.full_name

    @property
    def user_name(self) -> str | None:
        user = getattr(self, "user", None)
        if user is None or user.gym_id != self.gym_id:
            return None
        return user.full_name
