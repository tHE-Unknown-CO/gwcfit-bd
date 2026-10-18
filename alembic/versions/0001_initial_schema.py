"""initial multi-tenant schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-03
"""
from alembic import op
from sqlalchemy import text

from app.database.base import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
