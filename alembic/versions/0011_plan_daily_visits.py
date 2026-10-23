"""Add membership plan daily visit allowance."""
from alembic import op
import sqlalchemy as sa

revision = "0011_plan_daily_visits"
down_revision = "0010_expire_action_tokens"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("membership_plans", sa.Column("daily_visit_limit", sa.Integer(), nullable=False, server_default="4"))
    op.create_check_constraint("ck_plan_daily_visits", "membership_plans", "daily_visit_limit BETWEEN 1 AND 24")

def downgrade():
    op.drop_constraint("ck_plan_daily_visits", "membership_plans", type_="check")
    op.drop_column("membership_plans", "daily_visit_limit")
