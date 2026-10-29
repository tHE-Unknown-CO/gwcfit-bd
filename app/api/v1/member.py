from __future__ import annotations
from app.models.attendance import daily_visit_limit, checkout_ready, require_checkout_ready

from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.auth.jwt import create_token
from app.dependencies.permissions import require_member
from app.models.attendance import Attendance, MAX_DAILY_VISITS
from app.models.billing import Payment
from app.models.enums import AttendanceSource
from app.models.gym import Gym
from app.models.member import Member
from app.models.notification import Notification
from app.models.plans import DietPlan, WorkoutPlan, MembershipPlan
from app.models.trainer import Trainer
from app.models.trainer_feedback import TrainerFeedback
from app.models.user import User
from app.schemas.member_dashboard import (
    JsonDict,
    MemberActivitySync, MemberActivityDay, MemberActivityHistory,
    MemberAttendanceRecord,
    MemberAttendanceSummary,
    MemberAttendanceQrToken,
    MemberClassRead,
    MemberDashboardSummary,
    MemberGoalCreate,
    MemberGoalRead,
    MemberGoalUpdate,
    MemberMealComplete,
    MemberMealPlanRead,
    MemberAvailablePlan,
    MemberMembershipHistoryItem,
    MemberMembershipRead,
    MemberNotificationRead,
    MemberPaymentRead,
    MemberProfileRead,
    MemberProfileUpdate,
    MemberProgressLogCreate,
    MemberProgressLogRead,
    MemberRewardRead,
    MemberTrainerRead,
    
    MemberWorkoutComplete,
    MemberWorkoutRead,
    SupportTicketCreate,
    SupportTicketRead,
)
from app.schemas.trainer_feedback import MemberTrainerFeedbackRead, TrainerFeedbackUpsert
from app.services.auth import _ensure_member_profile_for_user

from app.services.member_activity import activity_day, merge_activity, snapshot_today, record_calorie_target

router = APIRouter(prefix="/member", tags=["member dashboard"])


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


def _as_dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _calculate_bmi(height: Any, weight: Any) -> float | None:
    height_cm = _safe_float(height)
    weight_kg = _safe_float(weight)
    if not height_cm or not weight_kg:
        return None
    height_m = height_cm / 100
    if height_m <= 0:
        return None
    return round(weight_kg / (height_m * height_m), 1)


def _days_remaining(expiry_date: date | None) -> int:
    if expiry_date is None:
        return 0
    return max((expiry_date - _today()).days, 0)


def _membership_status(member: Member) -> str:
    if member.membership_ends_at and member.membership_ends_at < _today():
        return "expired"
    return member.status


def _set_member_extra(member: Member, key: str, value: Any) -> None:
    member.extra_data = {**_as_dict(member.extra_data), key: value}


def _set_user_profile(user: User, key: str, value: Any) -> None:
    user.profile = {**_as_dict(user.profile), key: value}


def _member_base_statement(current_user: User):
    return select(Member).where(
        Member.user_id == current_user.id,
        Member.gym_id == current_user.gym_id,
        Member.is_active.is_(True),
    )


def _get_gym(db: Session, current_user: User) -> Gym:
    gym = db.scalar(select(Gym).where(Gym.id == current_user.gym_id, Gym.is_active.is_(True)))
    if gym is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gym was not found.")
    return gym


def _get_current_member(db: Session, current_user: User, *, lock: bool = False) -> Member:
    statement = _member_base_statement(current_user)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    member = db.scalar(statement)
    if member is not None:
        return member

    gym = _get_gym(db, current_user)
    member = _ensure_member_profile_for_user(db, current_user, gym)
    db.commit()
    db.refresh(member)
    return member


