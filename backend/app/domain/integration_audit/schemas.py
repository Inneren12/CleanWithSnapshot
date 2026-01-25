from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel

from app.domain.config_audit import ConfigActorType
from app.domain.integration_audit import IntegrationAuditAction, IntegrationScope


class IntegrationAuditLogEntry(BaseModel):
    audit_id: str
    occurred_at: datetime
    actor_type: ConfigActorType
    actor_id: str | None
    actor_role: str | None
    auth_method: str | None
    actor_source: str | None
    org_id: uuid.UUID | None
    integration_type: str
    integration_scope: IntegrationScope
    action: IntegrationAuditAction
    before_state: dict | None
    after_state: dict | None
    redaction_map: dict | None
    request_id: str | None


class IntegrationAuditLogListResponse(BaseModel):
    items: list[IntegrationAuditLogEntry]
    limit: int
    offset: int
    next_offset: int | None
