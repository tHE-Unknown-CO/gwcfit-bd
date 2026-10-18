import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, EnterpriseMixin, TenantMixin
from app.models.enums import PaymentStatus


class Payment(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "payments"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False)
    membership_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("membership_plans.id"),
        nullable=True,
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=PaymentStatus.PENDING.value, nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(180), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra_data: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    member = relationship("Member", foreign_keys=[member_id])
    membership_plan = relationship("MembershipPlan", foreign_keys=[membership_plan_id])

    @property
    def member_name(self) -> str | None:
        member = getattr(self, "member", None)
        if member is None or member.gym_id != self.gym_id:
            return None
        return member.member_name

    @property
    def membership_plan_name(self) -> str | None:
        membership_plan = getattr(self, "membership_plan", None)
        if membership_plan is None or membership_plan.gym_id != self.gym_id:
            return None
        return membership_plan.name


class Invoice(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "invoices"

    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(600), nullable=True)


class Subscription(EnterpriseMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("gym_id", name="uq_subscriptions_gym_id"),)

    gym_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("gyms.id"), nullable=False, index=True)
    platform_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    plan_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    billing_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_customer_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    limits: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
