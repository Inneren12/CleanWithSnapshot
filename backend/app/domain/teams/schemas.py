from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TeamLeadSummary(BaseModel):
    worker_id: int
    name: str
    role: str | None = None
    rating_avg: float | None = None


class TeamListItem(BaseModel):
    team_id: int
    name: str
    created_at: datetime
    lead: TeamLeadSummary | None = None
    worker_count: int
    monthly_bookings: int
    monthly_revenue_cents: int
    rating_avg: float | None = None
    rating_count: int

    model_config = ConfigDict(from_attributes=True)


class TeamDetailResponse(BaseModel):
    team_id: int
    name: str
    created_at: datetime
    archived_at: datetime | None = None
    lead: TeamLeadSummary | None = None
    worker_count: int
    monthly_bookings: int
    monthly_revenue_cents: int
    rating_avg: float | None = None
    rating_count: int


class TeamMemberSummary(BaseModel):
    worker_id: int
    name: str
    role: str | None = None
    phone: str
    email: str | None = None
    rating_avg: float | None = None
    rating_count: int
    is_active: bool


class TeamMembersResponse(BaseModel):
    team_id: int
    members: list[TeamMemberSummary]


class TeamRecentBooking(BaseModel):
    booking_id: str
    starts_at: datetime
    duration_minutes: int
    status: str
    lead_name: str | None = None
    lead_email: str | None = None


class TeamRecentBookingsResponse(BaseModel):
    team_id: int
    bookings: list[TeamRecentBooking]


class TeamMetricsResponse(BaseModel):
    team_id: int
    range_start: datetime
    range_end: datetime
    bookings_count: int
    completed_count: int
    cancelled_count: int
    total_revenue_cents: int
    average_rating: float | None = None
