from enum import StrEnum


class RoleName(StrEnum):
    SUPER_ADMIN = "super_admin"
    GYM_OWNER = "gym_owner"
    SUB_ADMIN = "sub_admin"
    TRAINER = "trainer"
    RECEPTIONIST = "receptionist"
    MEMBER = "member"


class PermissionCode(StrEnum):
    MANAGE_GYMS = "manage_gyms"
    MANAGE_SUBSCRIPTIONS = "manage_subscriptions"
    MANAGE_PLATFORM_SETTINGS = "manage_platform_settings"
    VIEW_PLATFORM_ANALYTICS = "view_platform_analytics"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_TRAINERS = "manage_trainers"
    MANAGE_PAYMENTS = "manage_payments"
    MANAGE_ATTENDANCE = "manage_attendance"
    MANAGE_WORKOUTS = "manage_workouts"
    MANAGE_DIET_PLANS = "manage_diet_plans"
    MANAGE_REPORTS = "manage_reports"
    MANAGE_STAFF = "manage_staff"
    MANAGE_MEMBERSHIP_PLANS = "manage_membership_plans"
    CONFIGURE_GYM = "configure_gym"
    VIEW_OWN_PROFILE = "view_own_profile"


class GymStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class InvitationStatus(StrEnum):
    ACTIVE = "active"
    USED = "used"
    REVOKED = "revoked"
    EXPIRED = "expired"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class AttendanceSource(StrEnum):
    QR_CODE = "qr_code"
    BARCODE = "barcode"
    MANUAL = "manual"
    OFFLINE_SYNC = "offline_sync"
