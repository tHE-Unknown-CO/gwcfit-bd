import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, EnterpriseMixin, TenantMixin


class TrainerFeedback(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "trainer_feedback"
    __table_args__ = (
        UniqueConstraint("gym_id", "member_id", "trainer_id", "review_month", name="uq_trainer_feedback_member_month"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_trainer_feedback_rating"),
    )

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True)
    trainer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False, index=True)
    review_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback_option: Mapped[str | None] = mapped_column(String(120), nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(String(1200), nullable=True)
