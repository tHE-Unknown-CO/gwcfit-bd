import pytest
from pydantic import ValidationError

from app.schemas.billing import PaymentCreate, PaymentUpdate
from app.schemas.plans import MembershipPlanCreate, MembershipPlanUpdate


def test_currency_schemas_normalize_rupee_aliases_to_inr():
    membership_plan = MembershipPlanCreate.model_validate(
        {
            "name": "Gold Plan",
            "duration_days": 30,
            "price_cents": 100000,
            "currency": "Rs=",
        }
    )
    payment = PaymentCreate.model_validate(
        {
            "member_id": "00000000-0000-0000-0000-000000000001",
            "amount_cents": 100000,
            "currency": "\u20b9",
            "method": "cash",
        }
    )
    membership_plan_update = MembershipPlanUpdate.model_validate({"currency": "rupees"})
    payment_update = PaymentUpdate.model_validate({"currency": "inr"})

    assert membership_plan.currency == "INR"
    assert payment.currency == "INR"
    assert membership_plan_update.currency == "INR"
    assert payment_update.currency == "INR"


def test_currency_schemas_reject_invalid_currency_codes():
    with pytest.raises(ValidationError):
        MembershipPlanCreate.model_validate(
            {
                "name": "Gold Plan",
                "duration_days": 30,
                "price_cents": 100000,
                "currency": "R$=",
            }
        )

    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(
            {
                "member_id": "00000000-0000-0000-0000-000000000001",
                "amount_cents": 100000,
                "currency": "R$=",
                "method": "cash",
            }
        )
