import math
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.analytics.db_models import EventLog
from app.domain.bookings.db_models import Booking, Team
from app.domain.leads.db_models import Lead, LeadQuote, LeadTouchpoint
from app.domain.leads import attribution as attribution_service
from app.domain.leads import statuses as lead_statuses
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.nps.db_models import NpsResponse
from app.domain.nps.db_models import NpsResponse
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, Payment


class EventType(StrEnum):
    lead_created = "lead_created"
    booking_created = "booking_created"
    booking_confirmed = "booking_confirmed"
    job_completed = "job_completed"
    job_time_started = "job_time_started"
    job_time_paused = "job_time_paused"
    job_time_resumed = "job_time_resumed"
    job_time_finished = "job_time_finished"


def _normalize_dt(value: datetime | None, default: datetime | None = None) -> datetime:
    if value is None:
        if default is None:
            raise ValueError("default datetime is required when value is None")
        return default
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _month_start(value: datetime) -> datetime:
    normalized = _normalize_dt(value, default=datetime.now(tz=timezone.utc))
    return datetime(normalized.year, normalized.month, 1, tzinfo=timezone.utc)


def _month_index(value: datetime) -> int:
    return value.year * 12 + (value.month - 1)


def _shift_month(value: datetime, offset: int) -> datetime:
    index = _month_index(value) + offset
    year, month_offset = divmod(index, 12)
    return datetime(year, month_offset + 1, 1, tzinfo=timezone.utc)


async def log_event(
    session: AsyncSession,
    *,
    event_type: EventType,
    lead: Lead | None = None,
    booking: Booking | None = None,
    estimated_revenue_cents: int | None = None,
    estimated_duration_minutes: int | None = None,
    actual_duration_minutes: int | None = None,
    occurred_at: datetime | None = None,
) -> EventLog:
    timestamp = _normalize_dt(occurred_at, default=datetime.now(tz=timezone.utc))
    event = EventLog(
        event_type=event_type.value,
        lead_id=lead.lead_id if lead else None,
        booking_id=booking.booking_id if booking else None,
        estimated_revenue_cents=estimated_revenue_cents,
        estimated_duration_minutes=estimated_duration_minutes,
        actual_duration_minutes=actual_duration_minutes,
        utm_source=getattr(lead, "utm_source", None),
        utm_medium=getattr(lead, "utm_medium", None),
        utm_campaign=getattr(lead, "utm_campaign", None),
        utm_term=getattr(lead, "utm_term", None),
        utm_content=getattr(lead, "utm_content", None),
        referrer=getattr(lead, "referrer", None),
        occurred_at=timestamp,
    )
    session.add(event)
    await session.flush()
    return event


async def conversion_counts(
    session: AsyncSession, start: datetime, end: datetime, *, org_id: uuid.UUID
) -> dict[EventType, int]:
    stmt: Select = (
        select(EventLog.event_type, func.count())
        .outerjoin(Booking, Booking.booking_id == EventLog.booking_id)
        .outerjoin(Lead, Lead.lead_id == EventLog.lead_id)
        .where(
            EventLog.occurred_at >= start,
            EventLog.occurred_at <= end,
            sa.or_(Lead.org_id == org_id, Booking.org_id == org_id),
        )
        .group_by(EventLog.event_type)
    )
    result = await session.execute(stmt)
    counts_raw = defaultdict(int)
    for event_type, count in result.all():
        try:
            counts_raw[EventType(event_type)] = int(count)
        except ValueError:
            continue
    return counts_raw


async def average_revenue_cents(
    session: AsyncSession, start: datetime, end: datetime, *, org_id: uuid.UUID
) -> float | None:
    stmt = (
        select(func.avg(EventLog.estimated_revenue_cents))
        .outerjoin(Booking, Booking.booking_id == EventLog.booking_id)
        .outerjoin(Lead, Lead.lead_id == EventLog.lead_id)
        .where(
            EventLog.event_type.in_(
                [EventType.booking_confirmed.value, EventType.job_completed.value]
            ),
            EventLog.occurred_at >= start,
            EventLog.occurred_at <= end,
            EventLog.estimated_revenue_cents.isnot(None),
            sa.or_(Lead.org_id == org_id, Booking.org_id == org_id),
        )
    )
    result = await session.execute(stmt)
    avg_value = result.scalar_one_or_none()
    return float(avg_value) if avg_value is not None else None


