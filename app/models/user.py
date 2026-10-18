import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, EnterpriseMixin
from app.models.enums import RoleName


class Role(EnterpriseMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("gym_id", "name", name="uq_roles_gym_name"),)

    gym_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gyms.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Permission(EnterpriseMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)


class RolePermission(EnterpriseMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"))
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
    )


class User(EnterpriseMixin, Base):
    __tablename__ = "users"

    gym_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gyms.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default=RoleName.MEMBER.value, nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_email_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    refresh_token_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_token_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    password_reset_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verification_token_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    email_verification_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    gym = relationship("Gym", back_populates="users")
    permission_overrides = relationship("UserPermission", back_populates="user", cascade="all, delete-orphan")

    @property
    def gym_name(self) -> str | None:
        gym = getattr(self, "gym", None)
        return gym.name if gym is not None else None


class UserPermission(EnterpriseMixin, Base):
    __tablename__ = "user_permissions"
    __table_args__ = (UniqueConstraint("user_id", "permission", name="uq_user_permission_override"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    permission: Mapped[str] = mapped_column(String(120), nullable=False)
    allowed: Mapped[bool] = mapped_column(default=True, nullable=False)

    user = relationship("User", back_populates="permission_overrides")
