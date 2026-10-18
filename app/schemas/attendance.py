from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from app.models.enums import AttendanceSource
from app.schemas.common import EnterpriseRead


class AttendanceCreate(BaseModel):
    member_id: UUID
    trainer_id: UUID | None = None
    check_in_at: AwareDatetime
    check_out_at: AwareDatetime | None = None
    source: AttendanceSource = AttendanceSource.MANUAL
    notes: str | None = Field(default=None, max_length=600)
    device_payload: dict = Field(default_factory=dict)


class AttendanceUpdate(BaseModel):
    trainer_id: UUID | None = None
    check_out_at: AwareDatetime | None = None
    source: AttendanceSource | None = None
    notes: str | None = Field(default=None, max_length=600)
    device_payload: dict | None = None


class AttendanceQrScan(BaseModel):
    token: str = Field(min_length=20)


class DailyAttendanceQr(BaseModel):
    token: str
    gym_id: UUID
    gym_name: str
    attendance_date: str
    expires_at: datetime


class DailyAttendanceStats(BaseModel):
    attendance_date: str
    daily_visit_limit: int
    total_check_ins: int
    total_check_outs: int
    currently_checked_in: int
    checked_in_members: list["AttendanceRead"]


class AttendanceRead(EnterpriseRead):
    gym_id: UUID
    gym_name: str | None = None
    member_id: UUID
    member_name: str | None = None
    trainer_id: UUID | None
    trainer_name: str | None = None
    check_in_at: datetime
    check_out_at: datetime | None
    source: str
    notes: str | None
    device_payload: dict
