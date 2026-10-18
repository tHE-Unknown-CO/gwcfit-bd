"""normalize currency codes

Revision ID: 0002_normalize_currency_codes
Revises: 0001_initial_schema
Create Date: 2026-07-07
"""
from alembic import op
from sqlalchemy import text


revision = "0002_normalize_currency_codes"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


RUPEE_ALIAS_SQL = "lower(regexp_replace(currency, '\\s+', '', 'g')) IN ('rs', 'rs=', chr(8377), 'rupee', 'rupees')"


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in ("membership_plans", "payments"):
        bind.execute(text(f"UPDATE {table_name} SET currency = 'INR' WHERE {RUPEE_ALIAS_SQL}"))
        bind.execute(text(f"UPDATE {table_name} SET currency = upper(currency) WHERE currency ~ '^[A-Za-z]{{3}}$'"))


def downgrade() -> None:
    pass
