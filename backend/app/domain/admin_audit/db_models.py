import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Index, String, event, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.infra.db import UUID_TYPE
from app.infra.db import Base
from app.settings import settings


class AdminAuditActionType(str, Enum):
    READ = "READ"
    WRITE = "WRITE"


class AdminAuditSensitivity(str, Enum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    CRITICAL = "critical"


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    admin_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(150), nullable=False)
    action_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=AdminAuditActionType.WRITE.value,
    )
    sensitivity_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AdminAuditSensitivity.NORMAL.value,
    )
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    auth_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_admin_audit_logs_org_id", "org_id"),
        Index("ix_admin_audit_logs_org_created", "org_id", "created_at"),
        Index("ix_admin_audit_logs_action_type", "action_type"),
        Index("ix_admin_audit_logs_resource_type", "resource_type"),
        Index("ix_admin_audit_logs_hash", "hash", unique=True),
    )


@event.listens_for(AdminAuditLog, "before_update", propagate=True)
def _prevent_admin_audit_updates(mapper, connection, target) -> None:  # noqa: ARG001
    raise ValueError("Admin audit records are immutable")


@event.listens_for(AdminAuditLog, "before_delete", propagate=True)
def _prevent_admin_audit_deletes(mapper, connection, target) -> None:  # noqa: ARG001
    raise ValueError("Admin audit records cannot be deleted")