def _get_payments(db: Session, member: Member, limit: int = 200) -> list[Payment]:
    statement = (
        select(Payment)
        .where(
            Payment.gym_id == member.gym_id,
            Payment.member_id == member.id,
            Payment.is_active.is_(True),
        )
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def _get_attendance_records(db: Session, member: Member, limit: int = 200) -> list[Attendance]:
    statement = (
        select(Attendance)
        .where(
            Attendance.gym_id == member.gym_id,
            Attendance.member_id == member.id,
            Attendance.is_active.is_(True),
        )
        .order_by(Attendance.check_in_at.desc())
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def _get_workout_plans(db: Session, member: Member, limit: int = 100) -> list[WorkoutPlan]:
    statement = (
        select(WorkoutPlan)
        .where(
            WorkoutPlan.gym_id == member.gym_id,
            WorkoutPlan.member_id == member.id,
            WorkoutPlan.is_active.is_(True),
        )
        .order_by(WorkoutPlan.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def _get_meal_plans(db: Session, member: Member, limit: int = 100) -> list[DietPlan]:
    statement = (
        select(DietPlan)
        .where(
            DietPlan.gym_id == member.gym_id,
            DietPlan.member_id == member.id,
            DietPlan.is_active.is_(True),
        )
        .order_by(DietPlan.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def _today_window() -> tuple[datetime, datetime]:
    start = datetime.combine(_today(), time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _attendance_today(db: Session, member: Member) -> Attendance | None:
    start, end = _today_window()
    statement = (
        select(Attendance)
        .where(
            Attendance.gym_id == member.gym_id,
            Attendance.member_id == member.id,
            Attendance.is_active.is_(True),
            Attendance.check_in_at >= start,
            Attendance.check_in_at < end,
        )
        .order_by(Attendance.check_in_at.desc())
    )
    return db.scalar(statement)


def _attendance_count_today(db: Session, member: Member) -> int:
    start, end = _today_window()
    return len(list(db.scalars(select(Attendance.id).where(
        Attendance.gym_id == member.gym_id,
        Attendance.member_id == member.id,
        Attendance.is_active.is_(True),
        Attendance.check_in_at >= start,
        Attendance.check_in_at < end,
    )).all()))


def _extract_today_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    weekday = _now().strftime("%A").lower()
    today_iso = _today().isoformat()
    for item in items:
        item_day = str(item.get("day") or item.get("weekday") or "").lower()
        item_date = str(item.get("date") or "")
        if item_date == today_iso or item_day == weekday:
            return item
    return items[0]


def _completion_status(logs: list[Any], key: str, resource_id: UUID) -> str:
    for log in logs:
        if isinstance(log, dict) and str(log.get(key)) == str(resource_id):
            return str(log.get("status") or "completed")
    return "not_started"


def _profile_response(member: Member) -> MemberProfileRead:
    extra = _as_dict(member.extra_data)
    height = _safe_float(extra.get("height"))
    weight = _safe_float(extra.get("weight"))
    return MemberProfileRead(
        member_uuid=member.id,
        member_name=member.member_name,
        member_code=member.member_code,
        email=member.email,
        phone=member.phone,
        gender=extra.get("gender"),
        date_of_birth=extra.get("date_of_birth"),
        address=extra.get("address"),
        emergency_contact=_as_dict(member.emergency_contact),
        height=height,
        weight=weight,
        bmi=_safe_float(extra.get("bmi")) or _calculate_bmi(height, weight),
        fitness_goal=extra.get("fitness_goal"),
        medical_conditions=extra.get("medical_conditions"),
        profile_photo=extra.get("profile_photo"),
        trainer_uuid=member.trainer_id,
        trainer_name=member.trainer_name,
        gym_uuid=member.gym_id,
        gym_name=member.gym_name,
        membership_plan_uuid=member.membership_plan_id,
        membership_plan_name=member.membership_plan_name,
        membership_status=_membership_status(member),
    )


def _payment_response(payment: Payment, member: Member) -> MemberPaymentRead:
    extra = _as_dict(payment.extra_data)
    status_value = str(payment.status)
    paid_amount = payment.amount_cents if status_value == "paid" else 0
    due_amount = payment.amount_cents if status_value in {"pending", "failed"} else 0
    return MemberPaymentRead(
        payment_uuid=payment.id,
        gym_uuid=payment.gym_id,
        gym_name=payment.gym_name,
        member_uuid=member.id,
        member_name=member.member_name,
        membership_plan_uuid=payment.membership_plan_id,
        membership_plan_name=payment.membership_plan_name,
        amount_cents=payment.amount_cents,
        paid_amount_cents=paid_amount,
        due_amount_cents=due_amount,
        currency=payment.currency,
        payment_method=payment.method,
        payment_date=payment.paid_at or payment.created_at,
        invoice_number=extra.get("invoice_number") or payment.provider_reference,
        receipt_url=extra.get("receipt_url"),
        status=status_value,
    )


def _attendance_response(record: Attendance, member: Member) -> MemberAttendanceRecord:
    return MemberAttendanceRecord(
        attendance_uuid=record.id,
        gym_uuid=record.gym_id,
        gym_name=record.gym_name,
        member_uuid=member.id,
        member_name=member.member_name,
        trainer_uuid=record.trainer_id,
        trainer_name=record.trainer_name,
        check_in_at=record.check_in_at,
        check_out_at=record.check_out_at,
        source=record.source,
        status="checked_out" if record.check_out_at else "checked_in",
        notes=record.notes,
    )


def _workout_response(plan: WorkoutPlan, member: Member) -> MemberWorkoutRead:
    extra = _as_dict(member.extra_data)
    sessions = [item for item in _as_list(plan.sessions) if isinstance(item, dict)]
    completions = _as_list(extra.get("workout_completions"))
    completed_count = sum(
        1 for item in completions if isinstance(item, dict) and str(item.get("workout_plan_uuid")) == str(plan.id)
    )
    status_value = _completion_status(completions, "workout_plan_uuid", plan.id)
    return MemberWorkoutRead(
        workout_plan_uuid=plan.id,
        workout_plan_name=plan.title,
        gym_uuid=plan.gym_id,
        gym_name=plan.gym_name,
        member_uuid=member.id,
        member_name=member.member_name,
        trainer_uuid=plan.trainer_id,
        trainer_name=plan.trainer_name,
        goal=plan.goal,
        level=plan.level,
        starts_at=plan.starts_at,
        ends_at=plan.ends_at,
        today_workout=_extract_today_item(sessions),
        weekly_plan=sessions,
        sessions=sessions,
        completion_status=status_value,
        completed_workouts=completed_count,
        missed_workouts=0,
        weekly_consistency=min(100.0, float(completed_count) * 20.0),
        personal_records=[item for item in _as_list(extra.get("personal_records")) if isinstance(item, dict)],
        trainer_notes=_as_dict(sessions[0]).get("trainer_notes") if sessions else None,
    )


def _meal_response(plan: DietPlan, member: Member) -> MemberMealPlanRead:
    extra = _as_dict(member.extra_data)
    meals = [item for item in _as_list(plan.meals) if isinstance(item, dict)]
    completions = _as_list(extra.get("meal_completions"))
    first_meal = _as_dict(meals[0] if meals else {})
    return MemberMealPlanRead(
        meal_plan_uuid=plan.id,
        meal_plan_name=plan.title,
        gym_uuid=plan.gym_id,
        gym_name=plan.gym_name,
        member_uuid=member.id,
        member_name=member.member_name,
        trainer_uuid=plan.trainer_id,
        trainer_name=plan.trainer_name,
        calories_per_day=plan.calories_per_day,
        starts_at=plan.starts_at,
        ends_at=plan.ends_at,
        today_meal_plan=_extract_today_item(meals),
        meals=meals,
        water_target_ml=first_meal.get("water_target_ml") or extra.get("water_target_ml"),
        trainer_notes=first_meal.get("trainer_notes"),
        completion_status=_completion_status(completions, "meal_plan_uuid", plan.id),
    )


def _progress_response(raw: dict[str, Any]) -> MemberProgressLogRead:
    logged_at = raw.get("logged_at")
    if not isinstance(logged_at, datetime):
        try:
            logged_at = datetime.fromisoformat(str(logged_at).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            logged_at = _now()
    return MemberProgressLogRead(
        progress_uuid=_coerce_uuid(raw.get("progress_uuid")) or uuid4(),
        logged_at=logged_at,
        weight=_safe_float(raw.get("weight")),
        bmi=_safe_float(raw.get("bmi")),
        body_fat_percentage=_safe_float(raw.get("body_fat_percentage")),
        muscle_mass=_safe_float(raw.get("muscle_mass")),
        calories_burned=raw.get("calories_burned"),
        measurements=_as_dict(raw.get("measurements")),
        photo_url=raw.get("photo_url"),
        goal_progress_percentage=_safe_float(raw.get("goal_progress_percentage")),
        notes=raw.get("notes"),
    )


def _class_uuid(raw: dict[str, Any], gym_id: UUID) -> UUID:
    provided = raw.get("class_uuid") or raw.get("id")
    coerced = _coerce_uuid(provided)
    if coerced:
        return coerced
    key = f"{gym_id}:{raw.get('class_name') or raw.get('name')}:{raw.get('date')}:{raw.get('time')}"
    return uuid5(NAMESPACE_URL, key)


def _gym_classes(gym: Gym) -> list[dict[str, Any]]:
    settings = _as_dict(gym.settings)
    classes = settings.get("member_classes") or settings.get("classes")
    return [item for item in _as_list(classes) if isinstance(item, dict)]


def _member_bookings(member: Member) -> list[dict[str, Any]]:
    return [item for item in _as_list(_as_dict(member.extra_data).get("class_bookings")) if isinstance(item, dict)]


def _class_response(raw: dict[str, Any], gym: Gym, member: Member) -> MemberClassRead:
    class_id = _class_uuid(raw, gym.id)
    bookings = _member_bookings(member)
    own_booking = next(
        (item for item in bookings if str(item.get("class_uuid")) == str(class_id) and item.get("status") != "cancelled"),
        None,
    )
    capacity = int(raw.get("capacity") or 0)
    booked_count = int(raw.get("booked_count") or 0)
    if own_booking and own_booking.get("status") == "booked":
        booked_count = max(booked_count, 1)
    available = max(capacity - booked_count, 0) if capacity else 0
    trainer_id = _coerce_uuid(raw.get("trainer_uuid") or raw.get("trainer_id"))
    return MemberClassRead(
        class_uuid=class_id,
        class_name=str(raw.get("class_name") or raw.get("name") or "Class"),
        gym_uuid=gym.id,
        gym_name=gym.name,
        trainer_uuid=trainer_id,
        trainer_name=raw.get("trainer_name"),
        date=raw.get("date"),
        time=raw.get("time"),
        duration_minutes=raw.get("duration_minutes") or raw.get("duration"),
        capacity=capacity,
        available_seats=available,
        class_type=str(raw.get("class_type") or raw.get("type") or "Fitness"),
        booking_status=str(own_booking.get("status") if own_booking else "available"),
    )


def _notification_response(notification: Notification) -> MemberNotificationRead:
    payload = _as_dict(notification.payload)
    return MemberNotificationRead(
        notification_uuid=notification.id,
        title=notification.title,
        body=notification.body,
        notification_type=str(payload.get("type") or payload.get("notification_type") or notification.channel),
        read_at=notification.read_at,
        created_at=notification.created_at,
        status="read" if notification.read_at else "unread",
        payload=payload,
    )


def _goal_response(raw: dict[str, Any]) -> MemberGoalRead:
    created_at = raw.get("created_at")
    completed_at = raw.get("completed_at")
    if not isinstance(created_at, datetime):
        try:
            created_at = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            created_at = _now()
    if completed_at and not isinstance(completed_at, datetime):
        try:
            completed_at = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            completed_at = None
    return MemberGoalRead(
        goal_uuid=_coerce_uuid(raw.get("goal_uuid")) or uuid4(),
        goal_name=str(raw.get("goal_name") or "Fitness goal"),
        target_weight=_safe_float(raw.get("target_weight")),
        target_date=raw.get("target_date"),
        progress_percentage=_safe_float(raw.get("progress_percentage")) or 0,
        workout_goal=raw.get("workout_goal"),
        water_intake_goal=raw.get("water_intake_goal"),
        attendance_goal=raw.get("attendance_goal"),
        calories_goal=raw.get("calories_goal"),
        status=str(raw.get("status") or "active"),
        created_at=created_at,
        completed_at=completed_at,
    )


def _reward_response(raw: dict[str, Any]) -> MemberRewardRead:
    return MemberRewardRead(
        reward_uuid=_coerce_uuid(raw.get("reward_uuid") or raw.get("id")) or uuid4(),
        title=str(raw.get("title") or raw.get("name") or "Reward"),
        description=raw.get("description"),
        points=int(raw.get("points") or 0),
        badge=raw.get("badge"),
        status=str(raw.get("status") or "active"),
        challenge_type=raw.get("challenge_type"),
        privacy_safe_rank=raw.get("privacy_safe_rank"),
    )


@router.get("/dashboard", response_model=MemberDashboardSummary)
def get_member_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberDashboardSummary:
    member = _get_current_member(db, current_user)
    gym = _get_gym(db, current_user)
    profile = _profile_response(member)
    payments = _get_payments(db, member)
    attendance = _attendance_today(db, member)
    workouts = _get_workout_plans(db, member, limit=1)
    meals = _get_meal_plans(db, member, limit=1)
    classes = [_class_response(raw, gym, member) for raw in _gym_classes(gym)]
    upcoming_class = next((item for item in classes if item.booking_status in {"booked", "available"}), None)
    pending_payments = [payment for payment in payments if str(payment.status) in {"pending", "failed"}]
    progress_logs = _as_list(_as_dict(member.extra_data).get("progress_logs"))
    latest_progress = _as_dict(progress_logs[0]) if progress_logs else {}

    return MemberDashboardSummary(
        member_uuid=member.id,
        member_name=member.member_name,
        gym_uuid=gym.id,
        gym_name=gym.name,
        profile_photo=profile.profile_photo,
        membership_status=profile.membership_status,
        membership_expiry_date=member.membership_ends_at,
        days_remaining=_days_remaining(member.membership_ends_at),
        assigned_trainer_name=member.trainer_name,
        today_attendance_status="checked_in" if attendance and not attendance.check_out_at else "not_checked_in",
        today_workout_plan=_workout_response(workouts[0], member) if workouts else None,
        today_meal_plan=_meal_response(meals[0], member) if meals else None,
        pending_payment_amount_cents=sum(payment.amount_cents for payment in pending_payments),
        pending_payment_currency=pending_payments[0].currency if pending_payments else "USD",
        upcoming_class=upcoming_class,
        fitness_goal_progress=_safe_float(latest_progress.get("goal_progress_percentage")) or 0,
        quick_actions=[
            "Scan QR / Check In",
            "Start Workout",
            "Log Weight",
            "Log Water",
            "Book Class",
            "View Membership",
            "Contact Trainer",
            "View Progress",
        ],
    )


@router.get("/profile", response_model=MemberProfileRead)
def get_member_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberProfileRead:
    return _profile_response(_get_current_member(db, current_user))


@router.patch("/profile", response_model=MemberProfileRead)
def update_member_profile(
    payload: MemberProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberProfileRead:
    member = _get_current_member(db, current_user)
    values = payload.model_dump(exclude_unset=True)
    extra = _as_dict(member.extra_data)

    if "phone" in values:
        member.phone = values["phone"]
        current_user.phone = values["phone"]
    if "emergency_contact" in values:
        member.emergency_contact = _as_dict(values["emergency_contact"])
    for key in ("address", "height", "weight", "fitness_goal", "profile_photo"):
        if key in values:
            extra[key] = values[key]
            _set_user_profile(current_user, key, values[key])
    if "height" in values or "weight" in values:
        extra["bmi"] = _calculate_bmi(extra.get("height"), extra.get("weight"))

    member.extra_data = extra
    member.updated_by = current_user.id
    current_user.updated_by = current_user.id
    db.commit()
    db.refresh(member)
    return _profile_response(member)


@router.get("/membership", response_model=MemberMembershipRead)
def get_member_membership(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberMembershipRead:
    member = _get_current_member(db, current_user)
    payments = _get_payments(db, member)
    plan = member.membership_plan
    history = [
        MemberMembershipHistoryItem(
            membership_uuid=payment.id,
            membership_plan_uuid=payment.membership_plan_id,
            membership_plan_name=(payment.extra_data or {}).get("plan_name") or payment.membership_plan_name,
            start_date=(payment.extra_data or {}).get("start_date") if (payment.extra_data or {}).get("source") == "member_checkout" else member.membership_starts_at,
            expiry_date=(payment.extra_data or {}).get("expiry_date") if (payment.extra_data or {}).get("source") == "member_checkout" else member.membership_ends_at,
            status=str(payment.status),
            amount_cents=payment.amount_cents,
            currency=payment.currency,
            paid_at=payment.paid_at,
        )
        for payment in payments
    ]
    days_left = _days_remaining(member.membership_ends_at)
    return MemberMembershipRead(
        membership_uuid=member.id,
        member_uuid=member.id,
        member_name=member.member_name,
        gym_uuid=member.gym_id,
        gym_name=member.gym_name,
        membership_plan_uuid=member.membership_plan_id,
        membership_plan_name=member.membership_plan_name,
        plan_price_cents=plan.price_cents if plan is not None and plan.gym_id == member.gym_id else 0,
        plan_currency=plan.currency if plan is not None and plan.gym_id == member.gym_id else "USD",
        plan_duration_days=plan.duration_days if plan is not None and plan.gym_id == member.gym_id else None,
        start_date=member.membership_starts_at,
        expiry_date=member.membership_ends_at,
        status=_membership_status(member),
        days_remaining=days_left,
        renewal_reminder="Renew soon" if 0 < days_left <= 7 else "No reminder",
        benefits=plan.features if plan is not None and plan.gym_id == member.gym_id else [],
        available_plans=[
            MemberAvailablePlan(plan_uuid=item.id, name=item.name,
                description=item.description, duration_days=item.duration_days,
                price_cents=item.price_cents, currency=item.currency, benefits=item.features or [])
            for item in db.scalars(select(MembershipPlan).where(
                MembershipPlan.gym_id == member.gym_id,
                MembershipPlan.is_active.is_(True),
            ).order_by(MembershipPlan.price_cents, MembershipPlan.name, MembershipPlan.id)).all()
        ],
        history=history,
    )


@router.get("/payments", response_model=list[MemberPaymentRead])
def get_member_payments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> list[MemberPaymentRead]:
    member = _get_current_member(db, current_user)
    return [_payment_response(payment, member) for payment in _get_payments(db, member)]


@router.get("/payments/{payment_id}/receipt")
def get_member_receipt(payment_id: UUID, db: Session = Depends(get_db),
    current_user: User = Depends(require_member)):
    member = _get_current_member(db, current_user)
    payment = db.scalar(select(Payment).where(Payment.id == payment_id,
        Payment.member_id == member.id, Payment.gym_id == member.gym_id, Payment.is_active.is_(True)))
    if payment is None:
        raise HTTPException(404, "Payment not found")
    if str(payment.status) != "paid":
        raise HTTPException(409, "A receipt is available only after payment is confirmed by your gym.")
    extra = _as_dict(payment.extra_data)
    gym = db.scalar(select(Gym).where(Gym.id == member.gym_id))
    return {
        "receipt_number": "RCP-" + str(payment.id).upper(),
        "payment_uuid": str(payment.id), "gym_name": gym.name if gym else member.gym_name or "Gym",
        "gym_address": gym.address if gym else None, "gym_phone": gym.phone if gym else None,
        "member_name": member.member_name, "member_code": member.member_code,
        "plan_name": extra.get("plan_name") or payment.membership_plan_name or "Membership payment",
        "amount_cents": payment.amount_cents, "currency": payment.currency,
        "paid_at": payment.paid_at or payment.created_at, "payment_method": payment.method,
        "transaction_reference": payment.provider_reference,
        "start_date": extra.get("start_date"), "expiry_date": extra.get("expiry_date"),
    }


@router.get("/attendance", response_model=MemberAttendanceSummary)
def get_member_attendance(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberAttendanceSummary:
    member = _get_current_member(db, current_user)
    records = _get_attendance_records(db, member)
    today_record = _attendance_today(db, member)
    today_visits = _attendance_count_today(db, member)
    current_date = _today()
    monthly_count = sum(
        1
        for record in records
        if record.check_in_at.month == current_date.month and record.check_in_at.year == current_date.year
    )
    elapsed_days = current_date.day
    percentage = round((monthly_count / elapsed_days) * 100, 1) if elapsed_days else 0
    return MemberAttendanceSummary(
        today_status="checked_in" if today_record and not today_record.check_out_at else "not_checked_in",
        today_visit_count=today_visits,
        daily_visit_limit=daily_visit_limit(db, member),
        can_check_in=(today_record is None or today_record.check_out_at is not None) and today_visits < daily_visit_limit(db, member),
        can_check_out=today_record is not None and today_record.check_out_at is None and checkout_ready(today_record),
        monthly_attendance_count=monthly_count,
        attendance_percentage=min(percentage, 100.0),
        missed_days=max(elapsed_days - monthly_count, 0),
        history=[_attendance_response(record, member) for record in records],
    )


@router.post("/attendance/qr-token", response_model=MemberAttendanceQrToken)
def create_member_attendance_qr_token(
    action: str = Query(pattern="^(check_in|check_out)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberAttendanceQrToken:
    member = _get_current_member(db, current_user)
    today_record = _attendance_today(db, member)
    today_visits = _attendance_count_today(db, member)
    if action == "check_in" and today_record is not None and today_record.check_out_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Member is already checked in.")
    if action == "check_in" and today_visits >= daily_visit_limit(db, member):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Your membership plan daily visit limit has been reached.")
    if action == "check_out" and (today_record is None or today_record.check_out_at is not None):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active check-in was found.")

    if action == "check_out":
        require_checkout_ready(today_record)
    expires_in = 120
    token = create_token(
        subject=member.id,
        token_type="attendance_qr",
        role="member",
        gym_id=member.gym_id,
        expires_delta=timedelta(seconds=expires_in),
        extra_claims={"action": action, "jti": str(uuid4())},
    )
    return MemberAttendanceQrToken(token=token, action=action, expires_in_seconds=expires_in)


@router.post("/attendance/check-in", response_model=MemberAttendanceRecord, status_code=201)
def check_in_member(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberAttendanceRecord:
    member = _get_current_member(db, current_user)
    existing = _attendance_today(db, member)
    if existing and existing.check_out_at is None:
        return _attendance_response(existing, member)
    if _attendance_count_today(db, member) >= daily_visit_limit(db, member):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Your membership plan daily visit limit has been reached.")

    attendance = Attendance(
        gym_id=member.gym_id,
        member_id=member.id,
        trainer_id=member.trainer_id,
        check_in_at=_now(),
        source=AttendanceSource.MANUAL.value,
        notes="Member self check-in",
        device_payload={"actor": "member_dashboard"},
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(attendance)
    db.commit()
    db.refresh(attendance)
    return _attendance_response(attendance, member)


@router.post("/attendance/check-out", response_model=MemberAttendanceRecord)
def check_out_member(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberAttendanceRecord:
    member = _get_current_member(db, current_user)
    attendance = _attendance_today(db, member)
    if attendance is None or attendance.check_out_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active check-in was found.")
    require_checkout_ready(attendance)
    attendance.check_out_at = _now()
    attendance.updated_by = current_user.id
    db.commit()
    db.refresh(attendance)
    return _attendance_response(attendance, member)


@router.get("/workouts", response_model=list[MemberWorkoutRead])
def get_member_workouts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> list[MemberWorkoutRead]:
    member = _get_current_member(db, current_user)
    return [_workout_response(plan, member) for plan in _get_workout_plans(db, member)]


@router.post("/workouts/{plan_id}/complete", response_model=MemberWorkoutRead)
def complete_member_workout(
    plan_id: UUID,
    payload: MemberWorkoutComplete | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberWorkoutRead:
    member = _get_current_member(db, current_user)
    plan = db.scalar(
        select(WorkoutPlan).where(
            WorkoutPlan.id == plan_id,
            WorkoutPlan.gym_id == member.gym_id,
            WorkoutPlan.member_id == member.id,
            WorkoutPlan.is_active.is_(True),
        )
    )
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workout plan was not found.")
    extra = _as_dict(member.extra_data)
    completions = _as_list(extra.get("workout_completions"))
    completions.insert(
        0,
        {
            "workout_plan_uuid": str(plan.id),
            "workout_plan_name": plan.title,
            "completed_at": _now().isoformat(),
            "status": "completed",
            "notes": payload.notes if payload else None,
            "exercises": payload.exercises if payload else [],
        },
    )
    _set_member_extra(member, "workout_completions", completions[:200])
    member.updated_by = current_user.id
    db.commit()
    db.refresh(member)
    return _workout_response(plan, member)


@router.get("/meals", response_model=list[MemberMealPlanRead])
def get_member_meals(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> list[MemberMealPlanRead]:
    member = _get_current_member(db, current_user)
    return [_meal_response(plan, member) for plan in _get_meal_plans(db, member)]


@router.post("/meals/{plan_id}/complete", response_model=MemberMealPlanRead)
def complete_member_meal(
    plan_id: UUID,
    payload: MemberMealComplete | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberMealPlanRead:
    member = _get_current_member(db, current_user)
    plan = db.scalar(
        select(DietPlan).where(
            DietPlan.id == plan_id,
            DietPlan.gym_id == member.gym_id,
            DietPlan.member_id == member.id,
            DietPlan.is_active.is_(True),
        )
    )
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal plan was not found.")
    extra = _as_dict(member.extra_data)
    completions = _as_list(extra.get("meal_completions"))
    completions.insert(
        0,
        {
            "meal_plan_uuid": str(plan.id),
            "meal_plan_name": plan.title,
            "completed_at": _now().isoformat(),
            "status": "completed",
            "notes": payload.notes if payload else None,
            "water_ml": payload.water_ml if payload else None,
            "extra_meal": payload.extra_meal if payload else None,
        },
    )
    _set_member_extra(member, "meal_completions", completions[:200])
    member.updated_by = current_user.id
    db.commit()
    db.refresh(member)
    return _meal_response(plan, member)


@router.get("/progress", response_model=list[MemberProgressLogRead])
def get_member_progress(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> list[MemberProgressLogRead]:
    member = _get_current_member(db, current_user)
    logs = [item for item in _as_list(_as_dict(member.extra_data).get("progress_logs")) if isinstance(item, dict)]
    return [_progress_response(item) for item in logs]


@router.post("/progress", response_model=MemberProgressLogRead, status_code=201)
def create_member_progress_log(
    payload: MemberProgressLogCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberProgressLogRead:
    member = _get_current_member(db, current_user, lock=True)
    extra = _as_dict(member.extra_data)
    logs = [item for item in _as_list(extra.get("progress_logs")) if isinstance(item, dict)]
    data = payload.model_dump()
    if data.get("weight") is not None and data.get("bmi") is None:
        data["bmi"] = _calculate_bmi(extra.get("height"), data["weight"])
    raw = {
        "progress_uuid": str(uuid4()),
        "logged_at": _now().isoformat(),
        **data,
    }
    logs.insert(0, raw)
    extra["progress_logs"] = logs[:300]
    if data.get("weight") is not None:
        extra["weight"] = data["weight"]
    if data.get("bmi") is not None:
        extra["bmi"] = data["bmi"]
    member.extra_data = snapshot_today(extra, _now())
    member.updated_by = current_user.id
    db.commit()
    db.refresh(member)
    return _progress_response(raw)


@router.get("/trainer", response_model=MemberTrainerRead | None)
def get_member_trainer(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberTrainerRead | None:
    member = _get_current_member(db, current_user)
    if member.trainer_id is None:
        return None
    trainer = db.scalar(
        select(Trainer).where(
            Trainer.id == member.trainer_id,
            Trainer.gym_id == member.gym_id,
            Trainer.is_active.is_(True),
        )
    )
    if trainer is None:
        return None
    trainer_extra = _as_dict(trainer.extra_data)
    workouts = _get_workout_plans(db, member)
    meals = _get_meal_plans(db, member)
    return MemberTrainerRead(
        trainer_uuid=trainer.id,
        trainer_name=trainer.full_name,
        trainer_photo=trainer_extra.get("photo") or trainer_extra.get("profile_photo"),
        email=trainer.email,
        phone=trainer.phone,
        specialization=trainer.specialties,
        schedule=[item for item in _as_list(trainer_extra.get("schedule")) if isinstance(item, dict)],
        assigned_workout_plans=[plan.title for plan in workouts],
        assigned_meal_plans=[plan.title for plan in meals],
        trainer_notes=trainer_extra.get("notes") or trainer.bio,
    )


def _feedback_response(record: TrainerFeedback) -> MemberTrainerFeedbackRead:
    return MemberTrainerFeedbackRead(
        id=record.id, trainer_id=record.trainer_id, review_month=record.review_month,
        rating=record.rating, feedback_option=record.feedback_option, feedback_text=record.feedback_text,
        created_at=record.created_at, updated_at=record.updated_at,
    )


@router.get("/trainer/feedback", response_model=MemberTrainerFeedbackRead | None)
def get_member_trainer_feedback(
    db: Session = Depends(get_db), current_user: User = Depends(require_member),
) -> MemberTrainerFeedbackRead | None:
    member = _get_current_member(db, current_user)
    if member.trainer_id is None:
        return None
    month = _today().replace(day=1)
    record = db.scalar(select(TrainerFeedback).where(
        TrainerFeedback.gym_id == member.gym_id, TrainerFeedback.member_id == member.id,
        TrainerFeedback.trainer_id == member.trainer_id, TrainerFeedback.review_month == month,
        TrainerFeedback.is_active.is_(True),
    ))
    return _feedback_response(record) if record else None


@router.put("/trainer/feedback", response_model=MemberTrainerFeedbackRead)
def upsert_member_trainer_feedback(
    payload: TrainerFeedbackUpsert,
    db: Session = Depends(get_db), current_user: User = Depends(require_member),
) -> MemberTrainerFeedbackRead:
    member = _get_current_member(db, current_user, lock=True)
    if member.trainer_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have an assigned trainer.")
    trainer = db.scalar(select(Trainer.id).where(
        Trainer.id == member.trainer_id, Trainer.gym_id == member.gym_id, Trainer.is_active.is_(True),
    ))
    if trainer is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your assigned trainer is unavailable.")
    month = _today().replace(day=1)
    record = db.scalar(select(TrainerFeedback).where(
        TrainerFeedback.gym_id == member.gym_id, TrainerFeedback.member_id == member.id,
        TrainerFeedback.trainer_id == member.trainer_id, TrainerFeedback.review_month == month,
    ).with_for_update())
    values = payload.model_dump()
    if record is None:
        record = TrainerFeedback(gym_id=member.gym_id, member_id=member.id, trainer_id=member.trainer_id,
                                 review_month=month, created_by=current_user.id, updated_by=current_user.id, **values)
        db.add(record)
    else:
        for key, value in values.items():
            setattr(record, key, value)
        record.updated_by = current_user.id
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A review already exists for this trainer this month.") from exc
    db.refresh(record)
    return _feedback_response(record)


@router.get("/classes", response_model=list[MemberClassRead])
def get_member_classes(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> list[MemberClassRead]:
    member = _get_current_member(db, current_user)
    gym = _get_gym(db, current_user)
    return [_class_response(raw, gym, member) for raw in _gym_classes(gym)]


@router.post("/classes/{class_id}/book", response_model=MemberClassRead)
def book_member_class(
    class_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberClassRead:
    member = _get_current_member(db, current_user)
    gym = _get_gym(db, current_user)
    class_raw = next((raw for raw in _gym_classes(gym) if _class_uuid(raw, gym.id) == class_id), None)
    if class_raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class was not found.")
    current = _class_response(class_raw, gym, member)
    if current.booking_status in {"booked", "waiting_list"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Class is already booked.")
    booking_status = "booked" if current.available_seats > 0 else "waiting_list"
    bookings = [item for item in _member_bookings(member) if str(item.get("class_uuid")) != str(class_id)]
    bookings.insert(
        0,
        {
            "class_uuid": str(class_id),
            "class_name": current.class_name,
            "status": booking_status,
            "booked_at": _now().isoformat(),
        },
    )
    _set_member_extra(member, "class_bookings", bookings[:100])
    member.updated_by = current_user.id
    db.commit()
    db.refresh(member)
    return _class_response(class_raw, gym, member)


@router.post("/classes/{class_id}/cancel", response_model=MemberClassRead)
def cancel_member_class(
    class_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberClassRead:
    member = _get_current_member(db, current_user)
    gym = _get_gym(db, current_user)
    class_raw = next((raw for raw in _gym_classes(gym) if _class_uuid(raw, gym.id) == class_id), None)
    if class_raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class was not found.")
    bookings = _member_bookings(member)
    found = False
    for booking in bookings:
        if str(booking.get("class_uuid")) == str(class_id) and booking.get("status") != "cancelled":
            booking["status"] = "cancelled"
            booking["cancelled_at"] = _now().isoformat()
            found = True
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class booking was not found.")
    _set_member_extra(member, "class_bookings", bookings[:100])
    member.updated_by = current_user.id
    db.commit()
    db.refresh(member)
    return _class_response(class_raw, gym, member)


@router.get("/notifications", response_model=list[MemberNotificationRead])
def get_member_notifications(
    unread_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> list[MemberNotificationRead]:
    statement = select(Notification).where(
        Notification.gym_id == current_user.gym_id,
        Notification.user_id == current_user.id,
        Notification.is_active.is_(True),
    )
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    statement = statement.order_by(Notification.created_at.desc()).limit(100)
    return [_notification_response(item) for item in db.scalars(statement).all()]


@router.patch("/notifications/{notification_id}/read", response_model=MemberNotificationRead)
def mark_member_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberNotificationRead:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.gym_id == current_user.gym_id,
            Notification.user_id == current_user.id,
            Notification.is_active.is_(True),
        )
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification was not found.")
    notification.read_at = notification.read_at or _now()
    notification.updated_by = current_user.id
    db.commit()
    db.refresh(notification)
    return _notification_response(notification)


@router.get("/goals", response_model=list[MemberGoalRead])
def get_member_goals(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> list[MemberGoalRead]:
    member = _get_current_member(db, current_user)
    goals = [item for item in _as_list(_as_dict(member.extra_data).get("fitness_goals")) if isinstance(item, dict)]
    return [_goal_response(item) for item in goals]


@router.post("/goals", response_model=MemberGoalRead, status_code=201)
def create_member_goal(
    payload: MemberGoalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberGoalRead:
    member = _get_current_member(db, current_user, lock=True)
    goals = [item for item in _as_list(_as_dict(member.extra_data).get("fitness_goals")) if isinstance(item, dict)]
    raw = {
        "goal_uuid": str(uuid4()),
        "status": "active",
        "created_at": _now().isoformat(),
        **payload.model_dump(),
    }
    goals.insert(0, raw)
    _set_member_extra(member, "fitness_goals", goals[:100])
    member.extra_data = snapshot_today(record_calorie_target(_as_dict(member.extra_data), _now()), _now())
    member.updated_by = current_user.id
    db.commit()
    db.refresh(member)
    return _goal_response(raw)


@router.patch("/goals/{goal_id}", response_model=MemberGoalRead)
def update_member_goal(
    goal_id: UUID,
    payload: MemberGoalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberGoalRead:
    member = _get_current_member(db, current_user, lock=True)
    goals = [item for item in _as_list(_as_dict(member.extra_data).get("fitness_goals")) if isinstance(item, dict)]
    updated: dict[str, Any] | None = None
    values = payload.model_dump(exclude_unset=True)
    for goal in goals:
        if str(goal.get("goal_uuid")) == str(goal_id):
            goal.update(values)
            if values.get("status") == "completed" and not goal.get("completed_at"):
                goal["completed_at"] = _now().isoformat()
            updated = goal
            break
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal was not found.")
    _set_member_extra(member, "fitness_goals", goals[:100])
    member.extra_data = snapshot_today(record_calorie_target(_as_dict(member.extra_data), _now()), _now())
    member.updated_by = current_user.id
    db.commit()
    db.refresh(member)
    return _goal_response(updated)


@router.get("/rewards", response_model=list[MemberRewardRead])
def get_member_rewards(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> list[MemberRewardRead]:
    member = _get_current_member(db, current_user)
    gym = _get_gym(db, current_user)
    member_rewards = [item for item in _as_list(_as_dict(member.extra_data).get("rewards")) if isinstance(item, dict)]
    gym_rewards = [item for item in _as_list(_as_dict(gym.settings).get("rewards")) if isinstance(item, dict)]
    rewards = member_rewards + gym_rewards
    if not rewards:
        rewards = [
            {"title": "30-day attendance challenge", "description": "Complete consistent check-ins.", "points": 0, "status": "available", "challenge_type": "attendance"},
            {"title": "Strength challenge", "description": "Log workout milestones.", "points": 0, "status": "available", "challenge_type": "strength"},
        ]
    return [_reward_response(item) for item in rewards]


@router.post("/support-tickets", response_model=SupportTicketRead, status_code=201)
@router.post("/support-ticket", response_model=SupportTicketRead, status_code=201, deprecated=True)
def create_member_support_ticket(
    payload: SupportTicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> SupportTicketRead:
    member = _get_current_member(db, current_user)
    gym = _get_gym(db, current_user)
    tickets = [item for item in _as_list(_as_dict(member.extra_data).get("support_tickets")) if isinstance(item, dict)]
    raw = {
        "ticket_uuid": str(uuid4()),
        "gym_uuid": str(gym.id),
        "gym_name": gym.name,
        "member_uuid": str(member.id),
        "member_name": member.member_name,
        "status": "open",
        "created_at": _now().isoformat(),
        **payload.model_dump(),
    }
    tickets.insert(0, raw)
    _set_member_extra(member, "support_tickets", tickets[:100])
    member.updated_by = current_user.id
    db.commit()
    db.refresh(member)
    return SupportTicketRead(
        ticket_uuid=UUID(raw["ticket_uuid"]),
        gym_uuid=gym.id,
        gym_name=gym.name,
        member_uuid=member.id,
        member_name=member.member_name,
        category=raw["category"],
        subject=raw["subject"],
        message=raw["message"],
        status=raw["status"],
        created_at=datetime.fromisoformat(raw["created_at"]),
    )


@router.get("/activity", response_model=MemberActivityHistory)
def get_member_activity(
    utc_offset_minutes: int = Query(default=0, ge=-720, le=840),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberActivityHistory:
    member = _get_current_member(db, current_user)
    extra = _as_dict(member.extra_data)
    today = _now().astimezone(timezone(timedelta(minutes=utc_offset_minutes))).date()
    days = set(_as_dict(extra.get("daily_activity")).keys())
    days.add(today.isoformat())
    ordered = sorted(days, reverse=True)
    return MemberActivityHistory(
        today=activity_day(extra, today, utc_offset_minutes, today),
        items=[activity_day(extra, date.fromisoformat(key), utc_offset_minutes, today) for key in ordered[offset:offset + limit]],
        total=len(ordered),
    )


@router.put("/activity", response_model=MemberActivityDay)
def sync_member_activity(
    payload: MemberActivitySync,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_member),
) -> MemberActivityDay:
    member = _get_current_member(db, current_user)
    # Refresh under a row lock so simultaneous devices do not overwrite a day.
    member = db.scalar(_member_base_statement(current_user).with_for_update().execution_options(populate_existing=True))
    if member is None:
        raise HTTPException(status_code=404, detail="Member was not found.")
    now = _now()
    today = now.astimezone(timezone(timedelta(minutes=payload.utc_offset_minutes))).date()
    if payload.activity_date > today:
        raise HTTPException(status_code=422, detail="Future activity cannot be recorded.")
    member.extra_data, result = merge_activity(_as_dict(member.extra_data), payload, now)
    member.updated_by = current_user.id
    db.commit()
    return result
