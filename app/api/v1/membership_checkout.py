"""Tenant-scoped gym QR checkout with owner verification."""
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.v1.member import _get_current_member
from app.database.session import get_db
from app.dependencies.permissions import require_member, require_permission
from app.dependencies.tenant import get_current_gym_id
from app.models.billing import Payment
from app.models.enums import PermissionCode
from app.models.gym import Gym
from app.models.member import Member
from app.models.plans import MembershipPlan
from app.models.user import User
from app.services.payment_qr import read_payment_qr, validate_uploaded_qr

router = APIRouter(prefix="/membership-checkout", tags=["membership checkout"])

class QrSettings(BaseModel):
    payee_name: str = Field(default="", max_length=120)
    upi_id: str = Field(default="", max_length=180)
    qr_image_url: str = Field(default="", max_length=700_050)
    enabled: bool = False

    @field_validator("payee_name", "upi_id", "qr_image_url", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("upi_id")
    @classmethod
    def upi(cls, value):
        if value and not re.fullmatch(r"[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+", value):
            raise ValueError("Enter a valid UPI ID")
        return value

    @field_validator("qr_image_url")
    @classmethod
    def image(cls, value):
        if value.startswith("data:"):
            validate_uploaded_qr(value)
            return value
        if value and not value.startswith("https://"):
            raise ValueError("QR image must use an HTTPS URL")
        return value

    @model_validator(mode="after")
    def matching_recipient(self):
        if self.qr_image_url.startswith("data:"):
            details = validate_uploaded_qr(self.qr_image_url)
            if self.upi_id and self.upi_id.lower() != details["upi_id"].lower():
                raise ValueError("The UPI ID must match the uploaded QR recipient.")
            self.upi_id = details["upi_id"]
        return self

class QrUpload(BaseModel):
    image_base64: str = Field(min_length=1, max_length=700_000)

class CheckoutRequest(BaseModel):
    plan_uuid: UUID
    method: Literal["manual_qr"]
    quoted_amount_cents: int = Field(gt=0)
    quoted_currency: str = Field(min_length=3, max_length=3)
    transaction_reference: str = Field(default="", max_length=180)

class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)
    verified_reference: str = Field(default="", max_length=180)
    verified_amount_cents: int | None = Field(default=None, gt=0)

def gym_or_404(db, gym_id, lock=False):
    statement = select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True))
    gym = db.scalar(statement.with_for_update() if lock else statement)
    if gym is None:
        raise HTTPException(404, "Gym not found")
    return gym

def config_response(gym):
    config = QrSettings.model_validate((gym.settings or {}).get("membership_payment_qr", {}))
    return config.model_dump()

def payment_response(payment):
    data = payment.extra_data or {}
    return {"id": str(payment.id), "plan_uuid": str(payment.membership_plan_id),
        "plan_name": data.get("plan_name", "Membership"), "member_name": payment.member_name,
        "amount_cents": payment.amount_cents, "currency": payment.currency,
        "status": payment.status, "method": payment.method,
        "transaction_reference": payment.provider_reference,
        "review_note": data.get("review_note"),
        "start_date": data.get("start_date"), "expiry_date": data.get("expiry_date")}

def activate(db, payment, actor_id=None):
    if payment.status == "paid":
        return
    if payment.status != "pending":
        raise HTTPException(409, "This payment has already been reviewed.")
    member = db.scalar(select(Member).where(Member.id == payment.member_id,
        Member.gym_id == payment.gym_id, Member.is_active.is_(True)).with_for_update().execution_options(populate_existing=True))
    if member is None:
        raise HTTPException(404, "Member not found")
    days = int((payment.extra_data or {}).get("duration_days", 0))
    if days <= 0:
        raise HTTPException(409, "Payment has no valid membership duration")
    try:
        zone = ZoneInfo((payment.extra_data or {}).get("gym_timezone", "UTC"))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        zone = UTC
    today = datetime.now(zone).date()
    renewing = member.membership_plan_id == payment.membership_plan_id and member.membership_ends_at and member.membership_ends_at >= today
    start = member.membership_ends_at + timedelta(days=1) if renewing else today
    end = start + timedelta(days=days - 1)
    if not renewing:
        member.membership_starts_at = start
    member.membership_ends_at = end
    member.membership_plan_id = payment.membership_plan_id
    member.status = "active"
    member.updated_by = actor_id
    payment.status = "paid"
    payment.paid_at = datetime.now(UTC)
    payment.updated_by = actor_id
    payment.extra_data = {**payment.extra_data, "start_date": start.isoformat(), "expiry_date": end.isoformat()}

@router.get("/settings")
def owner_settings(db: Session = Depends(get_db), gym_id: UUID = Depends(get_current_gym_id),
    user: User = Depends(require_permission(PermissionCode.MANAGE_PAYMENTS))):
    return config_response(gym_or_404(db, gym_id))

@router.post("/settings/qr-image")
def upload_qr(payload: QrUpload, gym_id: UUID = Depends(get_current_gym_id),
    user: User = Depends(require_permission(PermissionCode.CONFIGURE_GYM))):
    try:
        return read_payment_qr(payload.image_base64)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

@router.put("/settings")
def save_settings(payload: QrSettings, db: Session = Depends(get_db), gym_id: UUID = Depends(get_current_gym_id),
    user: User = Depends(require_permission(PermissionCode.CONFIGURE_GYM))):
    if payload.enabled and (not payload.payee_name or not (payload.upi_id or payload.qr_image_url)):
        raise HTTPException(422, "Add a payee name and a UPI ID or QR image before enabling payments.")
    gym = gym_or_404(db, gym_id, True)
    gym.settings = {**(gym.settings or {}), "membership_payment_qr": payload.model_dump()}
    gym.updated_by = user.id
    db.commit()
    return config_response(gym)

