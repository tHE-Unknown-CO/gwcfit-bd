from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.enums import RoleName
from app.schemas.auth import (
    AuthenticatedUser,
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GymUserRegistrationRequest,
    LoginRequest,
    OwnerRegistrationRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    TokenPair,
    VerifyEmailRequest,
)
from app.schemas.common import MessageResponse
from app.schemas.gym import GymOption
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me", response_model=AuthenticatedUser)
def get_authenticated_user(current_user: User = Depends(get_current_user)) -> AuthenticatedUser:
    return auth_service.get_authenticated_user(current_user)


@router.get("/gyms", response_model=list[GymOption], deprecated=True)
def list_gym_options(db: Session = Depends(get_db)) -> list[GymOption]:
    return [GymOption(id=gym.id, name=gym.name) for gym in auth_service.list_gym_options(db)]


@router.post("/register/owner", response_model=AuthResponse, status_code=201)
def register_owner(payload: OwnerRegistrationRequest, db: Session = Depends(get_db)) -> AuthResponse:
    return auth_service.register_owner(db, payload)


@router.post("/register", response_model=AuthResponse, status_code=201)
def register_existing_gym_user(
    payload: GymUserRegistrationRequest,
    db: Session = Depends(get_db),
) -> AuthResponse:
    return auth_service.register_existing_gym_user(db, payload)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> AuthResponse:
    forwarded_for = request.headers.get("x-forwarded-for")
    ip_address = forwarded_for.split(",", 1)[0].strip() if forwarded_for else (
        request.client.host if request.client else None
    )
    return auth_service.login(
        db, payload, ip_address=ip_address, user_agent=request.headers.get("user-agent")
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> TokenPair:
    return auth_service.refresh(db, payload)


@router.post("/logout", response_model=MessageResponse)
def logout(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MessageResponse:
    auth_service.logout(db, current_user)
    return MessageResponse(message="Logged out.")


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> ForgotPasswordResponse:
    return auth_service.forgot_password(db, payload.email)


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> MessageResponse:
    auth_service.reset_password(db, payload.token, payload.new_password)
    return MessageResponse(message="Password was reset.")


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if current_user.role == RoleName.SUPER_ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin accounts are protected and can only be changed in the codebase.")
    auth_service.change_password(db, current_user, payload)
    return MessageResponse(message="Password was changed.")


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)) -> MessageResponse:
    auth_service.verify_email(db, payload.token)
    return MessageResponse(message="Email was verified.")
