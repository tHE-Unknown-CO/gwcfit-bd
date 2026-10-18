"""add diet plan category

Revision ID: 0003_add_diet_plan_category
Revises: 0002_normalize_currency_codes
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_add_diet_plan_category"
down_revision = "0002_normalize_currency_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "diet_plans",
        sa.Column("category", sa.String(length=40), server_default="Custom", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("diet_plans", "category")
