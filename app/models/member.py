import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, EnterpriseMixin, TenantMixin


class Member(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("gym_id", "member_code", name="uq_members_gym_member_code"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    trainer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trainers.id"), nullable=True)
    membership_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("membership_plans.id"),
        nullable=True,
    )
    member_code: Mapped[str] = mapped_column(String(40), nullable=False)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    membership_starts_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    membership_ends_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    emergency_contact: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    extra_data: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    trainer = relationship("Trainer", foreign_keys=[trainer_id])
    membership_plan = relationship("MembershipPlan", foreign_keys=[membership_plan_id])

    @property
    def member_name(self) -> str:
        return " ".join(part for part in [self.first_name, self.last_name] if part).strip()

    @property
    def user_name(self) -> str | None:
        user = getattr(self, "user", None)
        if user is None or user.gym_id != self.gym_id:
            return None
        return user.full_name

    @property
    def trainer_name(self) -> str | None:
        trainer = getattr(self, "trainer", None)
        if trainer is None or trainer.gym_id != self.gym_id:
            return None
        return trainer.full_name

    @property
    def membership_plan_name(self) -> str | None:
        membership_plan = getattr(self, "membership_plan", None)
        if membership_plan is None or membership_plan.gym_id != self.gym_id:
            return None
        return membership_plan.name
