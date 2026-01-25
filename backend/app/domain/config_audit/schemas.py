from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.config_audit.db_models import ConfigAuditAction, ConfigActorType, ConfigScope


class ConfigAuditLogEntry(BaseModel):
    audit_id: str
    occurred_at: datetime
    actor_type: ConfigActorType
    actor_id: str | None
    actor_role: str | None
    auth_method: str | None
    actor_source: str | None
    org_id: uuid.UUID | None
    config_scope: ConfigScope
    config_key: str
    action: ConfigAuditAction
    before_value: dict | None
    after_value: dict | None
    request_id: str | None


class ConfigAuditLogListResponse(BaseModel):
    items: list[ConfigAuditLogEntry] = Field(default_factory=list)
    limit: int
    offset: int
    next_offset: int | None
