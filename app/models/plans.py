import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, EnterpriseMixin, TenantMixin


class MembershipPlan(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "membership_plans"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(800), nullable=True)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    features: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)


class WorkoutPlan(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "workout_plans"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False)
    trainer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trainers.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    goal: Mapped[str] = mapped_column(String(120), nullable=False)
    level: Mapped[str] = mapped_column(String(80), nullable=False)
    starts_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    sessions: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)

    member = relationship("Member", foreign_keys=[member_id])
    trainer = relationship("Trainer", foreign_keys=[trainer_id])

    @property
    def member_name(self) -> str | None:
        member = getattr(self, "member", None)
        if member is None or member.gym_id != self.gym_id:
            return None
        return member.member_name

    @property
    def trainer_name(self) -> str | None:
        trainer = getattr(self, "trainer", None)
        if trainer is None or trainer.gym_id != self.gym_id:
            return None
        return trainer.full_name


class DietPlan(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "diet_plans"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False)
    trainer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trainers.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="Custom", server_default="Custom")
    calories_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    meals: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)

    member = relationship("Member", foreign_keys=[member_id])
    trainer = relationship("Trainer", foreign_keys=[trainer_id])

    @property
    def member_name(self) -> str | None:
        member = getattr(self, "member", None)
        if member is None or member.gym_id != self.gym_id:
            return None
        return member.member_name

    @property
    def trainer_name(self) -> str | None:
        trainer = getattr(self, "trainer", None)
        if trainer is None or trainer.gym_id != self.gym_id:
            return None
        return trainer.full_name