async def duration_accuracy(
    session: AsyncSession, start: datetime, end: datetime, *, org_id: uuid.UUID
) -> tuple[float | None, float | None, float | None, int]:
    stmt = (
        select(Booking.duration_minutes, Booking.actual_duration_minutes)
        .join(EventLog, EventLog.booking_id == Booking.booking_id)
        .where(
            EventLog.event_type == EventType.job_completed.value,
            EventLog.occurred_at >= start,
            EventLog.occurred_at <= end,
            Booking.actual_duration_minutes.isnot(None),
            Booking.org_id == org_id,
        )
    )
    result = await session.execute(stmt)
    rows = result.all()
    if not rows:
        return None, None, None, 0

    estimated_values: list[int] = []
    actual_values: list[int] = []
    deltas: list[int] = []
    for estimated, actual in rows:
        if estimated is None or actual is None:
            continue
        estimated_values.append(int(estimated))
        actual_values.append(int(actual))
        deltas.append(int(actual) - int(estimated))

    if not estimated_values or not actual_values:
        return None, None, None, 0

    avg_estimated = sum(estimated_values) / len(estimated_values)
    avg_actual = sum(actual_values) / len(actual_values)
    avg_delta = sum(deltas) / len(deltas) if deltas else 0.0
    return (
        float(round(avg_estimated, 2)),
        float(round(avg_actual, 2)),
        float(round(avg_delta, 2)),
        len(actual_values),
    )


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _payment_timestamp_column() -> sa.ColumnElement:
    return func.coalesce(Payment.received_at, Payment.created_at)


def _bucket_start(column: sa.ColumnElement, period: str, bind) -> sa.ColumnElement:
    if bind and bind.dialect.name == "sqlite":
        if period == "week":
            return func.strftime("%Y-%W", column)
        return func.strftime("%Y-%m-01", column)
    return func.date_trunc(period, column)


def _normalize_area_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return " ".join(normalized.split())


def _booking_area_label(
    *, lead_area: str | None, address_label: str | None, team_zones: list[str] | None
) -> str | None:
    if lead_area:
        return lead_area
    if address_label:
        return address_label
    if team_zones:
        return team_zones[0] if team_zones else None
    return None


