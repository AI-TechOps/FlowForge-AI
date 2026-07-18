import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TenantBase, TimestampMixin


class Role(enum.StrEnum):
    administrator = "administrator"
    operator = "operator"
    approver = "approver"


class User(TenantBase, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_users_org_email"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # OAuth2 subject, linked at first login in Phase 4. No password column:
    # auth is Auth0-only; we never store or handle passwords.
    auth_subject: Mapped[str | None] = mapped_column(String(255), unique=True)

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserRole(TimestampMixin, Base):
    """One row per role grant; multiple roles = multiple rows (D14)."""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", values_callable=lambda e: [m.value for m in e]),
        primary_key=True,
    )

    user: Mapped[User] = relationship(back_populates="roles")
