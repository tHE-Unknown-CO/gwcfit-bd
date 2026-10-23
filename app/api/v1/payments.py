from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1._crud import get_or_404
from app.database.session import get_db
from app.dependencies.permissions import require_permission
from app.dependencies.tenant import get_current_gym_id, get_optional_gym_id
from app.models.billing import Payment
from app.models.enums import PermissionCode
from app.models.user import User
from app.repositories.base import TenantRepository
from app.schemas.billing import PaymentCreate, PaymentRead, PaymentUpdate
from app.schemas.common import MessageResponse

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=list[PaymentRead])
def list_payments(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    gym_id: UUID | None = Depends(get_optional_gym_id),
    _: User = Depends(require_permission(PermissionCode.MANAGE_PAYMENTS)),
):
    if gym_id is None:
        statement = (
            select(Payment)
            .where(Payment.is_active.is_(True))
            .order_by(Payment.created_at.desc())
            .offset(skip)
            .limit(min(limit, 200))
        )
        return list(db.scalars(statement).all())
    return TenantRepository(Payment, db, gym_id).list(skip=skip, limit=limit)


@router.post("", response_model=PaymentRead, status_code=201)
def create_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_PAYMENTS)),
):
    return TenantRepository(Payment, db, gym_id).create(payload.model_dump(), actor_id=current_user.id)


@router.get("/{payment_id}", response_model=PaymentRead)
def get_payment(
    payment_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    _: User = Depends(require_permission(PermissionCode.MANAGE_PAYMENTS)),
):
    return get_or_404(TenantRepository(Payment, db, gym_id), payment_id, "Payment")


@router.patch("/{payment_id}", response_model=PaymentRead)
def update_payment(
    payment_id: UUID,
    payload: PaymentUpdate,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_PAYMENTS)),
):
    repo = TenantRepository(Payment, db, gym_id)
    payment = get_or_404(repo, payment_id, "Payment")
    if (getattr(payment, "extra_data", None) or {}).get("source") == "member_checkout":
        raise HTTPException(409, "Use the membership checkout verification flow for this payment.")
    return repo.update(payment, payload.model_dump(exclude_unset=True), actor_id=current_user.id)


@router.delete("/{payment_id}", response_model=MessageResponse)
def delete_payment(
    payment_id: UUID,
    db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id),
    current_user: User = Depends(require_permission(PermissionCode.MANAGE_PAYMENTS)),
) -> MessageResponse:
    repo = TenantRepository(Payment, db, gym_id)
    payment = get_or_404(repo, payment_id, "Payment")
    if (getattr(payment, "extra_data", None) or {}).get("source") == "member_checkout":
        raise HTTPException(409, "Checkout payments must be retained. Use the payment review flow instead.")
    repo.deactivate(payment, actor_id=current_user.id)
    return MessageResponse(message="Payment was deactivated.")
