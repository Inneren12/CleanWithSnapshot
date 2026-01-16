from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class QualityIssueStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class QualityIssueSeverity(str, Enum):
    CRITICAL = "critical"
    MEDIUM = "medium"
    LOW = "low"


class QualityIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    booking_id: str | None = None
    worker_id: int | None = None
    client_id: str | None = None
    rating: int | None = None
    summary: str | None = None
    details: str | None = None
    status: QualityIssueStatus
    severity: QualityIssueSeverity
    created_at: datetime
    first_response_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_type: str | None = None
    resolution_value: str | None = None
    assignee_user_id: uuid.UUID | None = None


class QualityIssueListResponse(BaseModel):
    items: list[QualityIssueResponse]
    total: int


class QualityIssueTriageItem(BaseModel):
    id: uuid.UUID
    summary: str | None = None
    status: QualityIssueStatus
    severity: QualityIssueSeverity
    rating: int | None = None
    created_at: datetime
    booking_id: str | None = None
    worker_id: int | None = None
    client_id: str | None = None
    assignee_user_id: uuid.UUID | None = None


class QualityIssueTriageBucket(BaseModel):
    severity: QualityIssueSeverity
    total: int
    items: list[QualityIssueTriageItem]


class QualityIssueTriageResponse(BaseModel):
    as_of: datetime
    buckets: list[QualityIssueTriageBucket]
