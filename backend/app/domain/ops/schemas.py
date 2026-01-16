from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class JobStatusResponse(BaseModel):
    name: str
    last_heartbeat: Optional[datetime] = None
    runner_id: Optional[str] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    consecutive_failures: int


class QuickActionModel(BaseModel):
    label: str
    target: str
    method: str = "GET"


class GlobalSearchResult(BaseModel):
    kind: str
    ref: str
    label: str
    status: str | None = None
    created_at: datetime
    relevance_score: int = 0
    quick_actions: list[QuickActionModel] = []
    model_config = ConfigDict(from_attributes=True)


class ScheduleBooking(BaseModel):
    booking_id: str
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    status: str
    worker_id: int | None = None
    worker_name: str | None = None
    team_id: int
    team_name: str | None = None
    client_label: str | None = None
    address: str | None = None
    service_label: str | None = None
    price_cents: int | None = None
    notes: str | None = None
    model_config = ConfigDict(from_attributes=True)


class ScheduleBlackout(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: str | None = None
    model_config = ConfigDict(from_attributes=True)


class ScheduleResponse(BaseModel):
    from_date: date
    to_date: date
    bookings: list[ScheduleBooking]
    total: int | None = None
    limit: int | None = None
    offset: int | None = None
    query: str | None = None
    model_config = ConfigDict(from_attributes=True)


class WorkerTimelineTotals(BaseModel):
    booked_minutes: int
    booking_count: int
    revenue_cents: int


class WorkerTimelineDay(BaseModel):
    date: date
    booked_minutes: int
    booking_count: int
    revenue_cents: int
    booking_ids: list[str] = Field(default_factory=list)


class WorkerTimelineWorker(BaseModel):
    worker_id: int
    name: str
    team_id: int | None = None
    team_name: str | None = None
    days: list[WorkerTimelineDay] = Field(default_factory=list)
    totals: WorkerTimelineTotals


class WorkerTimelineResponse(BaseModel):
    from_date: date
    to_date: date
    org_timezone: str
    days: list[date] = Field(default_factory=list)
    workers: list[WorkerTimelineWorker] = Field(default_factory=list)
    totals: WorkerTimelineTotals
    model_config = ConfigDict(from_attributes=True)


class TeamCalendarDay(BaseModel):
    date: date
    bookings: int
    revenue: int
    workers_used: int


class TeamCalendarTeam(BaseModel):
    team_id: int
    name: str
    days: list[TeamCalendarDay] = Field(default_factory=list)


class TeamCalendarResponse(BaseModel):
    from_date: date
    to_date: date
    org_timezone: str
    days: list[date] = Field(default_factory=list)
    teams: list[TeamCalendarTeam] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class OpsDashboardAlertAction(BaseModel):
    label: str
    href: str
    method: str = "GET"


class OpsDashboardAlert(BaseModel):
    type: str
    severity: str
    title: str
    description: str
    entity_ref: dict[str, object] | None = None
    actions: list[OpsDashboardAlertAction] = Field(default_factory=list)
    created_at: datetime | None = None


class OpsDashboardUpcomingEvent(BaseModel):
    starts_at: datetime
    title: str
    entity_ref: dict[str, object] | None = None
    actions: list[OpsDashboardAlertAction] = Field(default_factory=list)


class ActivityFeedAction(BaseModel):
    label: str
    href: str


class ActivityFeedItem(BaseModel):
    event_id: str
    kind: str
    title: str
    description: str | None = None
    timestamp: datetime
    entity_ref: dict[str, object] | None = None
    action: ActivityFeedAction | None = None


class ActivityFeedResponse(BaseModel):
    as_of: datetime
    items: list[ActivityFeedItem] = Field(default_factory=list)


class OpsDashboardWorkerAvailability(BaseModel):
    worker_id: int
    name: str | None = None
    available: bool
    next_available_at: datetime | None = None


class OpsDashboardBookingStatusTotals(BaseModel):
    total: int
    pending: int
    confirmed: int
    done: int
    cancelled: int


class OpsDashboardBookingStatusBand(BaseModel):
    label: str
    count: int


class OpsDashboardBookingStatusToday(BaseModel):
    totals: OpsDashboardBookingStatusTotals
    bands: list[OpsDashboardBookingStatusBand] = Field(default_factory=list)


class OpsDashboardHeroMetrics(BaseModel):
    bookings_today: int
    revenue_today_cents: int
    workers_available: int
    workers_total: int
    worker_rating_avg: float | None = None


class OpsDashboardRevenueDay(BaseModel):
    date: date
    revenue_cents: int


class OpsDashboardRevenueGoal(BaseModel):
    goal_cents: int
    remaining_cents: int


class OpsDashboardRevenueWeek(BaseModel):
    week_start: date
    week_end: date
    days: list[OpsDashboardRevenueDay] = Field(default_factory=list)
    total_revenue_cents: int
    currency: str
    goal: OpsDashboardRevenueGoal | None = None


class OpsDashboardQualityToday(BaseModel):
    avg_rating: float | None = None
    reviews_count: int
    open_critical_issues: int


class OpsDashboardTopWorker(BaseModel):
    worker_id: int
    name: str | None = None
    team_id: int | None = None
    team_name: str | None = None
    bookings_count: int
    revenue_cents: int


class OpsDashboardTopClient(BaseModel):
    client_id: str
    name: str | None = None
    email: EmailStr | None = None
    bookings_count: int
    revenue_cents: int


class OpsDashboardTopTeam(BaseModel):
    team_id: int
    name: str
    bookings_count: int
    revenue_cents: int


class OpsDashboardTopService(BaseModel):
    label: str
    bookings_count: int
    revenue_cents: int
    share_of_revenue: float


class OpsDashboardTopPerformers(BaseModel):
    month_start: date
    month_end: date
    total_revenue_cents: int
    workers: list[OpsDashboardTopWorker] = Field(default_factory=list)
    clients: list[OpsDashboardTopClient] = Field(default_factory=list)
    teams: list[OpsDashboardTopTeam] = Field(default_factory=list)
    services: list[OpsDashboardTopService] = Field(default_factory=list)


class OpsDashboardResponse(BaseModel):
    as_of: datetime
    org_timezone: str
    org_currency: str
    critical_alerts: list[OpsDashboardAlert] = Field(default_factory=list)
    upcoming_events: list[OpsDashboardUpcomingEvent] = Field(default_factory=list)
    worker_availability: list[OpsDashboardWorkerAvailability] = Field(default_factory=list)
    booking_status_today: OpsDashboardBookingStatusToday
    hero_metrics: OpsDashboardHeroMetrics
    revenue_week: OpsDashboardRevenueWeek
    quality_today: OpsDashboardQualityToday | None = None
    top_performers: OpsDashboardTopPerformers


class MoveBookingRequest(BaseModel):
    starts_at: datetime
    duration_minutes: int | None = None
    team_id: int | None = None


class BlockSlotRequest(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: str | None = None
    team_id: int | None = None


class SuggestedTeam(BaseModel):
    team_id: int
    name: str


class SuggestedWorker(BaseModel):
    worker_id: int
    name: str
    team_id: int
    team_name: str


class RankedWorkerSuggestion(BaseModel):
    worker_id: int
    name: str
    team_id: int
    team_name: str
    reasons: list[str] = Field(default_factory=list)


class ScheduleSuggestions(BaseModel):
    teams: list[SuggestedTeam]
    workers: list[SuggestedWorker]
    ranked_workers: list[RankedWorkerSuggestion] = Field(default_factory=list)


class QuickCreateClientInput(BaseModel):
    name: str
    email: EmailStr
    phone: str


class QuickCreateBookingRequest(BaseModel):
    starts_at: datetime
    duration_minutes: int = Field(gt=0)
    client_id: str | None = None
    client: QuickCreateClientInput | None = None
    address_id: int | None = None
    address_text: str | None = None
    address_label: str | None = None
    service_type_id: int | None = None
    addon_ids: list[int] = Field(default_factory=list)
    assigned_worker_id: int | None = None
    price_cents: int = Field(ge=0)
    deposit_cents: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_inputs(self) -> "QuickCreateBookingRequest":
        if not self.client_id and not self.client:
            raise ValueError("client_id or client is required")
        if not self.address_id and not self.address_text:
            raise ValueError("address_id or address_text is required")
        return self


class ConflictDetail(BaseModel):
    kind: str
    reference: str
    starts_at: datetime
    ends_at: datetime
    note: str | None = None


class ConflictCheckResponse(BaseModel):
    has_conflict: bool
    conflicts: list[ConflictDetail]


class BulkBookingsRequest(BaseModel):
    booking_ids: list[str]
    team_id: int | None = None
    status: str | None = None
    send_reminder: bool = False


class BulkBookingsResponse(BaseModel):
    updated: int
    reminders_sent: int


class TemplatePreviewRequest(BaseModel):
    template: str
    booking_id: str | None = None
    invoice_id: str | None = None
    lead_id: str | None = None


class TemplatePreviewResponse(BaseModel):
    template: str
    version: str
    subject: str
    body: str
