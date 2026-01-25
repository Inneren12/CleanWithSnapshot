from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.admin_audit.db_models import AdminAuditActionType, AdminAuditSensitivity


class AdminAuditLogEntry(BaseModel):
    audit_id: str
    created_at: datetime
    admin_id: str | None
    actor: str
    role: str
    auth_method: str | None
    action: str
    action_type: AdminAuditActionType
    sensitivity_level: AdminAuditSensitivity
    resource_type: str | None
    resource_id: str | None
    context: dict | None = None


class AdminAuditLogListResponse(BaseModel):
    audits: list[AdminAuditLogEntry] = Field(default_factory=list)
    limit: int
    offset: int
