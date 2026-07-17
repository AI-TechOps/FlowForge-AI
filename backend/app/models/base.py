import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TenantBase:
    """Mixin for every tenant-scoped table: carries org_id, indexed.

    Locked decision D7: org_id on every table from day one; queries are
    always filtered by it at the application layer.
    """

    @declared_attr
    def org_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
