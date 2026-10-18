from typing import Any


RUPEE_CURRENCY_ALIASES = {"rs", "rs=", "\u20b9", "rupee", "rupees"}


def normalize_currency_code(value: Any) -> str:
    if value is None:
        raise ValueError("Currency is required.")

    if not isinstance(value, str):
        raise ValueError("Currency must be a valid 3-letter ISO currency code.")

    trimmed = value.strip()
    if not trimmed:
        raise ValueError("Currency is required.")

    compact = "".join(trimmed.split()).lower()
    if compact in RUPEE_CURRENCY_ALIASES:
        return "INR"

    if len(trimmed) == 3 and trimmed.isalpha():
        return trimmed.upper()

    raise ValueError("Currency must be a valid 3-letter ISO currency code.")
