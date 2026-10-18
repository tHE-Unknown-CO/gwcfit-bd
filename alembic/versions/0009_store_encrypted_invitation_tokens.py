"""store encrypted invitation tokens for authorized senders

Revision ID: 0009_invite_tokens
Revises: 0008_unique_inquiry
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_invite_tokens"
down_revision = "0008_unique_inquiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invitations", sa.Column("encrypted_token", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("invitations", "encrypted_token")
