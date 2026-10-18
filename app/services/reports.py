from collections import defaultdict
from datetime import UTC, datetime, time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.attendance import Attendance
from app.models.billing import Payment, Subscription
from app.models.enums import GymStatus, PaymentStatus, RoleName
from app.models.gym import Gym
from app.models.user import User
from app.models.member import Member
from app.models.trainer import Trainer
from app.schemas.reports import DashboardStats, PlatformGymPoint, PlatformReport, PlatformRevenuePoint


def get_dashboard_stats(db: Session, gym_id: UUID) -> DashboardStats:
    today = datetime.now(UTC).date()
    start_of_day = datetime.combine(today, time.min, tzinfo=UTC)
    start_of_month = datetime(today.year, today.month, 1, tzinfo=UTC)

    active_members = db.scalar(
        select(func.count(Member.id)).where(Member.gym_id == gym_id, Member.is_active.is_(True))
    ) or 0
    trainers = db.scalar(
        select(func.count(Trainer.id)).where(Trainer.gym_id == gym_id, Trainer.is_active.is_(True))
    ) or 0
    checkins_today = db.scalar(
        select(func.count(Attendance.id)).where(
            Attendance.gym_id == gym_id,
            Attendance.check_in_at >= start_of_day,
            Attendance.is_active.is_(True),
        )
    ) or 0
    revenue_cents_this_month = db.scalar(
        select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
            Payment.gym_id == gym_id,
            Payment.paid_at >= start_of_month,
            Payment.status == "paid",
            Payment.is_active.is_(True),
        )
    ) or 0

    return DashboardStats(
        active_members=active_members,
        trainers=trainers,
        checkins_today=checkins_today,
        revenue_cents_this_month=revenue_cents_this_month,
    )


def get_platform_report(db: Session) -> PlatformReport:
    """Build a platform-wide report for the Developer Admin role.

    Aggregation is intentionally done in the service layer so the endpoint
    remains portable across PostgreSQL and the SQLite test database.
    """
    now = datetime.now(UTC)
    start_of_month = datetime(now.year, now.month, 1, tzinfo=UTC)
    gyms = list(db.scalars(select(Gym).where(Gym.is_active.is_(True))).all())
    gym_ids = {gym.id for gym in gyms}
    users = list(db.scalars(select(User).where(User.is_active.is_(True))).all())
    payments = list(db.scalars(select(Payment).where(Payment.is_active.is_(True), Payment.status == PaymentStatus.PAID.value)).all())
    subscriptions = list(db.scalars(select(Subscription).where(Subscription.gym_id.in_(gym_ids))).all()) if gym_ids else []

    members = [user for user in users if user.role == RoleName.MEMBER.value and user.gym_id in gym_ids]
    owners = [user for user in users if user.role == RoleName.GYM_OWNER.value and user.gym_id in gym_ids]
    trainers = [user for user in users if user.role == RoleName.TRAINER.value and user.gym_id in gym_ids]
    staff = [user for user in users if user.role in {RoleName.SUB_ADMIN.value, RoleName.RECEPTIONIST.value} and user.gym_id in gym_ids]
    active_gym_ids = {gym.id for gym in gyms if gym.status == GymStatus.ACTIVE.value}
    suspended_gym_ids = {gym.id for gym in gyms if gym.status == GymStatus.SUSPENDED.value}
    free_trial_gyms = {
        subscription.gym_id for subscription in subscriptions
        if subscription.gym_id in active_gym_ids
        and subscription.status in {"trialing", "trial"}
        and subscription.current_period_ends_at is not None
        and subscription.current_period_ends_at >= now
    }

    revenue_by_gym: dict[UUID, int] = defaultdict(int)
    revenue_by_month: dict[str, int] = defaultdict(int)
    total_revenue = 0
    this_month_revenue = 0
    for payment in payments:
        if payment.gym_id not in gym_ids:
            continue
        amount = int(payment.amount_cents or 0)
        total_revenue += amount
        revenue_by_gym[payment.gym_id] += amount
        if payment.paid_at is not None:
            paid_at = payment.paid_at if payment.paid_at.tzinfo else payment.paid_at.replace(tzinfo=UTC)
            if paid_at >= start_of_month:
                this_month_revenue += amount
            month_key = paid_at.strftime("%Y-%m")
            revenue_by_month[month_key] += amount

    month_points: list[PlatformRevenuePoint] = []
    year, month = now.year, now.month
    for _ in range(6):
        key = f"{year:04d}-{month:02d}"
        month_points.append(PlatformRevenuePoint(period=key, revenue_cents=revenue_by_month.get(key, 0)))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    month_points.reverse()

    member_counts: dict[UUID, int] = defaultdict(int)
    for user in members:
        member_counts[user.gym_id] += 1
    gym_points = [
        PlatformGymPoint(
            gym_id=str(gym.id), gym_name=gym.name, status=gym.status,
            members=member_counts.get(gym.id, 0), revenue_cents=revenue_by_gym.get(gym.id, 0),
        )
        for gym in sorted(gyms, key=lambda item: (revenue_by_gym.get(item.id, 0), member_counts.get(item.id, 0)), reverse=True)
    ]

    return PlatformReport(
        total_gyms=len(gyms), active_gyms=len(active_gym_ids), suspended_gyms=len(suspended_gym_ids),
        free_trial_gyms=len(free_trial_gyms), total_members=len(members), active_members=len(members),
        total_gym_owners=len(owners), total_trainers=len(trainers), total_staff=len(staff),
        revenue_cents_total=total_revenue, revenue_cents_this_month=this_month_revenue,
        revenue_by_month=month_points, gyms=gym_points,
    )
