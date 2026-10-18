"""add secure invitations

Revision ID: 0004_add_invitations
Revises: 0003_add_diet_plan_category
Create Date: 2026-09-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_add_invitations"
down_revision = "0003_add_diet_plan_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("gym_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("token_hash", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), server_default="1", nullable=False),
        sa.Column("use_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["gym_id"], ["gyms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("gym_id", "role", "email", "status", "expires_at", "used_by", "created_by", "updated_by"):
        op.create_index(f"ix_invitations_{column}", "invitations", [column])
    op.create_index("ix_invitations_token_hash", "invitations", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("invitations")
