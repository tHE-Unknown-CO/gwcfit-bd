from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, EnterpriseMixin
from app.models.enums import GymStatus


class Gym(EnterpriseMixin, Base):
    __tablename__ = "gyms"

    name: Mapped[str] = mapped_column(String(180), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default=GymStatus.ACTIVE.value, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC", nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    users = relationship("User", back_populates="gym")
