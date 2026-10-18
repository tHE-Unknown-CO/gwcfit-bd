from pydantic import BaseModel


class DashboardStats(BaseModel):
    active_members: int
    trainers: int
    checkins_today: int
    revenue_cents_this_month: int


class RevenuePoint(BaseModel):
    period: str
    revenue_cents: int


class AttendancePoint(BaseModel):
    day: str
    checkins: int


class PlatformRevenuePoint(BaseModel):
    period: str
    revenue_cents: int


class PlatformGymPoint(BaseModel):
    gym_id: str
    gym_name: str
    status: str
    members: int
    revenue_cents: int


class PlatformReport(BaseModel):
    total_gyms: int
    active_gyms: int
    suspended_gyms: int
    free_trial_gyms: int
    total_members: int
    active_members: int
    total_gym_owners: int
    total_trainers: int
    total_staff: int
    revenue_cents_total: int
    revenue_cents_this_month: int
    revenue_by_month: list[PlatformRevenuePoint]
    gyms: list[PlatformGymPoint]
