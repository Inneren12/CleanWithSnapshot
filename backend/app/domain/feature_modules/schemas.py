from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class FeatureConfigResponse(BaseModel):
    org_id: uuid.UUID
    overrides: dict[str, bool] = Field(default_factory=dict)
    defaults: dict[str, bool] = Field(default_factory=dict)
    effective: dict[str, bool] = Field(default_factory=dict)
    keys: list[str] = Field(default_factory=list)


class FeatureConfigUpdateRequest(BaseModel):
    overrides: dict[str, bool] = Field(default_factory=dict)


class UiPrefsResponse(BaseModel):
    hidden_keys: list[str] = Field(default_factory=list)


class UiPrefsUpdateRequest(BaseModel):
    hidden_keys: list[str] = Field(default_factory=list)
