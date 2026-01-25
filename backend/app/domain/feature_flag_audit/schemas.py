from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.config_audit.db_models import ConfigActorType
from app.domain.feature_flag_audit.db_models import FeatureFlagAuditAction


class FeatureFlagAuditLogEntry(BaseModel):
    audit_id: str
    occurred_at: datetime
    actor_type: ConfigActorType
    actor_id: str | None
    actor_role: str | None
    auth_method: str | None
    actor_source: str | None
    org_id: uuid.UUID | None
    flag_key: str
    action: FeatureFlagAuditAction
    before_state: dict | None
    after_state: dict | None
    rollout_context: dict | None
    request_id: str | None


class FeatureFlagAuditLogListResponse(BaseModel):
    items: list[FeatureFlagAuditLogEntry] = Field(default_factory=list)
    limit: int
    offset: int
    next_offset: int | None
