from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.permissions import require_super_admin
from app.models.user import User
from app.schemas.super_admin import GymAdminCreateRequest, GymAdminCreateResponse
from app.services import super_admin as super_admin_service

router = APIRouter(prefix="/super-admin", tags=["super-admin"])


@router.post("/gym-admin", response_model=GymAdminCreateResponse, status_code=201)
def create_gym_admin(
    payload: GymAdminCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> GymAdminCreateResponse:
    return super_admin_service.create_gym_admin(db, payload, actor=current_user)
