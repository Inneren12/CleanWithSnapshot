from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, root_validator, validator

ALLOWED_ROLLOUT_PERCENTAGES = {0, 10, 25, 50, 100}


class FeatureOverrideConfig(BaseModel):
    enabled: bool | None = None
    percentage: int | None = None

    @validator("percentage")
    def validate_percentage(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value not in ALLOWED_ROLLOUT_PERCENTAGES:
            raise ValueError("percentage must be one of 0, 10, 25, 50, or 100")
        return value

    @root_validator
    def ensure_override_present(cls, values: dict[str, object]) -> dict[str, object]:
        enabled = values.get("enabled")
        percentage = values.get("percentage")
        if enabled is None and percentage is None:
            raise ValueError("override must include enabled or percentage")
        return values


FeatureOverrideValue = bool | FeatureOverrideConfig


class FeatureConfigResponse(BaseModel):
    org_id: uuid.UUID
    overrides: dict[str, FeatureOverrideValue] = Field(default_factory=dict)
    defaults: dict[str, bool] = Field(default_factory=dict)
    effective: dict[str, bool] = Field(default_factory=dict)
    keys: list[str] = Field(default_factory=list)


class FeatureConfigUpdateRequest(BaseModel):
    overrides: dict[str, FeatureOverrideValue] = Field(default_factory=dict)
    reason: str | None = None
    allow_expired_override: bool = False
    override_reason: str | None = None


class UiPrefsResponse(BaseModel):
    hidden_keys: list[str] = Field(default_factory=list)


class UiPrefsUpdateRequest(BaseModel):
    hidden_keys: list[str] = Field(default_factory=list)
