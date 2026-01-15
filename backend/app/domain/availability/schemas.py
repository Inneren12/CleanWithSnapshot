from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScopeType = Literal["worker", "team", "org"]
BlockType = Literal["vacation", "sick", "training", "holiday"]


class AvailabilityBlockBase(BaseModel):
    scope_type: ScopeType
    scope_id: int | None = None
    block_type: BlockType
    starts_at: datetime
    ends_at: datetime
    reason: str | None = Field(default=None, max_length=255)


class AvailabilityBlockCreate(AvailabilityBlockBase):
    pass


class AvailabilityBlockUpdate(BaseModel):
    scope_type: ScopeType | None = None
    scope_id: int | None = None
    block_type: BlockType | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=255)


class AvailabilityBlockResponse(AvailabilityBlockBase):
    id: int
    created_by: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
