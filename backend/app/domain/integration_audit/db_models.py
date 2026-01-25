from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, String, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db import Base, UUID_TYPE


class IntegrationScope(str, Enum):
    ORG = "org"
    SYSTEM = "system"


class IntegrationAuditAction(str, Enum):
    ENABLE = "enable"
    DISABLE = "disable"
    CREATE = "create"
    UPDATE = "update"
    ROTATE_SECRET = "rotate_secret"
    DELETE = "delete"


@dataclass(frozen=True)
class IntegrationAuditContext:
    integration_type: str
    integration_scope: IntegrationScope


JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


class IntegrationAuditLog(Base):
    __tablename__ = "integration_audit_logs"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auth_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="SET NULL"),
        nullable=True,
    )
    integration_type: Mapped[str] = mapped_column(String(64), nullable=False)
    integration_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    redaction_map: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_integration_audit_logs_org_id", "org_id"),
        Index("ix_integration_audit_logs_type", "integration_type"),
        Index("ix_integration_audit_logs_occurred_at", "occurred_at"),
        Index(
            "ix_integration_audit_logs_org_type_time",
            "org_id",
            "integration_type",
            "occurred_at",
        ),
    )


@event.listens_for(IntegrationAuditLog, "before_update", propagate=True)
def _prevent_integration_audit_updates(mapper, connection, target) -> None:  # noqa: ARG001
    raise ValueError("Integration audit records are immutable")


@event.listens_for(IntegrationAuditLog, "before_delete", propagate=True)
def _prevent_integration_audit_deletes(mapper, connection, target) -> None:  # noqa: ARG001
    raise ValueError("Integration audit records cannot be deleted")
