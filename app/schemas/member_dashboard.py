from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


JsonDict = dict[str, Any]


class MemberProfileUpdate(BaseModel):
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    emergency_contact: JsonDict | None = None
    height: float | None = Field(default=None, ge=0)
    weight: float | None = Field(default=None, ge=0)
    fitness_goal: str | None = Field(default=None, max_length=240)
    profile_photo: str | None = Field(default=None, max_length=800)


class MemberProfileRead(BaseModel):
    member_uuid: UUID
    member_name: str
    member_code: str
    email: str | None
    phone: str | None
    gender: str | None = None
    date_of_birth: date | str | None = None
    address: str | None = None
    emergency_contact: JsonDict
    height: float | None = None
    weight: float | None = None
    bmi: float | None = None
    fitness_goal: str | None = None
    medical_conditions: str | list[str] | None = None
    profile_photo: str | None = None
    trainer_uuid: UUID | None = None
    trainer_name: str | None = None
    gym_uuid: UUID
    gym_name: str | None = None
    membership_plan_uuid: UUID | None = None
    membership_plan_name: str | None = None
    membership_status: str


class MemberMembershipHistoryItem(BaseModel):
    membership_uuid: UUID
    membership_plan_uuid: UUID | None = None
    membership_plan_name: str | None = None
    start_date: date | None = None
    expiry_date: date | None = None
    status: str
    amount_cents: int | None = None
    currency: str | None = None
    paid_at: datetime | None = None


class MemberMembershipRead(BaseModel):
    membership_uuid: UUID
    member_uuid: UUID
    member_name: str
    gym_uuid: UUID
    gym_name: str | None = None
    membership_plan_uuid: UUID | None = None
    membership_plan_name: str | None = None
    plan_price_cents: int
    plan_currency: str
    plan_duration_days: int | None = None
    start_date: date | None = None
    expiry_date: date | None = None
    status: str
    days_remaining: int
    renewal_reminder: str
    benefits: list[str]
    history: list[MemberMembershipHistoryItem]


class MemberPaymentRead(BaseModel):
    payment_uuid: UUID
    gym_uuid: UUID
    gym_name: str | None = None
    member_uuid: UUID
    member_name: str
    membership_plan_uuid: UUID | None = None
    membership_plan_name: str | None = None
    amount_cents: int
    paid_amount_cents: int
    due_amount_cents: int
    currency: str
    payment_method: str
    payment_date: datetime | None = None
    invoice_number: str | None = None
    receipt_url: str | None = None
    status: str


class MemberAttendanceRecord(BaseModel):
    attendance_uuid: UUID
    gym_uuid: UUID
    gym_name: str | None = None
    member_uuid: UUID
    member_name: str
    trainer_uuid: UUID | None = None
    trainer_name: str | None = None
    check_in_at: datetime
    check_out_at: datetime | None = None
    source: str
    status: str
    notes: str | None = None


class MemberAttendanceSummary(BaseModel):
    today_status: str
    today_visit_count: int
    daily_visit_limit: int
    can_check_in: bool
    can_check_out: bool
    monthly_attendance_count: int
    attendance_percentage: float
    missed_days: int
    history: list[MemberAttendanceRecord]


class MemberAttendanceQrToken(BaseModel):
    token: str
    action: str
    expires_in_seconds: int


class MemberWorkoutRead(BaseModel):
    workout_plan_uuid: UUID
    workout_plan_name: str
    gym_uuid: UUID
    gym_name: str | None = None
    member_uuid: UUID
    member_name: str
    trainer_uuid: UUID | None = None
    trainer_name: str | None = None
    goal: str
    level: str
    starts_at: date | None = None
    ends_at: date | None = None
    today_workout: JsonDict | None = None
    weekly_plan: list[JsonDict]
    sessions: list[JsonDict]
    completion_status: str
    completed_workouts: int
    missed_workouts: int
    weekly_consistency: float
    personal_records: list[JsonDict]
    trainer_notes: str | None = None


class MemberWorkoutComplete(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)
    exercises: list[JsonDict] = Field(default_factory=list)


class MemberMealPlanRead(BaseModel):
    meal_plan_uuid: UUID
    meal_plan_name: str
    gym_uuid: UUID
    gym_name: str | None = None
    member_uuid: UUID
    member_name: str
    trainer_uuid: UUID | None = None
    trainer_name: str | None = None
    calories_per_day: int
    starts_at: date | None = None
    ends_at: date | None = None
    today_meal_plan: JsonDict | None = None
    meals: list[JsonDict]
    water_target_ml: int | None = None
    trainer_notes: str | None = None
    completion_status: str


class MemberMealComplete(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)
    water_ml: int | None = Field(default=None, ge=0)
    extra_meal: JsonDict | None = None


class MemberProgressLogCreate(BaseModel):
    weight: float | None = Field(default=None, ge=0)
    bmi: float | None = Field(default=None, ge=0)
    body_fat_percentage: float | None = Field(default=None, ge=0)
    muscle_mass: float | None = Field(default=None, ge=0)
    calories_burned: int | None = Field(default=None, ge=0)
    measurements: JsonDict = Field(default_factory=dict)
    photo_url: str | None = Field(default=None, max_length=800)
    goal_progress_percentage: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=1000)


