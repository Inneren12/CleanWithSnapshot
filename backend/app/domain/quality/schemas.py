from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QualityIssueStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class QualityIssueSeverity(str, Enum):
    CRITICAL = "critical"
    MEDIUM = "medium"
    LOW = "low"


class QualityIssueResponseType(str, Enum):
    RESPONSE = "response"
    NOTE = "note"


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


class QualityIssueRelatedBooking(BaseModel):
    booking_id: str
    status: str
    starts_at: datetime | None = None
    team_id: int | None = None
    assigned_worker_id: int | None = None


class QualityIssueRelatedWorker(BaseModel):
    worker_id: int
    name: str
    phone: str | None = None
    email: str | None = None
    team_id: int | None = None


class QualityIssueRelatedClient(BaseModel):
    client_id: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    is_blocked: bool | None = None


class QualityIssueResponseLog(BaseModel):
    response_id: uuid.UUID
    response_type: QualityIssueResponseType
    message: str
    created_by: str | None = None
    created_at: datetime


class QualityIssueTag(BaseModel):
    tag_key: str
    label: str


class QualityIssueDetailResponse(BaseModel):
    issue: QualityIssueResponse
    booking: QualityIssueRelatedBooking | None = None
    worker: QualityIssueRelatedWorker | None = None
    client: QualityIssueRelatedClient | None = None
    responses: list[QualityIssueResponseLog]
    tags: list[QualityIssueTag]
    tag_catalog: list[QualityIssueTag]


class QualityIssueUpdateRequest(BaseModel):
    status: QualityIssueStatus | None = None
    resolution_type: str | None = None
    resolution_value: str | None = None
    assignee_user_id: uuid.UUID | None = None


class QualityIssueRespondRequest(BaseModel):
    response_type: QualityIssueResponseType = QualityIssueResponseType.RESPONSE
    message: str


class QualityIssueTagUpdateRequest(BaseModel):
    tag_keys: list[str]


class QualityIssueTagsResponse(BaseModel):
    issue_id: uuid.UUID
    tags: list[QualityIssueTag]


class QualityIssueListResponse(BaseModel):
    items: list[QualityIssueResponse]
    total: int


class PhotoEvidenceKind(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"

    @classmethod
    def from_any_case(cls, value: str) -> "PhotoEvidenceKind":
        try:
            return cls(value.upper())
        except Exception as exc:  # noqa: BLE001
            raise ValueError("kind must be BEFORE or AFTER") from exc


class BookingPhotoEvidenceCreateRequest(BaseModel):
    kind: PhotoEvidenceKind
    storage_key: str
    mime: str
    bytes: int = Field(..., ge=0)
    consent: bool
    uploaded_by: str | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind(cls, value: str | PhotoEvidenceKind) -> PhotoEvidenceKind:
        if isinstance(value, PhotoEvidenceKind):
            return value
        if value is None:
            raise ValueError("kind is required")
        return PhotoEvidenceKind.from_any_case(str(value))


class BookingPhotoEvidenceResponse(BaseModel):
    photo_id: str
    booking_id: str
    kind: PhotoEvidenceKind
    storage_key: str
    mime: str
    bytes: int
    consent: bool
    uploaded_by: str
    created_at: datetime


class QualityPhotoEvidenceItem(BookingPhotoEvidenceResponse):
    worker_id: int | None = None
    has_issue: bool


class QualityPhotoEvidenceListResponse(BaseModel):
    items: list[QualityPhotoEvidenceItem]
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


class QualityReviewTemplate(BaseModel):
    key: str
    label: str
    body: str


class QualityReviewItem(BaseModel):
    feedback_id: int
    booking_id: str
    booking_starts_at: datetime | None = None
    worker_id: int | None = None
    worker_name: str | None = None
    client_id: str
    client_name: str | None = None
    client_email: str | None = None
    rating: int
    comment: str | None = None
    created_at: datetime
    has_issue: bool


class QualityReviewListResponse(BaseModel):
    items: list[QualityReviewItem]
    total: int
    page: int
    page_size: int
    templates: list[QualityReviewTemplate]


class QualityReviewReplyRequest(BaseModel):
    template_key: str | None = None
    message: str | None = None


class QualityReviewReplyResponse(BaseModel):
    reply_id: uuid.UUID
    feedback_id: int
    template_key: str | None = None
    message: str
    created_by: str | None = None
    created_at: datetime


class RatingDistributionEntry(BaseModel):
    stars: int
    count: int


class RatingDistributionResponse(BaseModel):
    from_date: date
    to_date: date
    total: int
    average_rating: float | None = None
    distribution: list[RatingDistributionEntry]


class WorkerQualityTrend(BaseModel):
    previous_average_rating: float | None = None
    previous_review_count: int
    previous_complaint_count: int
    average_rating_delta: float | None = None
    review_count_delta: int
    complaint_count_delta: int


class WorkerQualityLeaderboardEntry(BaseModel):
    worker_id: int
    worker_name: str
    team_id: int | None = None
    team_name: str | None = None
    average_rating: float | None = None
    review_count: int
    complaint_count: int
    trend: WorkerQualityTrend | None = None


class WorkerQualityLeaderboardResponse(BaseModel):
    from_date: date
    to_date: date
    as_of: datetime
    workers: list[WorkerQualityLeaderboardEntry]


class CommonIssueWorker(BaseModel):
    worker_id: int
    worker_name: str | None = None
    issue_count: int


class CommonIssueTagEntry(BaseModel):
    tag_key: str
    label: str
    issue_count: int
    worker_count: int
    workers: list[CommonIssueWorker]


class CommonIssueTagsResponse(BaseModel):
    from_date: date
    to_date: date
    as_of: datetime
    tags: list[CommonIssueTagEntry]


class ServiceQualityBreakdownEntry(BaseModel):
    service_label: str
    average_rating: float | None = None
    review_count: int
    complaint_count: int


class ServiceQualityBreakdownResponse(BaseModel):
    from_date: date
    to_date: date
    as_of: datetime
    services: list[ServiceQualityBreakdownEntry]


class QualitySummaryReview(BaseModel):
    feedback_id: int
    booking_id: str
    rating: int
    comment: str | None = None
    created_at: datetime
    worker_id: int | None = None
    worker_name: str | None = None
    client_id: str | None = None
    client_name: str | None = None


class WorkerQualitySummaryResponse(BaseModel):
    worker_id: int
    average_rating: float | None = None
    review_count: int
    complaint_count: int
    last_review: QualitySummaryReview | None = None


class ClientQualitySummaryResponse(BaseModel):
    client_id: str
    average_rating: float | None = None
    review_count: int
    complaint_count: int
    last_review: QualitySummaryReview | None = None
