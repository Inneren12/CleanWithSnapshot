from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class TrainingRequirementStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    title: str
    required: bool
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    next_due_at: datetime | None = None
    status: Literal["ok", "due", "overdue"]


class TrainingStatusResponse(BaseModel):
    worker_id: int
    requirements: list[TrainingRequirementStatus]


class TrainingRecordCreateRequest(BaseModel):
    requirement_id: uuid.UUID | None = None
    requirement_key: str | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    score: int | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _ensure_requirement(self) -> "TrainingRecordCreateRequest":
        if not self.requirement_id and not self.requirement_key:
            raise ValueError("requirement_key_or_id_required")
        return self


class TrainingRecordResponse(BaseModel):
    record_id: uuid.UUID
    worker_id: int
    requirement_id: uuid.UUID
    completed_at: datetime
    expires_at: datetime | None = None
    score: int | None = None
    note: str | None = None
    created_at: datetime
