from datetime import date, datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, func
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
    reviews: Mapped[list["WorkerReview"]] = relationship(
        "WorkerReview",
        back_populates="worker",
        cascade="all, delete-orphan",
    )
    notes: Mapped[list["WorkerNote"]] = relationship(
        "WorkerNote",
        back_populates="worker",
        cascade="all, delete-orphan",
    )
    onboarding: Mapped["WorkerOnboarding | None"] = relationship(
        "WorkerOnboarding",
        back_populates="worker",
        uselist=False,
        cascade="all, delete-orphan",
    )
    certificates: Mapped[list["WorkerCertificate"]] = relationship(
        "WorkerCertificate",
        back_populates="worker",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_workers_org_id", "org_id"),
        Index("ix_workers_org_active", "org_id", "is_active"),
        Index("ix_workers_phone", "phone"),
        Index("ix_workers_archived_at", "archived_at"),
    )


class WorkerReview(Base):
    __tablename__ = "worker_reviews"

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    booking_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("bookings.booking_id", ondelete="CASCADE"),
        nullable=False,
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    worker: Mapped["Worker"] = relationship("Worker", back_populates="reviews")
    booking: Mapped["Booking"] = relationship("Booking", back_populates="worker_reviews")

    __table_args__ = (
        Index("ix_worker_reviews_org_id", "org_id"),
        Index("ix_worker_reviews_worker_id", "worker_id"),
        Index("ix_worker_reviews_booking_id", "booking_id"),
        Index("ix_worker_reviews_created_at", "created_at"),
    )


class WorkerNote(Base):
    __tablename__ = "worker_notes"

    note_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="CASCADE"),
        nullable=False,
    )
    booking_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("bookings.booking_id", ondelete="CASCADE"),
    )
    note_type: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    worker: Mapped["Worker"] = relationship("Worker", back_populates="notes")
    booking: Mapped["Booking | None"] = relationship("Booking", back_populates="worker_notes")

    __table_args__ = (
        Index("ix_worker_notes_org_id", "org_id"),
        Index("ix_worker_notes_worker_id", "worker_id"),
        Index("ix_worker_notes_booking_id", "booking_id"),
        Index("ix_worker_notes_note_type", "note_type"),
        Index("ix_worker_notes_created_at", "created_at"),
    )


class WorkerOnboarding(Base):
    __tablename__ = "worker_onboarding"

    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="CASCADE"), primary_key=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    docs_received: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    background_check: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    training_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    first_booking_done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    worker: Mapped["Worker"] = relationship("Worker", back_populates="onboarding")

    __table_args__ = (Index("ix_worker_onboarding_org_id", "org_id"),)


class WorkerCertificate(Base):
    __tablename__ = "worker_certificates"

    cert_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    issued_at: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    worker: Mapped["Worker"] = relationship("Worker", back_populates="certificates")

    __table_args__ = (
        Index("ix_worker_certificates_org_id", "org_id"),
        Index("ix_worker_certificates_worker_id", "worker_id"),
        Index("ix_worker_certificates_status", "status"),
        Index("ix_worker_certificates_expires_at", "expires_at"),
    )
