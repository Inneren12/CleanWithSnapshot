from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DISPATCHER_STATUS_VALUES = {"PLANNED", "IN_PROGRESS", "DONE", "CANCELLED"}


class DispatcherBoardClient(BaseModel):
    id: str | None
    name: str | None
    phone: str | None = None


class DispatcherBoardAddress(BaseModel):
    id: int | None
    formatted: str | None
    lat: float | None = None
    lng: float | None = None
    zone: str | None = None


class DispatcherBoardWorker(BaseModel):
    id: int | None
    display_name: str | None
    phone: str | None = None


class DispatcherBoardBooking(BaseModel):
    booking_id: str
    status: str
    starts_at: datetime
    ends_at: datetime
    duration_min: int
    client: DispatcherBoardClient
    address: DispatcherBoardAddress
    assigned_worker: DispatcherBoardWorker | None = None
    team_id: int | None
    updated_at: datetime


class DispatcherBoardWorkerSummary(BaseModel):
    worker_id: int
    display_name: str


class DispatcherBoardResponse(BaseModel):
    bookings: list[DispatcherBoardBooking] = Field(default_factory=list)
    workers: list[DispatcherBoardWorkerSummary] = Field(default_factory=list)
    server_time: datetime
    data_version: int


class DispatcherAlert(BaseModel):
    alert_id: str
    type: Literal["DOUBLE_BOOKING", "LATE_WORKER", "CLIENT_CANCELLED_TODAY", "WORKER_SHORTAGE"]
    severity: Literal["info", "warn", "critical"]
    message: str
    action: str
    booking_ids: list[str] = Field(default_factory=list)
    worker_ids: list[int] = Field(default_factory=list)


class DispatcherAlertsResponse(BaseModel):
    alerts: list[DispatcherAlert] = Field(default_factory=list)


class DispatcherAlertAckRequest(BaseModel):
    alert_id: str = Field(min_length=3)


class DispatcherAlertAckResponse(BaseModel):
    status: Literal["ok"]


class DispatcherStatsResponse(BaseModel):
    done_count: int
    in_progress_count: int
    planned_count: int
    avg_duration_hours: float | None = None
    revenue_today: int


class DispatcherRoutePoint(BaseModel):
    lat: float
    lng: float


class DispatcherRouteEstimateRequest(BaseModel):
    origin: DispatcherRoutePoint
    dest: DispatcherRoutePoint
    depart_at: datetime | None = None
    mode: Literal["driving"] = "driving"


class DispatcherRouteEstimateResponse(BaseModel):
    distance_km: float
    duration_min: int
    duration_in_traffic_min: int | None = None
    provider: Literal["google", "heuristic"]
    cached: bool


class DispatcherSuggestionScoreParts(BaseModel):
    availability: float
    distance: float
    skill: float
    rating: float
    workload: float


class DispatcherAssignmentSuggestion(BaseModel):
    worker_id: int
    display_name: str | None
    score_total: float
    score_parts: DispatcherSuggestionScoreParts
    eta_min: int | None = None
    reasons: list[str] = Field(default_factory=list)


class DispatcherAssignmentSuggestionsResponse(BaseModel):
    suggestions: list[DispatcherAssignmentSuggestion] = Field(default_factory=list)


class DispatcherReassignRequest(BaseModel):
    worker_id: int = Field(gt=0)


class DispatcherRescheduleRequest(BaseModel):
    starts_at: datetime
    ends_at: datetime
    override_conflicts: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> "DispatcherRescheduleRequest":
        if self.ends_at <= self.starts_at:
            raise ValueError("End time must be after start time")
        return self


class DispatcherStatusRequest(BaseModel):
    status: str
    reason: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        if value is None:
            raise ValueError("Status is required")
        normalized = str(value).strip().upper()
        if normalized not in DISPATCHER_STATUS_VALUES:
            raise ValueError("Status must be planned, in_progress, done, or cancelled")
        return normalized


class DispatcherNotifyRequest(BaseModel):
    booking_id: str
    target: Literal["client", "worker"]
    channel: Literal["sms", "call"]
    template_id: str
    params: dict[str, str] | None = None
    locale: Literal["en", "ru"] = "en"


class DispatcherNotifyResponse(BaseModel):
    audit_id: str
    status: Literal["sent", "failed"]
    error_code: str | None = None
    provider_msg_id: str | None = None
    sent_at: datetime


class DispatcherNotifyAuditEntry(BaseModel):
    audit_id: str
    booking_id: str
    target: Literal["client", "worker"]
    channel: Literal["sms", "call"]
    template_id: str
    admin_user_id: str
    status: Literal["sent", "failed"]
    error_code: str | None = None
    provider_msg_id: str | None = None
    sent_at: datetime


class DispatcherNotifyAuditResponse(BaseModel):
    audits: list[DispatcherNotifyAuditEntry] = Field(default_factory=list)


class DispatcherWeatherNow(BaseModel):
    temp_c: float | None = None
    wind_kph: float | None = None
    precip_mm: float | None = None
    snow_cm: float | None = None
    summary: str | None = None


class DispatcherWeatherHour(BaseModel):
    starts_at: str
    precip_mm: float | None = None
    snow_cm: float | None = None


class DispatcherWeatherFlags(BaseModel):
    snow_risk: bool
    freezing_risk: bool


class DispatcherWeatherPayload(BaseModel):
    weather_now: DispatcherWeatherNow
    next_6h: list[DispatcherWeatherHour] = Field(default_factory=list)
    flags: DispatcherWeatherFlags


TrafficRiskLevel = Literal["low", "medium", "high"]


class DispatcherContextResponse(BaseModel):
    weather_now: DispatcherWeatherNow
    next_6h: list[DispatcherWeatherHour] = Field(default_factory=list)
    flags: DispatcherWeatherFlags
    traffic_risk: TrafficRiskLevel
