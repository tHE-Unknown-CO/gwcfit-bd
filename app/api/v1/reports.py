from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.permissions import require_permission
from app.dependencies.tenant import get_current_gym_id
from app.models.enums import PermissionCode
from app.models.user import User
from app.schemas.reports import DashboardStats, PlatformReport
from app.schemas.gym_feedback import GymFeedbackSummary
from app.services.reports import get_dashboard_stats, get_gym_feedback_summary, get_platform_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/dashboard", response_model=DashboardStats)
def dashboard_stats(
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    _: User = Depends(require_permission(PermissionCode.MANAGE_REPORTS)),
) -> DashboardStats:
    return get_dashboard_stats(db, gym_id)


@router.get("/gym-feedback", response_model=GymFeedbackSummary)
def gym_feedback(
    db: Session = Depends(get_db), gym_id: UUID = Depends(get_current_gym_id),
    _: User = Depends(require_permission(PermissionCode.MANAGE_REPORTS)),
) -> GymFeedbackSummary:
    return get_gym_feedback_summary(db, gym_id)


@router.get("/platform", response_model=PlatformReport)
def platform_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PermissionCode.VIEW_PLATFORM_ANALYTICS)),
) -> PlatformReport:
    return get_platform_report(db)
