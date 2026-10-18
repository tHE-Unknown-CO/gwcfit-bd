import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, EnterpriseMixin, TenantMixin
from app.models.enums import AttendanceSource

MAX_DAILY_VISITS = 4


class Attendance(TenantMixin, EnterpriseMixin, Base):
    __tablename__ = "attendance"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("members.id"), nullable=False)
    trainer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trainers.id"), nullable=True)
    check_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default=AttendanceSource.MANUAL.value, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(600), nullable=True)
    device_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

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