class MemberProgressLogRead(MemberProgressLogCreate):
    progress_uuid: UUID
    logged_at: datetime


class MemberTrainerRead(BaseModel):
    trainer_uuid: UUID
    trainer_name: str
    trainer_photo: str | None = None
    email: str | None = None
    phone: str | None = None
    specialization: list[str]
    schedule: list[JsonDict]
    assigned_workout_plans: list[str]
    assigned_meal_plans: list[str]
    trainer_notes: str | None = None


class MemberClassRead(BaseModel):
    class_uuid: UUID
    class_name: str
    gym_uuid: UUID
    gym_name: str | None = None
    trainer_uuid: UUID | None = None
    trainer_name: str | None = None
    date: date | str | None = None
    time: str | None = None
    duration_minutes: int | None = None
    capacity: int
    available_seats: int
    class_type: str
    booking_status: str


class MemberNotificationRead(BaseModel):
    notification_uuid: UUID
    title: str
    body: str
    notification_type: str
    read_at: datetime | None = None
    created_at: datetime
    status: str
    payload: JsonDict


class MemberGoalCreate(BaseModel):
    goal_name: str = Field(min_length=2, max_length=180)
    target_weight: float | None = Field(default=None, ge=0)
    target_date: date | None = None
    progress_percentage: float = Field(default=0, ge=0, le=100)
    workout_goal: str | None = Field(default=None, max_length=180)
    water_intake_goal: int | None = Field(default=None, ge=0)
    attendance_goal: int | None = Field(default=None, ge=0)
    calories_goal: int | None = Field(default=None, ge=0)


class MemberGoalUpdate(BaseModel):
    goal_name: str | None = Field(default=None, min_length=2, max_length=180)
    target_weight: float | None = Field(default=None, ge=0)
    target_date: date | None = None
    progress_percentage: float | None = Field(default=None, ge=0, le=100)
    workout_goal: str | None = Field(default=None, max_length=180)
    water_intake_goal: int | None = Field(default=None, ge=0)
    attendance_goal: int | None = Field(default=None, ge=0)
    calories_goal: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, max_length=40)


class MemberGoalRead(MemberGoalCreate):
    goal_uuid: UUID
    status: str
    created_at: datetime
    completed_at: datetime | None = None


class MemberRewardRead(BaseModel):
    reward_uuid: UUID
    title: str
    description: str | None = None
    points: int
    badge: str | None = None
    status: str
    challenge_type: str | None = None
    privacy_safe_rank: int | None = None


class SupportTicketCreate(BaseModel):
    category: str = Field(default="support", max_length=80)
    subject: str = Field(min_length=2, max_length=180)
    message: str = Field(min_length=2, max_length=2000)


class SupportTicketRead(BaseModel):
    ticket_uuid: UUID
    gym_uuid: UUID
    gym_name: str | None = None
    member_uuid: UUID
    member_name: str
    category: str
    subject: str
    message: str
    status: str
    created_at: datetime


class MemberDashboardSummary(BaseModel):
    member_uuid: UUID
    member_name: str
    gym_uuid: UUID
    gym_name: str | None = None
    profile_photo: str | None = None
    membership_status: str
    membership_expiry_date: date | None = None
    days_remaining: int
    assigned_trainer_name: str | None = None
    today_attendance_status: str
    today_workout_plan: MemberWorkoutRead | None = None
    today_meal_plan: MemberMealPlanRead | None = None
    pending_payment_amount_cents: int
    pending_payment_currency: str
    upcoming_class: MemberClassRead | None = None
    fitness_goal_progress: float
    quick_actions: list[str]

class MemberActivitySync(BaseModel):
    activity_date: date
    utc_offset_minutes: int = Field(ge=-720, le=840)
    device_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    hourly_steps: list[int] | None = Field(default=None, min_length=24, max_length=24)
    source: str = Field(default="android_foreground", pattern=r"^(ios_pedometer|android_foreground|dashboard)$")

    @field_validator("hourly_steps")
    @classmethod
    def validate_steps(cls, values):
        if values is not None and any(value < 0 or value > 100000 for value in values):
            raise ValueError("Hourly steps must be between 0 and 100000")
        return values


class MemberActivityDay(BaseModel):
    activity_date: date
    steps: int
    distance_km: float
    hourly_steps: list[int]
    calories_completed: int
    calories_logged: int = 0
    calories_estimated: int = 0
    calories_source: str = "none"
    calorie_estimate_weight_kg: float = 70
    calorie_estimate_uses_default_weight: bool = True
    calories_target: int
    calories_remaining: int
    completion_percentage: float
    source: str | None = None
    updated_at: datetime | None = None


class MemberActivityHistory(BaseModel):
    today: MemberActivityDay
    items: list[MemberActivityDay]
    total: int
