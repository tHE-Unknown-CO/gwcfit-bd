from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, EnterpriseMixin


class PlatformPlan(EnterpriseMixin, Base):
    __tablename__ = "platform_plans"

    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR", nullable=False)
    billing_period: Mapped[str | None] = mapped_column(String(40), default="month", nullable=True)
    member_limit: Mapped[str] = mapped_column(String(120), nullable=False)
    features: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    cta_label: Mapped[str] = mapped_column(String(120), nullable=False)
    trial_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30", nullable=False)
    is_popular: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
