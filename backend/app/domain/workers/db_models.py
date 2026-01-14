from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.infra.db import UUID_TYPE
from app.infra.db import Base
from app.settings import settings

if TYPE_CHECKING:  # pragma: no cover
    from app.domain.bookings.db_models import Booking, BookingWorker, Team


class Worker(Base):
    __tablename__ = "workers"

    worker_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.team_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(80))
    hourly_rate_cents: Mapped[int | None] = mapped_column(Integer)
    rating_avg: Mapped[float | None] = mapped_column(Float)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skills: Mapped[list[str] | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    team: Mapped["Team"] = relationship("Team")
    bookings: Mapped[list["Booking"]] = relationship(
        "Booking", back_populates="assigned_worker"
    )
    booking_assignments: Mapped[list["BookingWorker"]] = relationship(
        "BookingWorker",
        back_populates="worker",
        cascade="all, delete-orphan",
    )
    assigned_bookings: Mapped[list["Booking"]] = relationship(
        "Booking",
        secondary="booking_workers",
        back_populates="assigned_workers",
        viewonly=True,
    )

    __table_args__ = (
        Index("ix_workers_org_id", "org_id"),
        Index("ix_workers_org_active", "org_id", "is_active"),
        Index("ix_workers_phone", "phone"),
        Index("ix_workers_archived_at", "archived_at"),
    )
