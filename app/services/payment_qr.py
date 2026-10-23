"""Normalize owner-uploaded images and extract only UPI payment recipients."""
import base64
import binascii
from io import BytesIO
from urllib.parse import urlparse, parse_qs
from decimal import Decimal, InvalidOperation
import re
from PIL import Image, ImageOps, UnidentifiedImageError
import zxingcpp

MAX_IMAGE_BYTES = 500_000
MAX_BASE64_LENGTH = 700_000

def read_payment_qr(image_base64: str):
    if len(image_base64) > MAX_BASE64_LENGTH:
        raise ValueError("QR image is too large. Choose a smaller image.")
    try:
        raw = base64.b64decode(image_base64, validate=True)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("QR image is too large. Choose a smaller image.")
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"} or source.width * source.height > 16_000_000:
                raise ValueError("Use a PNG, JPEG or WebP QR image under 16 megapixels.")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1400, 1400))
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("The uploaded file is not a valid QR image.") from error
    codes = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode)
    recipients = []
    for code in codes:
        parsed = urlparse(code.text)
        if parsed.scheme.lower() != "upi" or parsed.netloc.lower() != "pay":
            continue
        params = parse_qs(parsed.query, keep_blank_values=True)
        if len(params.get("pa", [])) != 1 or any(len(params.get(key, [])) > 1 for key in ("am", "cu", "pn")):
            raise ValueError("The QR contains ambiguous payment details. Upload the original merchant QR.")
        upi = params.get("pa", [""])[0].strip()
        if not re.fullmatch(r"[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+", upi):
            continue
        currency = params.get("cu", ["INR"])[0]
        if currency.upper() != "INR":
            raise ValueError("Upload an INR UPI payment QR.")
        try:
            fixed_amount = Decimal(params.get("am", ["0"])[0])
            if not fixed_amount.is_finite() or fixed_amount != 0:
                raise ValueError("Upload your reusable PhonePe or BHIM merchant QR without a fixed amount.")
        except InvalidOperation as error:
            raise ValueError("The QR contains an invalid payment amount.") from error
        recipients.append((upi, params.get("pn", [""])[0][:120]))
    if not recipients:
        raise ValueError("No readable UPI payment QR found. Upload the original PhonePe or BHIM QR image.")
    if len({upi.lower() for upi, name in recipients}) != 1:
        raise ValueError("Upload an image with only one payment recipient.")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    if output.tell() > MAX_IMAGE_BYTES:
        output = BytesIO()
        image.save(output, format="JPEG", quality=90)
        mime = "jpeg"
    else:
        mime = "png"
    if output.tell() > MAX_IMAGE_BYTES:
        raise ValueError("QR image is too large. Choose a smaller image.")
    return {"qr_image_url": f"data:image/{mime};base64," + base64.b64encode(output.getvalue()).decode("ascii"),
        "upi_id": recipients[0][0], "payee_name": recipients[0][1]}

def validate_uploaded_qr(value: str):
    if not value.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
        raise ValueError("Use an uploaded QR image or HTTPS image URL.")
    return read_payment_qr(value.split(",", 1)[1])
