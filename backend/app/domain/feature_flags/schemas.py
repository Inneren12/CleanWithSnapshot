from __future__ import annotations

from datetime import datetime

from enum import Enum

from pydantic import BaseModel, Field

from app.domain.feature_flags.db_models import FeatureFlagLifecycleState


class FeatureFlagDefinitionBase(BaseModel):
    key: str
    owner: str
    purpose: str
    created_at: datetime
    expires_at: datetime | None
    lifecycle_state: FeatureFlagLifecycleState
    effective_state: FeatureFlagLifecycleState


class FeatureFlagDefinitionListResponse(BaseModel):
    items: list[FeatureFlagDefinitionBase] = Field(default_factory=list)


class FeatureFlagDefinitionCreateRequest(BaseModel):
    key: str
    owner: str
    purpose: str
    expires_at: datetime
    lifecycle_state: FeatureFlagLifecycleState = FeatureFlagLifecycleState.DRAFT
    override_max_horizon: bool = False
    override_reason: str | None = None


class FeatureFlagDefinitionUpdateRequest(BaseModel):
    owner: str | None = None
    purpose: str | None = None
    expires_at: datetime | None = None
    lifecycle_state: FeatureFlagLifecycleState | None = None
    override_max_horizon: bool = False
    override_reason: str | None = None


class FeatureFlagStaleCategory(str, Enum):
    NEVER = "never"
    INACTIVE = "inactive"


class FeatureFlagStaleItem(BaseModel):
    key: str
    owner: str
    purpose: str
    created_at: datetime
    expires_at: datetime | None
    lifecycle_state: FeatureFlagLifecycleState
    last_evaluated_at: datetime | None
    evaluate_count: int
    stale_category: FeatureFlagStaleCategory


class FeatureFlagStaleListResponse(BaseModel):
    items: list[FeatureFlagStaleItem] = Field(default_factory=list)
    limit: int
    offset: int
    next_offset: int | None
