from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    enabled: bool = False
    dry_run: bool = True
    trigger_type: str = Field(min_length=1, max_length=64)
    conditions_json: dict[str, Any] = Field(default_factory=dict)
    actions_json: list[Any] = Field(default_factory=list)


class RuleCreate(RuleBase):
    pass


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    enabled: bool | None = None
    dry_run: bool | None = None
    trigger_type: str | None = Field(default=None, min_length=1, max_length=64)
    conditions_json: dict[str, Any] | None = None
    actions_json: list[Any] | None = None


class RuleResponse(RuleBase):
    rule_id: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime


class RuleRunResponse(BaseModel):
    run_id: uuid.UUID
    org_id: uuid.UUID
    rule_id: uuid.UUID
    occurred_at: datetime
    entity_type: str | None
    entity_id: str | None
    matched: bool
    actions_json: list[Any]
    idempotency_key: str | None
    created_at: datetime


class RuleTestRequest(BaseModel):
    rule_id: uuid.UUID
    payload: dict[str, Any] = Field(default_factory=dict)
    trigger_type: str | None = Field(default=None, min_length=1, max_length=64)
    occurred_at: datetime | None = None
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: str | None = Field(default=None, max_length=64)
    idempotency_key: str | None = None


class RuleTestResponse(BaseModel):
    rule_id: uuid.UUID
    matched: bool
    dry_run: bool
    actions_json: list[Any]


class RuleRunEventRequest(BaseModel):
    trigger_type: str = Field(min_length=1, max_length=64)
    event_payload: dict[str, Any] = Field(default_factory=dict)


class RuleRunEventResponse(BaseModel):
    trigger_type: str
    run_count: int
    matched_count: int
    runs: list[RuleRunResponse]
