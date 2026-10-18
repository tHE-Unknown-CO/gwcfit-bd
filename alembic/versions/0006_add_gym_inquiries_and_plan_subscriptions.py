"""add gym inquiries and platform plan subscriptions

Revision ID: 0006_gym_sales
Revises: 0005_add_platform_plans
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_gym_sales"
down_revision = "0005_add_platform_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gym_inquiries",
        sa.Column("full_name", sa.String(length=180), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("gym_name", sa.String(length=180), nullable=False),
        sa.Column("active_members_range", sa.String(length=40), nullable=False),
        sa.Column("interested_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="new", nullable=False),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("gym_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=80), server_default="owner_site", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["gym_id"], ["gyms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["interested_plan_id"], ["platform_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("email", "status", "interested_plan_id", "invitation_id", "gym_id", "created_by", "updated_by"):
        op.create_index(f"ix_gym_inquiries_{column}", "gym_inquiries", [column])

    op.add_column("subscriptions", sa.Column("platform_plan_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("subscriptions", sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_subscriptions_platform_plan_id", "subscriptions", "platform_plans", ["platform_plan_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_subscriptions_platform_plan_id", "subscriptions", ["platform_plan_id"])
    op.create_unique_constraint("uq_subscriptions_gym_id", "subscriptions", ["gym_id"])


def downgrade() -> None:
    op.drop_constraint("uq_subscriptions_gym_id", "subscriptions", type_="unique")
    op.drop_index("ix_subscriptions_platform_plan_id", table_name="subscriptions")
    op.drop_constraint("fk_subscriptions_platform_plan_id", "subscriptions", type_="foreignkey")
    op.drop_column("subscriptions", "trial_started_at")
    op.drop_column("subscriptions", "platform_plan_id")
    op.drop_table("gym_inquiries")
