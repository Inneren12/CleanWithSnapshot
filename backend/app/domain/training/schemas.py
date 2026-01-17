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


TrainingCourseFormat = Literal["video", "doc", "in_person", "mixed"]
TrainingAssignmentStatus = Literal["assigned", "in_progress", "completed", "overdue"]


class TrainingCourseCreateRequest(BaseModel):
    title: str
    description: str | None = None
    duration_minutes: int | None = None
    active: bool = True
    format: TrainingCourseFormat | None = None


class TrainingCourseUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    active: bool | None = None
    format: TrainingCourseFormat | None = None


class TrainingCourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    course_id: uuid.UUID
    title: str
    description: str | None = None
    duration_minutes: int | None = None
    active: bool
    format: TrainingCourseFormat | None = None
    created_at: datetime


class TrainingCourseListResponse(BaseModel):
    items: list[TrainingCourseResponse]
    total: int


class TrainingCourseAssignRequest(BaseModel):
    worker_ids: list[int]
    due_at: datetime | None = None


class TrainingAssignmentUpdateRequest(BaseModel):
    status: TrainingAssignmentStatus | None = None
    completed_at: datetime | None = None
    score: int | None = None


class TrainingAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assignment_id: uuid.UUID
    course_id: uuid.UUID
    worker_id: int
    status: TrainingAssignmentStatus
    assigned_at: datetime
    due_at: datetime | None = None
    completed_at: datetime | None = None
    score: int | None = None
    assigned_by_user_id: uuid.UUID | None = None
    course_title: str | None = None
    worker_name: str | None = None


class TrainingAssignmentListResponse(BaseModel):
    items: list[TrainingAssignmentResponse]
    total: int
