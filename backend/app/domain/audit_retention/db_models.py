from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Index, String, event, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.infra.db import Base, UUID_TYPE


class AuditLogScope(str, Enum):
    ADMIN = "admin"
    CONFIG = "config"
    FEATURE_FLAG = "feature_flag"
    INTEGRATION = "integration"
    ALL = "all"


class AuditLegalHold(Base):
    __tablename__ = "audit_legal_holds"

    hold_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    audit_scope: Mapped[str] = mapped_column(String(32), nullable=False, default=AuditLogScope.ALL.value)
    applies_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applies_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    investigation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_audit_legal_holds_org_id", "org_id"),
        Index("ix_audit_legal_holds_scope", "audit_scope"),
        Index("ix_audit_legal_holds_investigation", "investigation_id"),
        Index("ix_audit_legal_holds_active", "released_at"),
    )


class AuditPurgeEvent(Base):
    __tablename__ = "audit_purge_events"

    purge_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dry_run: Mapped[bool] = mapped_column(default=False)
    policy_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    purge_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_purge_events_started_at", "started_at"),
        Index("ix_audit_purge_events_actor_type", "actor_type"),
    )


@event.listens_for(AuditPurgeEvent, "before_update", propagate=True)
def _prevent_purge_event_updates(mapper, connection, target) -> None:  # noqa: ARG001
    raise ValueError("Audit purge events are immutable")


@event.listens_for(AuditPurgeEvent, "before_delete", propagate=True)
def _prevent_purge_event_deletes(mapper, connection, target) -> None:  # noqa: ARG001
    raise ValueError("Audit purge events cannot be deleted")


@event.listens_for(AuditLegalHold, "before_delete", propagate=True)
def _prevent_legal_hold_deletes(mapper, connection, target) -> None:  # noqa: ARG001
    raise ValueError("Audit legal holds cannot be deleted")