@router.get("/member")
def member_checkout(db: Session = Depends(get_db), user: User = Depends(require_member)):
    member = _get_current_member(db, user)
    payments = db.scalars(select(Payment).where(Payment.gym_id == member.gym_id,
        Payment.member_id == member.id, Payment.is_active.is_(True),
        Payment.method == "manual_qr").order_by(Payment.created_at.desc()).limit(50)).all()
    return {"settings": config_response(gym_or_404(db, member.gym_id)), "payments": [payment_response(p) for p in payments]}

@router.post("/member", status_code=201)
def submit_checkout(payload: CheckoutRequest, db: Session = Depends(get_db), user: User = Depends(require_member)):
    member = _get_current_member(db, user)
    gym = gym_or_404(db, member.gym_id, True)
    plan = db.scalar(select(MembershipPlan).where(MembershipPlan.id == payload.plan_uuid,
        MembershipPlan.gym_id == member.gym_id, MembershipPlan.is_active.is_(True)))
    if plan is None:
        raise HTTPException(404, "Plan not available at your gym")
    if plan.price_cents <= 0 or plan.duration_days <= 0:
        raise HTTPException(409, "Contact your gym to activate this plan.")
    if payload.quoted_amount_cents != plan.price_cents or payload.quoted_currency != plan.currency:
        raise HTTPException(409, "The plan price has changed. Refresh the plan before paying or contact the gym if you already paid.")
    if plan.currency != "INR":
        raise HTTPException(409, "UPI QR payments require a plan priced in INR. Contact your gym for other payment options.")
    if not config_response(gym)["enabled"]:
        raise HTTPException(409, "QR payments are not enabled by your gym.")
    reference = payload.transaction_reference.strip().upper()
    if not re.fullmatch(r"[A-Z0-9-]{6,180}", reference):
        raise HTTPException(422, "Enter the transaction reference from your payment app (at least 6 letters or digits).")
    existing = db.scalar(select(Payment).where(Payment.gym_id == member.gym_id, Payment.provider_reference == reference))
    if existing:
        if existing.member_id == member.id and existing.membership_plan_id == plan.id and existing.status != "failed":
            return payment_response(existing)
        raise HTTPException(409, "That transaction reference has already been submitted.")
    existing = db.scalar(select(Payment).where(Payment.gym_id == member.gym_id, Payment.member_id == member.id,
        Payment.membership_plan_id == plan.id, Payment.method == payload.method,
        Payment.status == "pending", Payment.is_active.is_(True)))
    if existing:
        if payload.method == "manual_qr" and existing.provider_reference != reference:
            raise HTTPException(409, "A payment for this plan is already awaiting review. Contact your gym before paying again.")
        return payment_response(existing)
    payment = Payment(id=uuid4(), gym_id=member.gym_id, member_id=member.id, membership_plan_id=plan.id,
        amount_cents=plan.price_cents, currency=plan.currency, method=payload.method, status="pending",
        provider_reference=reference, created_by=user.id, updated_by=user.id,
        extra_data={"source": "member_checkout", "plan_name": plan.name, "duration_days": plan.duration_days,
            "gym_timezone": getattr(gym, "timezone", None) or "UTC"})
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment_response(payment)

@router.post("/member/{payment_id}/check")
def check_payment(payment_id: UUID, db: Session = Depends(get_db), user: User = Depends(require_member)):
    member = _get_current_member(db, user)
    payment = db.scalar(select(Payment).where(Payment.id == payment_id, Payment.gym_id == member.gym_id,
        Payment.member_id == member.id, Payment.is_active.is_(True)).with_for_update())
    if payment is None:
        raise HTTPException(404, "Payment not found")
    db.commit()
    return payment_response(payment)

@router.get("/reviews")
def reviews(db: Session = Depends(get_db), gym_id: UUID = Depends(get_current_gym_id),
    user: User = Depends(require_permission(PermissionCode.MANAGE_PAYMENTS))):
    payments = db.scalars(select(Payment).where(Payment.gym_id == gym_id, Payment.is_active.is_(True),
        Payment.method == "manual_qr", Payment.status == "pending").order_by(Payment.created_at)).all()
    return [payment_response(p) for p in payments]

@router.post("/reviews/{payment_id}")
def review(payment_id: UUID, payload: ReviewRequest, db: Session = Depends(get_db),
    gym_id: UUID = Depends(get_current_gym_id), user: User = Depends(require_permission(PermissionCode.MANAGE_PAYMENTS))):
    payment = db.scalar(select(Payment).where(Payment.id == payment_id, Payment.gym_id == gym_id,
        Payment.is_active.is_(True), Payment.method == "manual_qr").with_for_update())
    if payment is None:
        raise HTTPException(404, "Payment not found")
    if payment.status != "pending":
        raise HTTPException(409, "This payment has already been reviewed.")
    if payload.decision == "approve":
        if (payload.verified_reference.strip().upper() != (payment.provider_reference or "").strip().upper()
            or not payload.verified_reference.strip()
            or payload.verified_amount_cents != payment.amount_cents):
            raise HTTPException(422, "Enter the matching bank transaction reference and received amount before approving.")
        activate(db, payment, user.id)
    else:
        payment.status = "failed"
    payment.updated_by = user.id
    payment.extra_data = {**payment.extra_data, "review_note": payload.note.strip(), "reviewed_by": str(user.id), "reviewed_at": datetime.now(UTC).isoformat(), "verified_reference": payload.verified_reference.strip().upper(), "verified_amount_cents": payload.verified_amount_cents}
    db.commit()
    return payment_response(payment)

