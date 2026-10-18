import pytest
from pydantic import ValidationError

from app.schemas.auth import GymUserRegistrationRequest, OwnerRegistrationRequest


def test_owner_registration_accepts_snake_case_fields():
    payload = OwnerRegistrationRequest.model_validate(
        {
            "gym_name": "PulseFit Downtown",
            "full_name": "Oliver Garcia",
            "email": "owner@pulsefit.dev",
            "password": "pulsefit123",
            "invitation_token": "a" * 32,
        }
    )

    assert payload.gym_name == "PulseFit Downtown"
    assert payload.full_name == "Oliver Garcia"


def test_owner_registration_accepts_camel_case_fields():
    payload = OwnerRegistrationRequest.model_validate(
        {
            "gymName": "PulseFit Downtown",
            "fullName": "Oliver Garcia",
            "email": "owner@pulsefit.dev",
            "password": "pulsefit123",
            "invitationToken": "a" * 32,
        }
    )

    assert payload.gym_name == "PulseFit Downtown"
    assert payload.full_name == "Oliver Garcia"


def test_gym_user_registration_accepts_gym_name():
    payload = GymUserRegistrationRequest.model_validate(
        {
            "gym_name": "PulseFit Downtown",
            "full_name": "Ava Stone",
            "email": "ava@pulsefit.dev",
            "password": "pulsefit123",
            "role": "member",
            "invitation_token": "a" * 32,
        }
    )

    assert payload.gym_name == "PulseFit Downtown"
    assert payload.full_name == "Ava Stone"


def test_gym_user_registration_accepts_camel_case_gym_name():
    payload = GymUserRegistrationRequest.model_validate(
        {
            "gymName": "PulseFit Downtown",
            "fullName": "Ava Stone",
            "email": "ava@pulsefit.dev",
            "password": "pulsefit123",
            "invitationToken": "a" * 32,
        }
    )

    assert payload.gym_name == "PulseFit Downtown"
    assert payload.full_name == "Ava Stone"


def test_owner_registration_rejects_passwords_over_bcrypt_byte_limit():
    with pytest.raises(ValidationError):
        OwnerRegistrationRequest.model_validate(
            {
                "gym_name": "PulseFit Downtown",
                "full_name": "Oliver Garcia",
                "email": "owner@pulsefit.dev",
                "password": "😀" * 19,
            }
        )


def test_registration_requires_an_invitation_token():
    with pytest.raises(ValidationError):
        GymUserRegistrationRequest.model_validate(
            {
                "full_name": "Ava Stone",
                "email": "ava@pulsefit.dev",
                "password": "pulsefit123",
            }
        )
