from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.api.v1.gyms import GymActivation


def test_activation_requires_plan_and_payment_choice():
    with pytest.raises(ValidationError):
        GymActivation()
    with pytest.raises(ValidationError):
        GymActivation(platform_plan_id=uuid4(), activation_type="override")
    for choice in ("free", "paid"):
        assert GymActivation(platform_plan_id=uuid4(), activation_type=choice).activation_type == choice
