"""make gym inquiry email and phone unique

Revision ID: 0008_unique_inquiry
Revises: 0007_login_events
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_unique_inquiry"
down_revision = "0007_login_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_gym_inquiries_email", table_name="gym_inquiries")
    op.create_index("ix_gym_inquiries_email", "gym_inquiries", ["email"], unique=True)
    op.add_column("gym_inquiries", sa.Column("phone", sa.String(length=40), nullable=False))
    op.create_index("ix_gym_inquiries_phone", "gym_inquiries", ["phone"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_gym_inquiries_phone", table_name="gym_inquiries")
    op.drop_column("gym_inquiries", "phone")
    op.drop_index("ix_gym_inquiries_email", table_name="gym_inquiries")
    op.create_index("ix_gym_inquiries_email", "gym_inquiries", ["email"], unique=False)
