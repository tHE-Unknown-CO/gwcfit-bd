"""expire password-reset and email-verification tokens

Revision ID: 0010_expire_action_tokens
Revises: 0009_invite_tokens
Create Date: 2026-09-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_expire_action_tokens"
down_revision = "0009_invite_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Invitation credentials are one-time secrets. The hash is sufficient for
    # validation; retaining reversible ciphertext creates needless exposure.
    op.drop_column("invitations", "encrypted_token")
    op.add_column(
        "users",
        sa.Column("password_reset_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_users_password_reset_token_hash",
        "users",
        ["password_reset_token_hash"],
        unique=False,
    )
    op.create_index(
        "ix_users_email_verification_token_hash",
        "users",
        ["email_verification_token_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_email_verification_token_hash", table_name="users")
    op.drop_index("ix_users_password_reset_token_hash", table_name="users")
    op.drop_column("users", "email_verification_token_expires_at")
    op.drop_column("users", "password_reset_token_expires_at")
    op.add_column("invitations", sa.Column("encrypted_token", sa.Text(), nullable=True))
