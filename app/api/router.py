from fastapi import APIRouter

from app.api.v1 import (
    attendance,
    auth,
    diet_plans,
    developer_portal,
    gyms,
    invitations,
    member,
    members,
    membership_plans,
    notifications,
    payments,
    platform_plans,
    reports,
    staff,
    super_admin,
    trainers,
    users,
    workout_plans,
)

api_router = APIRouter()


@api_router.get("/", tags=["system"])
def api_root() -> dict[str, str]:
    return {
        "status": "ok",
        "version": "v1",
        "docs": "/docs",
        "openapi": "/api/v1/openapi.json",
    }


api_router.include_router(auth.router)
api_router.include_router(invitations.router)
api_router.include_router(platform_plans.router)
api_router.include_router(developer_portal.router)
api_router.include_router(super_admin.router)
api_router.include_router(gyms.router)
api_router.include_router(member.router)
api_router.include_router(members.router)
api_router.include_router(staff.router)
api_router.include_router(trainers.router)
api_router.include_router(users.router)
api_router.include_router(attendance.router)
api_router.include_router(payments.router)
api_router.include_router(workout_plans.router)
api_router.include_router(diet_plans.router)
api_router.include_router(membership_plans.router)
api_router.include_router(notifications.router)
api_router.include_router(reports.router)
