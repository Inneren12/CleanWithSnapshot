from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base, UUID_TYPE


class OrgStorageReservation(Base):
    __tablename__ = "org_storage_reservations"

    reservation_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
    )
    bytes_reserved: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    bytes_finalized: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        sa.Index("ix_storage_reservations_org", "org_id"),
        sa.Index("ix_storage_reservations_org_status", "org_id", "status"),
        sa.Index("ix_storage_reservations_expires", "expires_at"),
    )
