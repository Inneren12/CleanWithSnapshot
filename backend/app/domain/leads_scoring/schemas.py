from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class LeadScoringCondition(BaseModel):
    field: str = Field(..., min_length=1, max_length=200)
    op: str = Field("equals", min_length=1, max_length=20)
    value: Any | None = None


class LeadScoringRuleDefinition(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=255)
    points: int = Field(..., ge=-10000, le=10000)
    conditions: list[LeadScoringCondition] = Field(default_factory=list)


class LeadScoringRulesUpdateRequest(BaseModel):
    enabled: bool = True
    rules: list[LeadScoringRuleDefinition] = Field(default_factory=list)


class LeadScoringRuleVersionResponse(BaseModel):
    org_id: UUID
    version: int
    enabled: bool
    rules: list[LeadScoringRuleDefinition]
    created_at: datetime

    class Config:
        from_attributes = True


class LeadScoringRulesListResponse(BaseModel):
    active_version: int | None
    items: list[LeadScoringRuleVersionResponse]


class LeadScoringReason(BaseModel):
    rule_key: str
    label: str
    points: int


class LeadScoringSnapshotResponse(BaseModel):
    org_id: UUID
    lead_id: str
    score: int
    reasons: list[LeadScoringReason]
    computed_at: datetime
    rules_version: int
