import base64
from io import BytesIO
from uuid import uuid4
import pytest
from PIL import Image
from pydantic import ValidationError
import zxingcpp
from app.services.payment_qr import read_payment_qr, validate_uploaded_qr
from app.api.v1.membership_checkout import QrSettings
from app.models.enums import RoleName
from app.tests.test_rbac_endpoints import client_as, FakeSession, make_user


def qr_image(text="upi://pay?pa=gym@bank&pn=Gym%20Fitness&cu=INR"):
    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode)
    pixels = memoryview(barcode.to_image(scale=6))
    image = Image.frombytes("L", (pixels.shape[1], pixels.shape[0]), bytes(pixels))
    output = BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def test_uploaded_payment_qr_round_trips_and_extracts_same_recipient():
    result = read_payment_qr(qr_image())
    assert result["upi_id"] == "gym@bank"
    assert result["payee_name"] == "Gym Fitness"
    assert result["qr_image_url"].startswith("data:image/png;base64,")
    assert validate_uploaded_qr(result["qr_image_url"])["upi_id"] == "gym@bank"
    settings = QrSettings(payee_name="Gym Fitness", qr_image_url=result["qr_image_url"], enabled=True)
    assert settings.upi_id == "gym@bank"


@pytest.mark.parametrize("text", [
    "https://example.com/not-a-payment", "upi://pay?pa=not-an-id", "upi://pay?pa=gym@bank&am=999",
    "upi://pay?pa=gym@bank&cu=USD", "upi://pay?pa=gym@bank&pa=other@bank", "upi://pay?pa=gym@bank&am=NaN",
])
def test_invalid_or_fixed_amount_payment_qr_is_rejected(text):
    with pytest.raises(ValueError):
        read_payment_qr(qr_image(text))


def test_settings_cannot_change_payee_away_from_uploaded_qr():
    result = read_payment_qr(qr_image())
    with pytest.raises(ValidationError):
        QrSettings(payee_name="Gym", upi_id="other@bank", qr_image_url=result["qr_image_url"])


@pytest.mark.parametrize("content", ["not-base64!", base64.b64encode(b"not an image").decode(), "a" * 700001], ids=["invalid-base64", "not-image", "oversized"])
def test_bad_or_oversized_uploads_are_rejected(content):
    with pytest.raises(ValueError):
        read_payment_qr(content)


def test_owner_can_upload_but_member_cannot():
    payload = {"image_base64": qr_image()}
    for role, expected in [(RoleName.GYM_OWNER, 200), (RoleName.MEMBER, 403)]:
        with client_as(make_user(role, gym_id=uuid4()), FakeSession()) as client:
            response = client.post("/api/v1/membership-checkout/settings/qr-image", json=payload)
        assert response.status_code == expected
        if expected == 200:
            assert response.json()["upi_id"] == "gym@bank"
