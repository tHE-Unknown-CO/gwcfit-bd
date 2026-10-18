from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from jose import jwt
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1._crud import get_or_404
from app.auth.jwt import create_token, decode_token
from app.core.config import get_settings
from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import require_permission
from app.dependencies.tenant import get_current_gym_id
from app.models.attendance import Attendance, MAX_DAILY_VISITS
from app.models.enums import AttendanceSource, PermissionCode, RoleName
from app.models.member import Member
from app.models.gym import Gym
from app.models.trainer import Trainer
from app.models.user import User
from app.permissions.rbac import has_permission
from app.repositories.base import TenantRepository
from app.schemas.attendance import AttendanceCreate, AttendanceQrScan, AttendanceRead, AttendanceUpdate, DailyAttendanceQr, DailyAttendanceStats
from app.schemas.common import MessageResponse

router = APIRouter(prefix="/attendance", tags=["attendance"])
settings = get_settings()


def _gym_day(gym: Gym) -> tuple[datetime, datetime, str]:
    try:
        zone = ZoneInfo(gym.timezone or "UTC")
    except ZoneInfoNotFoundError:
        zone = UTC
    now = datetime.now(zone)
    start = datetime.combine(now.date(), time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC), now.date().isoformat()


def _active_membership(member: Member, day: str) -> bool:
    local_date = datetime.fromisoformat(day).date()
    return (
        member.is_active
        and member.status.lower() == "active"
        and (member.membership_starts_at is None or member.membership_starts_at <= local_date)
        and (member.membership_ends_at is None or member.membership_ends_at >= local_date)
    )


