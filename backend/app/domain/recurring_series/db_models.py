from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class RecurringSeries(Base):
    __tablename__ = "recurring_series"

    series_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    client_id: Mapped[str | None] = mapped_column(
        ForeignKey("client_users.client_id", ondelete="SET NULL"), nullable=True
    )
    address_id: Mapped[int | None] = mapped_column(
        ForeignKey("client_addresses.address_id", ondelete="SET NULL"), nullable=True
    )
    service_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_types.service_type_id", ondelete="SET NULL"), nullable=True
    )
    preferred_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.team_id", ondelete="SET NULL"), nullable=True
    )
    preferred_worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="weekly")
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    by_weekday: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    by_monthday: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    ends_on: Mapped[date | None] = mapped_column(Date)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    bookings: Mapped[list["Booking"]] = relationship(
        "Booking",
        back_populates="recurring_series",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_recurring_series_org_id", "org_id"),
        Index("ix_recurring_series_status", "status"),
        Index("ix_recurring_series_next_run", "next_run_at"),
    )
