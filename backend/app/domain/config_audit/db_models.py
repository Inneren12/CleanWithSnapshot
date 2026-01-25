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


class ConfigActorType(str, Enum):
    ADMIN = "admin"
    SYSTEM = "system"
    AUTOMATION = "automation"


class ConfigScope(str, Enum):
    ORG_SETTINGS = "org_settings"
    FEATURE_FLAG = "feature_flag"
    INTEGRATION = "integration"
    SYSTEM = "system"


class ConfigAuditAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True)
class ConfigAuditActor:
    actor_type: ConfigActorType
    actor_id: str | None
    actor_role: str | None
    auth_method: str | None
    actor_source: str | None = None


JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


class ConfigAuditLog(Base):
    __tablename__ = "config_audit_logs"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
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
    config_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    config_key: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_value: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    after_value: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_config_audit_logs_org_id", "org_id"),
        Index("ix_config_audit_logs_scope", "config_scope"),
        Index("ix_config_audit_logs_occurred_at", "occurred_at"),
        Index("ix_config_audit_logs_org_scope_time", "org_id", "config_scope", "occurred_at"),
    )


@event.listens_for(ConfigAuditLog, "before_update", propagate=True)
def _prevent_config_audit_updates(mapper, connection, target) -> None:  # noqa: ARG001
    raise ValueError("Config audit records are immutable")


@event.listens_for(ConfigAuditLog, "before_delete", propagate=True)
def _prevent_config_audit_deletes(mapper, connection, target) -> None:  # noqa: ARG001
    raise ValueError("Config audit records cannot be deleted")