async def list_attribution_paths(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    *,
    org_id: uuid.UUID,
    limit: int,
) -> list[dict[str, object]]:
    stmt = (
        select(LeadTouchpoint)
        .where(
            LeadTouchpoint.org_id == org_id,
            LeadTouchpoint.occurred_at >= start,
            LeadTouchpoint.occurred_at <= end,
        )
        .order_by(
            LeadTouchpoint.lead_id.asc(),
            LeadTouchpoint.occurred_at.asc(),
            LeadTouchpoint.touchpoint_id.asc(),
        )
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    by_lead: dict[str, list[LeadTouchpoint]] = defaultdict(list)
    for touchpoint in rows:
        by_lead[touchpoint.lead_id].append(touchpoint)

    path_counts: Counter[str] = Counter()
    for touchpoints in by_lead.values():
        path = attribution_service.build_path(touchpoints)
        if not path:
            continue
        path_counts[path] += 1

    items = [
        {"path": path, "lead_count": count}
        for path, count in path_counts.most_common(limit)
    ]
    return items


async def geo_area_analytics(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    *,
    org_id: uuid.UUID,
) -> tuple[list[dict[str, object]], list[dict[str, object]] | None]:
    revenue_expr = Booking.base_charge_cents - Booking.refund_total_cents - Booking.credit_note_total_cents
    stmt = (
        select(
            Booking.booking_id,
            revenue_expr.label("revenue_cents"),
            Booking.team_id,
            ClientAddress.label.label("address_label"),
            ClientAddress.lat,
            ClientAddress.lng,
        )
        .select_from(Booking)
        .join(ClientAddress, Booking.address_id == ClientAddress.address_id, isouter=True)
        .where(
            Booking.starts_at >= start,
            Booking.starts_at <= end,
            Booking.org_id == org_id,
            sa.or_(ClientAddress.org_id == org_id, ClientAddress.address_id.is_(None)),
        )
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return [], None

    team_ids = {row.team_id for row in rows if row.team_id is not None}
    zones_by_team: dict[int, list[str]] = {}
    if team_ids:
        team_rows = await session.execute(
            select(Team.team_id, Team.zones).where(Team.team_id.in_(team_ids), Team.org_id == org_id)
        )
        for team_id, zones in team_rows.all():
            if team_id is None:
                continue
            zones_by_team[int(team_id)] = list(zones or [])

    bucket_counts: Counter[str] = Counter()
    revenue_totals: defaultdict[str, int] = defaultdict(int)
    points_counter: Counter[tuple[float, float]] = Counter()
    for row in rows:
        address_label = _normalize_area_label(row.address_label)
        area = _normalize_area_label(
            _booking_area_label(
                lead_area=None,
                address_label=address_label,
                team_zones=zones_by_team.get(row.team_id),
            )
        )
        if not area:
            continue
        bucket_counts[area] += 1
        revenue_totals[area] += int(row.revenue_cents or 0)
        if row.lat is not None and row.lng is not None:
            points_counter[(float(row.lat), float(row.lng))] += 1

    by_area = []
    for area, count in sorted(bucket_counts.items(), key=lambda item: (-item[1], item[0])):
        revenue_total = revenue_totals.get(area, 0)
        avg_ticket = int(round(revenue_total / count)) if count > 0 else None
        by_area.append(
            {
                "area": area,
                "bookings": count,
                "revenue_cents": revenue_total,
                "avg_ticket_cents": avg_ticket,
            }
        )

    points = None
    if points_counter:
        points = [
            {"lat": lat, "lng": lng, "count": count}
            for (lat, lng), count in sorted(
                points_counter.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
            )
        ]

    return by_area, points


async def client_clv_summary(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    *,
    org_id: uuid.UUID,
    top: int,
) -> tuple[float | None, float | None, list[dict[str, object]]]:
    payment_time = _payment_timestamp_column()
    stmt = (
        select(
            ClientUser.client_id,
            ClientUser.name,
            ClientUser.email,
            func.coalesce(func.sum(Payment.amount_cents), 0).label("total_paid_cents"),
            func.count(Payment.payment_id).label("payments_count"),
            func.min(payment_time).label("first_payment_at"),
            func.max(payment_time).label("last_payment_at"),
        )
        .select_from(Payment)
        .join(Invoice, Payment.invoice_id == Invoice.invoice_id, isouter=True)
        .join(
            Booking,
            sa.or_(
                Payment.booking_id == Booking.booking_id,
                Invoice.order_id == Booking.booking_id,
            ),
        )
        .join(ClientUser, ClientUser.client_id == Booking.client_id)
        .where(
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            Payment.org_id == org_id,
            Booking.org_id == org_id,
            ClientUser.org_id == org_id,
            payment_time >= start,
            payment_time <= end,
        )
        .group_by(ClientUser.client_id, ClientUser.name, ClientUser.email)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None, None, []

    entries: list[dict[str, object]] = []
    totals: list[int] = []
    for row in rows:
        total_paid = int(row.total_paid_cents or 0)
        totals.append(total_paid)
        entries.append(
            {
                "client_id": row.client_id,
                "name": row.name,
                "email": row.email,
                "total_paid_cents": total_paid,
                "payments_count": int(row.payments_count or 0),
                "first_payment_at": row.first_payment_at,
                "last_payment_at": row.last_payment_at,
            }
        )

    totals_sorted = sorted(totals)
    count = len(totals_sorted)
    avg_value = round(sum(totals_sorted) / count, 2) if count else None
    if count == 0:
        median_value = None
    elif count % 2 == 1:
        median_value = float(totals_sorted[count // 2])
    else:
        median_value = round(
            (totals_sorted[count // 2 - 1] + totals_sorted[count // 2]) / 2, 2
        )

    top_entries = sorted(
        entries, key=lambda entry: (-int(entry["total_paid_cents"]), str(entry["client_id"]))
    )[: max(top, 0)]
    return avg_value, median_value, top_entries


async def client_retention_cohorts(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    months: int,
    cohort: str,
) -> list[dict[str, object]]:
    if cohort != "monthly":
        raise ValueError("Unsupported cohort type")
    if months <= 0:
        return []

    payment_time = _payment_timestamp_column()
    stmt = (
        select(
            Booking.client_id,
            payment_time.label("paid_at"),
        )
        .select_from(Payment)
        .join(Invoice, Payment.invoice_id == Invoice.invoice_id, isouter=True)
        .join(
            Booking,
            sa.or_(
                Payment.booking_id == Booking.booking_id,
                Invoice.order_id == Booking.booking_id,
            ),
        )
        .where(
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            Payment.org_id == org_id,
            Booking.org_id == org_id,
            Booking.client_id.isnot(None),
        )
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []

    client_months: dict[str, set[datetime]] = defaultdict(set)
    for client_id, paid_at in rows:
        if client_id is None or paid_at is None:
            continue
        month_bucket = _month_start(paid_at)
        client_months[str(client_id)].add(month_bucket)

    if not client_months:
        return []

    first_month_by_client = {
        client_id: min(months_set) for client_id, months_set in client_months.items()
    }
    latest_month = max(
        month for months_set in client_months.values() for month in months_set
    )
    cohort_months = [
        _shift_month(latest_month, offset)
        for offset in range(-(months - 1), 1)
    ]

    cohorts: list[dict[str, object]] = []
    for cohort_month in cohort_months:
        cohort_clients = [
            client_id
            for client_id, first_month in first_month_by_client.items()
            if first_month == cohort_month
        ]
        cohort_size = len(cohort_clients)
        if cohort_size == 0:
            continue
        retention: list[float | None] = []
        for offset in range(months):
            target_month = _shift_month(cohort_month, offset)
            if target_month > latest_month:
                retention.append(None)
                continue
            retained = sum(
                1
                for client_id in cohort_clients
                if target_month in client_months.get(client_id, set())
            )
            retention.append(_safe_rate(retained, cohort_size))
        cohorts.append(
            {
                "cohort_month": cohort_month,
                "customers": cohort_size,
                "retention": retention,
            }
        )

    return cohorts


async def funnel_summary(
    session: AsyncSession, start: datetime, end: datetime, *, org_id: uuid.UUID
) -> dict[str, int]:
    inquiry_stmt = select(func.count()).select_from(Lead).where(
        Lead.org_id == org_id, Lead.created_at >= start, Lead.created_at <= end
    )
    quote_stmt = select(func.count()).select_from(LeadQuote).where(
        LeadQuote.org_id == org_id,
        LeadQuote.created_at >= start,
        LeadQuote.created_at <= end,
    )
    booking_stmt = select(func.count()).select_from(Booking).where(
        Booking.org_id == org_id,
        Booking.created_at >= start,
        Booking.created_at <= end,
    )
    completed_stmt = select(func.count()).select_from(Booking).where(
        Booking.org_id == org_id,
        Booking.status == "DONE",
        Booking.updated_at >= start,
        Booking.updated_at <= end,
    )
    review_stmt = (
        select(func.count())
        .select_from(NpsResponse)
        .where(
            NpsResponse.org_id == org_id,
            NpsResponse.created_at >= start,
            NpsResponse.created_at <= end,
        )
    )

    inquiry_count = int((await session.execute(inquiry_stmt)).scalar_one())
    quote_count = int((await session.execute(quote_stmt)).scalar_one())
    booking_count = int((await session.execute(booking_stmt)).scalar_one())
    completed_count = int((await session.execute(completed_stmt)).scalar_one())
    review_count = int((await session.execute(review_stmt)).scalar_one())

    return {
        "inquiries": inquiry_count,
        "quotes": quote_count,
        "bookings_created": booking_count,
        "bookings_completed": completed_count,
        "reviews": review_count,
    }


async def funnel_loss_reasons(
    session: AsyncSession, start: datetime, end: datetime, *, org_id: uuid.UUID
) -> list[dict[str, int | str]]:
    trimmed_reason = func.trim(Lead.loss_reason)
    stmt = (
        select(trimmed_reason, func.count())
        .select_from(Lead)
        .where(
            Lead.org_id == org_id,
            Lead.status == lead_statuses.LEAD_STATUS_LOST,
            Lead.updated_at >= start,
            Lead.updated_at <= end,
            Lead.loss_reason.isnot(None),
            trimmed_reason != "",
        )
        .group_by(trimmed_reason)
        .order_by(func.count().desc())
    )
    result = await session.execute(stmt)
    return [
        {"reason": str(reason), "count": int(count)}
        for reason, count in result.all()
        if reason is not None
    ]


async def nps_distribution(
    session: AsyncSession, start: datetime, end: datetime, *, org_id: uuid.UUID
) -> tuple[int, float | None, int, int, int]:
    stmt = (
        select(
            func.count(),
            func.avg(NpsResponse.score),
            func.sum(sa.case((NpsResponse.score >= 9, 1), else_=0)),
            func.sum(sa.case((NpsResponse.score.between(7, 8), 1), else_=0)),
            func.sum(sa.case((NpsResponse.score <= 6, 1), else_=0)),
        )
        .select_from(NpsResponse)
        .where(
            NpsResponse.org_id == org_id,
            NpsResponse.created_at >= start,
            NpsResponse.created_at <= end,
        )
    )
    result = await session.execute(stmt)
    total, avg_score, promoters, passives, detractors = result.one()
    return (
        int(total or 0),
        float(avg_score) if avg_score is not None else None,
        int(promoters or 0),
        int(passives or 0),
        int(detractors or 0),
    )


async def nps_trends(
    session: AsyncSession, start: datetime, end: datetime, *, org_id: uuid.UUID
) -> dict[str, list[tuple[datetime, float | None, int]]]:
    bind = session.get_bind()
    weekly_bucket = _bucket_start(NpsResponse.created_at, "week", bind)
    monthly_bucket = _bucket_start(NpsResponse.created_at, "month", bind)

    def _parse_bucket(value: str | datetime) -> datetime:
        if isinstance(value, datetime):
            normalized = value
        else:
            raw = str(value)
            try:
                normalized = datetime.fromisoformat(raw)
            except ValueError:
                normalized = datetime.strptime(f"{raw}-1", "%Y-%W-%w")
        if normalized.tzinfo is None:
            return normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc)

    weekly_stmt = (
        select(
            weekly_bucket.label("bucket"),
            func.avg(NpsResponse.score),
            func.count(),
        )
        .select_from(NpsResponse)
        .where(
            NpsResponse.org_id == org_id,
            NpsResponse.created_at >= start,
            NpsResponse.created_at <= end,
        )
        .group_by("bucket")
        .order_by("bucket")
    )

    monthly_stmt = (
        select(
            monthly_bucket.label("bucket"),
            func.avg(NpsResponse.score),
            func.count(),
        )
        .select_from(NpsResponse)
        .where(
            NpsResponse.org_id == org_id,
            NpsResponse.created_at >= start,
            NpsResponse.created_at <= end,
        )
        .group_by("bucket")
        .order_by("bucket")
    )

    weekly_rows = (await session.execute(weekly_stmt)).all()
    monthly_rows = (await session.execute(monthly_stmt)).all()

    weekly = [
        (_parse_bucket(bucket), float(avg) if avg is not None else None, int(count))
        for bucket, avg, count in weekly_rows
    ]
    monthly = [
        (_parse_bucket(bucket), float(avg) if avg is not None else None, int(count))
        for bucket, avg, count in monthly_rows
    ]
    return {"weekly": weekly, "monthly": monthly}


async def cohort_repeat_rates(
    session: AsyncSession, start: datetime, end: datetime, *, org_id: uuid.UUID
) -> list[tuple[datetime, int, int]]:
    bind = session.get_bind()
    customer_key = sa.func.coalesce(Booking.client_id, Booking.lead_id)
    first_booking_subquery = (
        select(
            customer_key.label("customer_key"),
            func.min(Booking.created_at).label("first_created_at"),
            func.count().label("total_bookings"),
        )
        .where(Booking.org_id == org_id, customer_key.isnot(None))
        .group_by(customer_key)
    ).subquery()

    cohort_bucket = _bucket_start(first_booking_subquery.c.first_created_at, "month", bind)
    cohort_stmt = (
        select(
            cohort_bucket.label("cohort_month"),
            func.count().label("customers"),
            func.sum(sa.case((first_booking_subquery.c.total_bookings > 1, 1), else_=0)).label(
                "repeat_customers"
            ),
        )
        .where(
            first_booking_subquery.c.first_created_at >= start,
            first_booking_subquery.c.first_created_at <= end,
        )
        .group_by("cohort_month")
        .order_by("cohort_month")
    )

    rows = (await session.execute(cohort_stmt)).all()

    def _normalize_bucket(bucket: str | datetime) -> datetime:
        if isinstance(bucket, datetime):
            normalized = bucket
        else:
            normalized = datetime.fromisoformat(str(bucket))
        if normalized.tzinfo is None:
            return normalized.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc)

    return [
        (
            _normalize_bucket(bucket),
            int(customers or 0),
            int(repeat or 0),
        )
        for bucket, customers, repeat in rows
    ]


def estimated_revenue_from_lead(lead: Lead | None) -> int | None:
    if lead is None:
        return None
    snapshot = getattr(lead, "estimate_snapshot", None) or {}
    total_before_tax = snapshot.get("total_before_tax")
    if total_before_tax is None:
        return None
    try:
        return int(round(float(total_before_tax) * 100))
    except (TypeError, ValueError):
        return None


def estimated_duration_from_booking(booking: Booking | None) -> int | None:
    if booking is None:
        return None
    try:
        return int(math.ceil(float(booking.duration_minutes)))
    except (TypeError, ValueError):
        return None


def estimated_duration_from_lead(lead: Lead | None) -> int | None:
    if lead is None:
        return None
    snapshot = getattr(lead, "estimate_snapshot", None) or {}
    time_on_site_hours = snapshot.get("time_on_site_hours")
    if time_on_site_hours is None:
        return None
    try:
        return int(round(float(time_on_site_hours) * 60))
    except (TypeError, ValueError):
        return None


def _labor_cost_cents_expression(bind, lead_table: Lead) -> sa.ColumnElement:
    if bind and bind.dialect.name == "postgresql":
        labor_text = lead_table.estimate_snapshot["labor_cost"].as_string()
        is_numeric = labor_text.op("~")(r"^-?\d+(?:\.\d+)?$")
        labor_value = sa.case(
            (is_numeric, sa.cast(labor_text, sa.Numeric())),
            else_=0,
        )
    else:
        labor_text = func.json_extract(lead_table.estimate_snapshot, "$.labor_cost")
        json_type = func.json_type(lead_table.estimate_snapshot, "$.labor_cost")
        labor_value = sa.case(
            (json_type.in_(["integer", "real"]), sa.cast(labor_text, sa.Float)),
            else_=0,
        )
    return func.coalesce(labor_value * 100, 0)


def _day_diff_expression(bind, current: sa.ColumnElement, previous: sa.ColumnElement) -> sa.ColumnElement:
    if bind and bind.dialect.name == "postgresql":
        return func.extract("epoch", current - previous) / 86400.0
    return func.julianday(current) - func.julianday(previous)


async def kpi_aggregates(
    session: AsyncSession, start: datetime, end: datetime, *, org_id: uuid.UUID
) -> dict[str, object]:
    bind = session.get_bind()
    revenue_expr = Booking.base_charge_cents - Booking.refund_total_cents - Booking.credit_note_total_cents
    planned_minutes = func.coalesce(Booking.planned_minutes, Booking.duration_minutes)
    planned_seconds = planned_minutes * 60
    actual_seconds = func.coalesce(Booking.actual_seconds, Booking.actual_duration_minutes * 60, 0)
    labor_cents = _labor_cost_cents_expression(bind, Lead)

    aggregate_stmt = (
        select(
            func.count().label("total_bookings"),
            func.count().filter(Booking.status == "DONE").label("completed_bookings"),
            func.count().filter(Booking.status == "CANCELLED").label("cancelled_bookings"),
            func.sum(func.coalesce(revenue_expr, 0)).filter(Booking.status == "DONE").label("total_revenue_cents"),
            func.sum(func.coalesce(planned_seconds, 0)).filter(Booking.status == "DONE").label("planned_seconds"),
            func.sum(func.coalesce(actual_seconds, 0)).filter(Booking.status == "DONE").label("actual_seconds"),
            func.sum(func.coalesce(labor_cents, 0)).filter(Booking.status == "DONE").label("labor_cents"),
        )
        .select_from(Booking)
        .join(Lead, Booking.lead_id == Lead.lead_id, isouter=True)
        .where(
            Booking.starts_at >= start,
            Booking.starts_at <= end,
            Booking.org_id == org_id,
            sa.or_(Lead.org_id == org_id, Lead.lead_id.is_(None)),
        )
    )

    aggregate_row = await session.execute(aggregate_stmt)
    (
        total_bookings,
        completed_bookings,
        cancelled_bookings,
        total_revenue_cents,
        planned_seconds_total,
        actual_seconds_total,
        labor_cents_total,
    ) = aggregate_row.one()

    total_bookings = int(total_bookings or 0)
    completed_bookings = int(completed_bookings or 0)
    cancelled_bookings = int(cancelled_bookings or 0)
    total_revenue_cents = int(total_revenue_cents or 0)
    planned_seconds_total = float(planned_seconds_total or 0)
    actual_seconds_total = float(actual_seconds_total or 0)
    labor_cents_total = int(round(float(labor_cents_total or 0)))

    window = end - start
    day_span = max(1, math.ceil(window.total_seconds() / 86400))
    revenue_per_day = float(round(total_revenue_cents / day_span, 2))
    average_order_value = (
        float(round(total_revenue_cents / completed_bookings, 2))
        if completed_bookings > 0
        else None
    )
    margin_cents = total_revenue_cents - labor_cents_total
    crew_utilization = (
        round(actual_seconds_total / planned_seconds_total, 4)
        if planned_seconds_total > 0
        else None
    )
    cancellation_rate = (
        round(cancelled_bookings / total_bookings, 4) if total_bookings > 0 else 0.0
    )

    completed_subquery = (
        select(
            func.coalesce(Booking.client_id, Booking.lead_id).label("customer_id"),
            Booking.starts_at.label("starts_at"),
        )
        .where(Booking.status == "DONE", Booking.org_id == org_id)
        .subquery()
    )

    lagged = select(
        completed_subquery.c.customer_id,
        completed_subquery.c.starts_at.label("current_start"),
        func.lag(completed_subquery.c.starts_at)
        .over(
            partition_by=completed_subquery.c.customer_id,
            order_by=completed_subquery.c.starts_at,
        )
        .label("prev_start"),
    ).subquery()

    range_rows = select(lagged).where(
        lagged.c.current_start >= start,
        lagged.c.current_start <= end,
    )

    range_subquery = range_rows.subquery()
    day_diff = _day_diff_expression(bind, range_subquery.c.current_start, range_subquery.c.prev_start)

    base_customers_stmt = select(
        func.count(sa.distinct(completed_subquery.c.customer_id))
    ).where(completed_subquery.c.starts_at >= start, completed_subquery.c.starts_at <= end)

    retention_stmt = select(
        func.count(sa.distinct(range_subquery.c.customer_id)).filter(
            range_subquery.c.prev_start.isnot(None)
        ).label("customers_with_history"),
        func.count(sa.distinct(range_subquery.c.customer_id)).filter(
            sa.and_(range_subquery.c.prev_start.isnot(None), day_diff <= 30)
        ).label("retained_30"),
        func.count(sa.distinct(range_subquery.c.customer_id)).filter(
            sa.and_(range_subquery.c.prev_start.isnot(None), day_diff <= 60)
        ).label("retained_60"),
        func.count(sa.distinct(range_subquery.c.customer_id)).filter(
            sa.and_(range_subquery.c.prev_start.isnot(None), day_diff <= 90)
        ).label("retained_90"),
    )

    customers_result = await session.execute(base_customers_stmt)
    customers_in_range = int(customers_result.scalar_one() or 0)

    retention_result = await session.execute(retention_stmt)
    customers_with_history, retained_30, retained_60, retained_90 = retention_result.one()

    def _rate(value: int) -> float:
        if customers_in_range == 0:
            return 0.0
        return round((value or 0) / customers_in_range, 4)

    return {
        "financial": {
            "total_revenue_cents": total_revenue_cents,
            "revenue_per_day_cents": revenue_per_day,
            "margin_cents": margin_cents,
            "average_order_value_cents": average_order_value,
        },
        "operational": {
            "crew_utilization": crew_utilization,
            "cancellation_rate": cancellation_rate,
            "retention_30_day": _rate(int(retained_30 or 0)),
            "retention_60_day": _rate(int(retained_60 or 0)),
            "retention_90_day": _rate(int(retained_90 or 0)),
        },
    }
