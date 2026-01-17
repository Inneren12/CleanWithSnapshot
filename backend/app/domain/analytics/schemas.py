from datetime import datetime

from pydantic import BaseModel


class ConversionMetrics(BaseModel):
    lead_created: int
    booking_created: int
    booking_confirmed: int
    job_completed: int


class RevenueMetrics(BaseModel):
    average_estimated_revenue_cents: float | None


class DurationAccuracy(BaseModel):
    sample_size: int
    average_estimated_duration_minutes: float | None
    average_actual_duration_minutes: float | None
    average_delta_minutes: float | None


class FinancialKpis(BaseModel):
    total_revenue_cents: int
    revenue_per_day_cents: float
    margin_cents: int
    average_order_value_cents: float | None


class OperationalKpis(BaseModel):
    crew_utilization: float | None
    cancellation_rate: float
    retention_30_day: float
    retention_60_day: float
    retention_90_day: float


class FunnelCounts(BaseModel):
    inquiries: int
    quotes: int
    bookings_created: int
    bookings_completed: int
    reviews: int


class FunnelConversionRates(BaseModel):
    inquiry_to_quote: float
    quote_to_booking: float
    booking_to_completed: float
    completed_to_review: float


class FunnelLossReasonSummary(BaseModel):
    reason: str
    count: int


class FunnelAnalyticsResponse(BaseModel):
    range_start: datetime
    range_end: datetime
    counts: FunnelCounts
    conversion_rates: FunnelConversionRates
    loss_reasons: list[FunnelLossReasonSummary]


class NpsDistribution(BaseModel):
    total_responses: int
    average_score: float | None
    promoters: int
    passives: int
    detractors: int
    promoter_rate: float
    passive_rate: float
    detractor_rate: float


class NpsTrendPoint(BaseModel):
    period_start: datetime
    average_score: float | None
    response_count: int


class NpsTrends(BaseModel):
    weekly: list[NpsTrendPoint]
    monthly: list[NpsTrendPoint]


class NpsAnalyticsResponse(BaseModel):
    range_start: datetime
    range_end: datetime
    distribution: NpsDistribution
    trends: NpsTrends


class CohortBreakdown(BaseModel):
    cohort_month: datetime
    customers: int
    repeat_customers: int
    repeat_rate: float


class CohortAnalyticsResponse(BaseModel):
    range_start: datetime
    range_end: datetime
    cohorts: list[CohortBreakdown]


class GeoAreaSummary(BaseModel):
    area: str
    bookings: int
    revenue_cents: int
    avg_ticket_cents: int | None


class GeoPointSummary(BaseModel):
    lat: float
    lng: float
    count: int


class GeoAnalyticsResponse(BaseModel):
    by_area: list[GeoAreaSummary]
    points: list[GeoPointSummary] | None = None


class ClientClvEntry(BaseModel):
    client_id: str
    name: str | None
    email: str | None
    total_paid_cents: int
    payments_count: int
    first_payment_at: datetime | None
    last_payment_at: datetime | None


class ClientClvResponse(BaseModel):
    range_start: datetime
    range_end: datetime
    average_clv_cents: float | None
    median_clv_cents: float | None
    top_clients: list[ClientClvEntry]


class ClientRetentionCohort(BaseModel):
    cohort_month: datetime
    customers: int
    retention: list[float | None]


class ClientRetentionResponse(BaseModel):
    cohort: str
    months: int
    cohorts: list[ClientRetentionCohort]


class AdminMetricsResponse(BaseModel):
    range_start: datetime
    range_end: datetime
    conversions: ConversionMetrics
    revenue: RevenueMetrics
    accuracy: DurationAccuracy
    financial: FinancialKpis
    operational: OperationalKpis


class FinancialSummaryResponse(BaseModel):
    ready: bool
    reason: str | None = None
    revenue_cents: int | None = None
    expenses_cents: int | None = None
    profit_cents: int | None = None
    margin_pp: float | None = None
    gst_owed_cents: int | None = None
