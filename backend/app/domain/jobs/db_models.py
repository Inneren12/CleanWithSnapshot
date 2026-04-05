"""Persistent Job model for orchestrating long-running tasks.

Architecture decision R7: All long-running operations (catalog sync,
data fetch, chart generation) are tracked as persistent DB-backed jobs.
Jobs survive server restarts. Status is queryable via API.

Commit semantics follow the repository pattern established in this
project: repositories flush/refresh but do NOT commit. The ``get_db``
dependency handles commit/rollback at request boundary.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base


class JobStatus(str, enum.Enum):
    """Lifecycle status of a job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    """A persistent record of a long-running background task.

    Attributes:
        id: Auto-incrementing primary key.
        job_type: Identifier for the kind of work (e.g. ``"catalog_sync"``,
            ``"cube_fetch"``, ``"graphics_generate"``).
        status: Current lifecycle status.
        payload_json: JSON-serialized typed payload (see ``job_payloads.py``).
        result_json: JSON-serialized result on success (nullable).
        error_code: Machine-readable error code on failure (nullable).
        error_message: Human-readable error description (nullable).
        attempt_count: How many times this job has been attempted.
        max_attempts: Maximum retry attempts before permanent failure.
        created_at: When the job was enqueued.
        started_at: When the job was last claimed by a runner.
        finished_at: When the job reached a terminal state.
        created_by: Operator / system identifier that enqueued the job.
        dedupe_key: Optional unique key preventing duplicate jobs.
            If a job with the same dedupe_key exists in queued/running
            status, enqueue returns the existing job instead.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_type_status", "job_type", "status"),
        Index("ix_jobs_created_at", "created_at"),
        Index("ix_jobs_dedupe_key", "dedupe_key", unique=False),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"),
        nullable=False,
        default=JobStatus.QUEUED,
        server_default="queued",
    )

    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    dedupe_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Job(id={self.id}, type={self.job_type!r}, "
            f"status={self.status.value}, attempt={self.attempt_count})>"
        )
