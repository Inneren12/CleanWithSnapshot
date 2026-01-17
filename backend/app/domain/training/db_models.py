from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import UUID_TYPE, Base
from app.settings import settings

if TYPE_CHECKING:  # pragma: no cover
    from app.domain.workers.db_models import Worker


class TrainingRequirement(Base):
    __tablename__ = "training_requirements"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    renewal_months: Mapped[int | None] = mapped_column(Integer)
    required_for_role: Mapped[str | None] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    records: Mapped[list["WorkerTrainingRecord"]] = relationship(
        "WorkerTrainingRecord",
        back_populates="requirement",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_training_requirements_org_key"),
        Index("ix_training_requirements_org_id", "org_id"),
        Index("ix_training_requirements_org_active", "org_id", "active"),
        Index("ix_training_requirements_key", "key"),
        Index("ix_training_requirements_required_for_role", "required_for_role"),
    )


class WorkerTrainingRecord(Base):
    __tablename__ = "worker_training_records"

    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("training_requirements.requirement_id", ondelete="CASCADE"),
        nullable=False,
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    requirement: Mapped[TrainingRequirement] = relationship(
        "TrainingRequirement", back_populates="records"
    )
    worker: Mapped["Worker"] = relationship("Worker")

    __table_args__ = (
        Index("ix_worker_training_records_org_id", "org_id"),
        Index("ix_worker_training_records_worker_id", "worker_id"),
        Index("ix_worker_training_records_requirement_id", "requirement_id"),
        Index("ix_worker_training_records_expires_at", "expires_at"),
    )


class TrainingCourse(Base):
    __tablename__ = "training_courses"

    course_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    format: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    assignments: Mapped[list["TrainingAssignment"]] = relationship(
        "TrainingAssignment",
        back_populates="course",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_training_courses_org_id", "org_id"),
        Index("ix_training_courses_org_active", "org_id", "active"),
        Index("ix_training_courses_title", "title"),
    )


class TrainingAssignment(Base):
    __tablename__ = "training_assignments"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("training_courses.course_id", ondelete="CASCADE"),
        nullable=False,
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="CASCADE"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="assigned", server_default="assigned")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int | None] = mapped_column(Integer)
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE)

    course: Mapped[TrainingCourse] = relationship("TrainingCourse", back_populates="assignments")
    worker: Mapped["Worker"] = relationship("Worker")

    __table_args__ = (
        Index("ix_training_assignments_org_id", "org_id"),
        Index("ix_training_assignments_course_id", "course_id"),
        Index("ix_training_assignments_worker_id", "worker_id"),
        Index("ix_training_assignments_status", "status"),
        Index("ix_training_assignments_due_at", "due_at"),
    )


class TrainingSession(Base):
    __tablename__ = "training_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    instructor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    attendees: Mapped[list["TrainingSessionAttendee"]] = relationship(
        "TrainingSessionAttendee",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_training_sessions_org_id", "org_id"),
        Index("ix_training_sessions_window", "starts_at", "ends_at"),
    )


class TrainingSessionAttendee(Base):
    __tablename__ = "training_session_attendees"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("training_sessions.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    worker_id: Mapped[int] = mapped_column(
        ForeignKey("workers.worker_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="enrolled", server_default="enrolled"
    )
    block_id: Mapped[int | None] = mapped_column(
        ForeignKey("availability_blocks.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped["TrainingSession"] = relationship("TrainingSession", back_populates="attendees")
    worker: Mapped["Worker"] = relationship("Worker")

    __table_args__ = (
        UniqueConstraint("session_id", "worker_id", name="uq_training_session_attendee"),
        Index("ix_training_session_attendees_worker", "worker_id"),
        Index("ix_training_session_attendees_status", "status"),
    )
