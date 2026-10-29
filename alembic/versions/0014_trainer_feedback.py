"""add trainer feedback

Revision ID: 0014_trainer_feedback
Revises: 0013_live_notifications
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014_trainer_feedback"
down_revision = "0013_live_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trainer_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("gym_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trainer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_month", sa.Date(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("feedback_option", sa.String(length=120)),
        sa.Column("feedback_text", sa.String(length=1200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("gym_id", "member_id", "trainer_id", "review_month", name="uq_trainer_feedback_member_month"),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_trainer_feedback_rating"),
    )
    op.create_index("ix_trainer_feedback_gym_trainer_month", "trainer_feedback", ["gym_id", "trainer_id", "review_month"])
    op.create_index("ix_trainer_feedback_gym_member_month", "trainer_feedback", ["gym_id", "member_id", "review_month"])


def downgrade():
    op.drop_table("trainer_feedback")
