"""Allow platform notifications without a gym."""
from alembic import op

revision = "0012_platform_notifications"
down_revision = "0011_plan_daily_visits"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("notifications", "gym_id", nullable=True)


def downgrade():
    op.execute("DELETE FROM notifications WHERE gym_id IS NULL")
    op.alter_column("notifications", "gym_id", nullable=False)