@router.get("/daily/qr", response_model=DailyAttendanceQr)
def get_daily_attendance_qr(
    db: Session = Depends(get_db), gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE):
        raise HTTPException(status_code=403, detail="Attendance access is required.")
    gym = db.get(Gym, gym_id)
    if gym is None:
        raise HTTPException(status_code=404, detail="Gym was not found.")
    start, end, day = _gym_day(gym)
    # Fixed claims make every request for this gym/day return exactly the same QR.
    token = jwt.encode({"sub": str(gym.id), "user_id": str(gym.id), "type": "daily_attendance_qr",
        "role": "gym", "gym_id": str(gym.id), "permissions": [], "iat": start,
        "exp": end, "iss": settings.jwt_issuer, "aud": settings.jwt_audience,
        "attendance_date": day, "day_start": int(start.timestamp())},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return DailyAttendanceQr(token=token, gym_id=gym.id, gym_name=gym.name, attendance_date=day, expires_at=end)


@router.get("/daily/today", response_model=DailyAttendanceStats)
def today_attendance(
    db: Session = Depends(get_db), gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE):
        raise HTTPException(status_code=403, detail="Attendance access is required.")
    gym = db.get(Gym, gym_id)
    if gym is None:
        raise HTTPException(status_code=404, detail="Gym was not found.")
    start, end, day = _gym_day(gym)
    records = list(db.scalars(select(Attendance).where(Attendance.gym_id == gym_id,
        Attendance.is_active.is_(True), Attendance.check_in_at >= start, Attendance.check_in_at < end)
        .order_by(Attendance.check_in_at.desc())).all())
    active = [record for record in records if record.check_out_at is None]
    return DailyAttendanceStats(attendance_date=day, daily_visit_limit=MAX_DAILY_VISITS, total_check_ins=len(records),
        total_check_outs=sum(record.check_out_at is not None for record in records),
        currently_checked_in=len(active), checked_in_members=active)


@router.post("/daily/scan", response_model=AttendanceRead)
def scan_daily_attendance_qr(payload: AttendanceQrScan, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != RoleName.MEMBER.value:
        raise HTTPException(status_code=403, detail="Only members can scan the daily attendance QR code.")
    claims = decode_token(payload.token, expected_type="daily_attendance_qr")
    # Serialize scans for this member so two near-simultaneous requests cannot create
    # duplicate rows or turn an accidental double-tap into an immediate checkout.
    member = db.scalar(select(Member).where(Member.user_id == current_user.id, Member.is_active.is_(True)).with_for_update())
    if member is None:
        raise HTTPException(status_code=404, detail="Member profile was not found.")
    if claims.get("gym_id") != str(member.gym_id) or claims.get("sub") != str(member.gym_id):
        raise HTTPException(status_code=403, detail="This QR code belongs to another gym.")
    gym = db.get(Gym, member.gym_id)
    if gym is None:
        raise HTTPException(status_code=404, detail="Gym was not found.")
    start, end, day = _gym_day(gym)
    if claims.get("attendance_date") != day:
        raise HTTPException(status_code=410, detail="This attendance QR code has expired.")
    if not _active_membership(member, day):
        raise HTTPException(status_code=403, detail="An active membership is required.")
    records = list(db.scalars(select(Attendance).where(Attendance.gym_id == member.gym_id,
        Attendance.member_id == member.id, Attendance.is_active.is_(True),
        Attendance.check_in_at >= start, Attendance.check_in_at < end).order_by(Attendance.check_in_at.desc())).all())
    now = datetime.now(UTC)
    active = next((record for record in records if record.check_out_at is None), None)
    if active is not None:
        if (now - active.check_in_at).total_seconds() < 10:
            raise HTTPException(status_code=409, detail="Duplicate scan ignored. Please wait before scanning to check out.")
        active.check_out_at = now
        active.updated_by = current_user.id
        active.device_payload = {**(active.device_payload or {}), "checkout_actor": str(current_user.id)}
        attendance = active
    elif len(records) >= MAX_DAILY_VISITS:
        raise HTTPException(status_code=409, detail="Daily limit of 4 visits has been reached.")
    else:
        attendance = Attendance(gym_id=member.gym_id, member_id=member.id, trainer_id=member.trainer_id,
            check_in_at=now, source=AttendanceSource.QR_CODE.value, notes="Daily gym QR attendance",
            device_payload={"attendance_date": day, "actor": str(current_user.id)},
            created_by=current_user.id, updated_by=current_user.id)
        db.add(attendance)
    db.commit()
    db.refresh(attendance)
    return attendance


@router.post("/scan-qr", response_model=AttendanceRead)
def scan_attendance_qr(
    payload: AttendanceQrScan,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attendance access is required.")

    claims = decode_token(payload.token, expected_type="attendance_qr")
    if claims.get("gym_id") != str(gym_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This QR code belongs to another gym.")
    try:
        member_id = UUID(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid attendance QR code.") from exc
    action = claims.get("action")
    jti = claims.get("jti")
    if action not in {"check_in", "check_out"} or not jti:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid attendance QR action.")

    member = db.scalar(select(Member).where(Member.id == member_id, Member.gym_id == gym_id, Member.is_active.is_(True)))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member was not found.")
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        _ensure_trainer_member(db, trainer, member.id, gym_id)

    start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    records = list(db.scalars(select(Attendance).where(
        Attendance.gym_id == gym_id,
        Attendance.member_id == member.id,
        Attendance.is_active.is_(True),
        Attendance.check_in_at >= start,
        Attendance.check_in_at < start + timedelta(days=1),
    ).order_by(Attendance.check_in_at.desc())).all())
    if any((record.device_payload or {}).get("qr_jti") == jti for record in records):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This QR code has already been used.")
    active = next((record for record in records if record.check_out_at is None), None)

    if action == "check_in":
        if active is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Member is already checked in.")
        if len(records) >= MAX_DAILY_VISITS:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Daily limit of 4 visits has been reached.")
        attendance = Attendance(
            gym_id=gym_id,
            member_id=member.id,
            trainer_id=member.trainer_id,
            check_in_at=datetime.now(UTC),
            source=AttendanceSource.QR_CODE.value,
            notes="Reception QR check-in",
            device_payload={"qr_jti": jti, "scanned_by": str(current_user.id)},
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(attendance)
    else:
        if active is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active check-in was found.")
        attendance = active
        attendance.check_out_at = datetime.now(UTC)
        attendance.source = AttendanceSource.QR_CODE.value
        attendance.device_payload = {**(attendance.device_payload or {}), "qr_jti": jti, "scanned_by": str(current_user.id)}
        attendance.updated_by = current_user.id

    db.commit()
    db.refresh(attendance)
    return attendance


def _get_current_trainer(db: Session, current_user: User) -> Trainer | None:
    if current_user.role != RoleName.TRAINER.value or current_user.gym_id is None:
        return None

    return db.scalar(
        select(Trainer).where(
            Trainer.user_id == current_user.id,
            Trainer.gym_id == current_user.gym_id,
            Trainer.is_active.is_(True),
        )
    )


def _ensure_trainer_member(db: Session, trainer: Trainer | None, member_id: UUID, gym_id: UUID) -> None:
    if trainer is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer profile is not configured.")

    member = db.scalar(
        select(Member).where(
            Member.id == member_id,
            Member.gym_id == gym_id,
            Member.trainer_id == trainer.id,
            Member.is_active.is_(True),
        )
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only manage attendance for assigned members.")


@router.get("", response_model=list[AttendanceRead])
def list_attendance(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attendance access is required.")

    repo = TenantRepository(Attendance, db, gym_id)
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer profile is not configured.")
        statement = repo.base_query().where(Attendance.trainer_id == trainer.id)
        return list(db.scalars(statement.offset(skip).limit(min(limit, 200))).all())

    return repo.list(skip=skip, limit=limit)


@router.post("", response_model=AttendanceRead, status_code=201)
def create_attendance(
    payload: AttendanceCreate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attendance access is required.")

    check_in_at = payload.check_in_at.astimezone(UTC)
    day_start = datetime.combine(check_in_at.date(), time.min, tzinfo=UTC)
    daily_visits = len(list(db.scalars(select(Attendance.id).where(
        Attendance.gym_id == gym_id,
        Attendance.member_id == payload.member_id,
        Attendance.is_active.is_(True),
        Attendance.check_in_at >= day_start,
        Attendance.check_in_at < day_start + timedelta(days=1),
    )).all()))
    if daily_visits >= MAX_DAILY_VISITS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Daily limit of 4 visits has been reached.")

    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer profile is not configured.")
        _ensure_trainer_member(db, trainer, payload.member_id, gym_id)
        payload_data = payload.model_dump()
        payload_data["trainer_id"] = trainer.id
        return TenantRepository(Attendance, db, gym_id).create(payload_data, actor_id=current_user.id)

    return TenantRepository(Attendance, db, gym_id).create(payload.model_dump(), actor_id=current_user.id)


@router.get("/{attendance_id:uuid}", response_model=AttendanceRead)
def get_attendance(
    attendance_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attendance access is required.")

    attendance = get_or_404(TenantRepository(Attendance, db, gym_id), attendance_id, "Attendance")
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None or attendance.trainer_id != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only access assigned attendance records.")
    return attendance


@router.patch("/{attendance_id:uuid}", response_model=AttendanceRead)
def update_attendance(
    attendance_id: UUID,
    payload: AttendanceUpdate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attendance access is required.")

    repo = TenantRepository(Attendance, db, gym_id)
    attendance = get_or_404(repo, attendance_id, "Attendance")
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None or attendance.trainer_id != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only edit assigned attendance records.")
        if "trainer_id" in payload.model_fields_set and payload.trainer_id != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only assign attendance to themselves.")

    return repo.update(attendance, payload.model_dump(exclude_unset=True), actor_id=current_user.id)


@router.delete("/{attendance_id:uuid}", response_model=MessageResponse)
def delete_attendance(
    attendance_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    if not has_permission(current_user, PermissionCode.MANAGE_ATTENDANCE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attendance access is required.")

    repo = TenantRepository(Attendance, db, gym_id)
    attendance = get_or_404(repo, attendance_id, "Attendance")
    if current_user.role == RoleName.TRAINER.value:
        trainer = _get_current_trainer(db, current_user)
        if trainer is None or attendance.trainer_id != trainer.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trainer may only delete assigned attendance records.")

    repo.deactivate(attendance, actor_id=current_user.id)
    return MessageResponse(message="Attendance entry was deactivated.")
