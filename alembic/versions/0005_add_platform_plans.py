"""add editable platform plans

Revision ID: 0005_add_platform_plans
Revises: 0004_add_invitations
Create Date: 2026-09-10
"""
from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_add_platform_plans"
down_revision = "0004_add_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    plans = op.create_table(
        "platform_plans",
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("billing_period", sa.String(length=40), nullable=True),
        sa.Column("member_limit", sa.String(length=120), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cta_label", sa.String(length=120), nullable=False),
        sa.Column("trial_days", sa.Integer(), server_default="30", nullable=False),
        sa.Column("is_popular", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_platform_plans_slug", "platform_plans", ["slug"], unique=True)
    op.create_index("ix_platform_plans_created_by", "platform_plans", ["created_by"])
    op.create_index("ix_platform_plans_updated_by", "platform_plans", ["updated_by"])
    op.bulk_insert(plans, [
        {"id": UUID("10000000-0000-0000-0000-000000000001"), "slug": "launch", "name": "Launch", "description": "For independent gyms getting organised", "price_cents": 199900, "currency": "INR", "billing_period": "month", "member_limit": "Up to 150 members", "features": ["Owner + staff dashboard", "Member management", "Attendance & check-in", "Membership plans & payments", "Basic reports", "Member mobile experience"], "cta_label": "Start 1 month free", "trial_days": 30, "is_popular": False, "display_order": 1, "is_active": True},
        {"id": UUID("10000000-0000-0000-0000-000000000002"), "slug": "grow", "name": "Grow", "description": "For growing teams that want more automation", "price_cents": 399900, "currency": "INR", "billing_period": "month", "member_limit": "Up to 500 members", "features": ["Everything in Launch", "Trainer workspaces", "Workout & diet planning", "Goals and progress tracking", "Advanced reports", "Roles and permissions", "Priority support"], "cta_label": "Start 1 month free", "trial_days": 30, "is_popular": True, "display_order": 2, "is_active": True},
        {"id": UUID("10000000-0000-0000-0000-000000000003"), "slug": "scale", "name": "Scale", "description": "For multi-location fitness businesses", "price_cents": None, "currency": "INR", "billing_period": None, "member_limit": "500+ members", "features": ["Everything in Grow", "Multiple gym locations", "Cross-location analytics", "Custom roles and controls", "Data onboarding support", "Dedicated success manager"], "cta_label": "Talk to us", "trial_days": 30, "is_popular": False, "display_order": 3, "is_active": True},
    ])


def downgrade() -> None:
    op.drop_table("platform_plans")
