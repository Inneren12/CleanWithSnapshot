from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_audit import service as audit_service
from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import BLOCKING_STATUSES
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.dispatcher.db_models import DispatcherCommunicationAudit
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, Payment
from app.domain.dispatcher import alert_state_store, schemas
from app.domain.dispatcher import route_estimates
from app.domain.leads.db_models import Lead
from app.domain.notifications.email_service import LOCAL_TZ
from app.domain.ops import service as ops_service
from app.domain.workers.db_models import Worker
from app.infra.communication import CommunicationResult, NoopCommunicationAdapter, TwilioCommunicationAdapter
from app.settings import settings

logger = logging.getLogger(__name__)

_DISPATCHER_ALERT_ACK_TTL = timedelta(minutes=30)
_DISPATCHER_ALERT_SMS_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class DispatcherBoardResult:
    bookings: list[schemas.DispatcherBoardBooking]
    workers: list[schemas.DispatcherBoardWorkerSummary]
    server_time: datetime
    data_version: int


@dataclass(frozen=True)
class DispatcherAlertsResult:
    alerts: list[schemas.DispatcherAlert]


@dataclass(frozen=True)
class DispatcherStatsResult:
    done_count: int
    in_progress_count: int
    planned_count: int
    avg_duration_hours: float | None
    revenue_today_cents: int


@dataclass(frozen=True)
class DispatcherAssignmentSuggestionsResult:
    suggestions: list[schemas.DispatcherAssignmentSuggestion]


@dataclass(frozen=True)
class _ZoneBox:
    name: str
    lat_min: float
    lat_max: float
    lng_min: float
    lng_max: float


_ZONE_BOXES: list[_ZoneBox] = [
    _ZoneBox("Downtown", 53.53, 53.57, -113.53, -113.47),
    _ZoneBox("Whyte/Old Strathcona", 53.50, 53.53, -113.55, -113.48),
    _ZoneBox("West", 53.50, 53.60, -113.68, -113.54),
    _ZoneBox("South/Millwoods", 53.44, 53.52, -113.58, -113.44),
    _ZoneBox("North/Castle Downs", 53.58, 53.68, -113.56, -113.42),
    _ZoneBox("St. Albert", 53.60, 53.70, -113.72, -113.58),
]
# Zone boxes can overlap; zone_for_point resolves by this order and filters follow the label.

_ZONE_LOOKUP = {zone.name.lower(): zone for zone in _ZONE_BOXES}
_ZONE_ALIASES = {
    "whyte": "whyte/old strathcona",
    "old strathcona": "whyte/old strathcona",
    "st albert": "st. albert",
}
_RIVER_VALLEY_BOXES = [
    _ZoneBox("River Valley Access", 53.47, 53.58, -113.62, -113.42),
    _ZoneBox("River Valley Southwest", 53.44, 53.50, -113.62, -113.50),
]

_DEFAULT_TZ = ZoneInfo("America/Edmonton")

SUGGEST_DISTANCE_WEIGHT = 0.45
SUGGEST_SKILL_WEIGHT = 0.2
SUGGEST_RATING_WEIGHT = 0.2
SUGGEST_WORKLOAD_WEIGHT = 0.15
SUGGEST_DISTANCE_MAX_MIN = 60
SUGGEST_CLOSEST_THRESHOLD_MIN = 20
SUGGEST_HIGH_RATING_THRESHOLD = 0.8
SUGGEST_LIGHT_WORKLOAD_THRESHOLD = 0.7


def resolve_zone(zone: str | None) -> _ZoneBox | None:
    if not zone:
        return None
    normalized = zone.strip().lower()
    normalized = _ZONE_ALIASES.get(normalized, normalized)
    match = _ZONE_LOOKUP.get(normalized)
    if not match:
        raise ValueError("unknown_zone")
    return match


def zone_for_point(lat: float | None, lng: float | None) -> str | None:
    if lat is None or lng is None:
        return None
    for zone in _ZONE_BOXES:
        if zone.lat_min <= lat <= zone.lat_max and zone.lng_min <= lng <= zone.lng_max:
            return zone.name
    return None


def _matches_zone(lat: float | None, lng: float | None, zone: _ZoneBox | None) -> bool:
    if zone is None:
        return True
    return zone_for_point(lat, lng) == zone.name


def _apply_zone_filter(
    rows: list[tuple[str, float | None, float | None]],
    zone: _ZoneBox | None,
) -> list[tuple[str, float | None, float | None]]:
    if zone is None:
        return list(rows)
    filtered: list[tuple[str, float | None, float | None]] = []
    for booking_id, lat, lng in rows:
        if _matches_zone(lat, lng, zone):
            filtered.append((booking_id, lat, lng))
    return filtered


async def _zone_filtered_booking_ids(
    session: AsyncSession,
    *,
    org_id,
    start_utc: datetime,
    end_utc: datetime,
    zone: _ZoneBox | None,
) -> set[str] | None:
    if zone is None:
        return None
    stmt = (
        select(Booking.booking_id, ClientAddress.lat, ClientAddress.lng)
        .select_from(Booking)
        .join(ClientAddress, ClientAddress.address_id == Booking.address_id, isouter=True)
        .where(
            Booking.org_id == org_id,
            Booking.starts_at >= start_utc,
            Booking.starts_at < end_utc,
            Booking.archived_at.is_(None),
        )
    )
    rows = (await session.execute(stmt)).all()
    filtered_rows = _apply_zone_filter(rows, zone)
    return {booking_id for booking_id, _, _ in filtered_rows}


def _booking_end(booking: Booking) -> datetime:
    return _ensure_aware(booking.starts_at) + timedelta(minutes=booking.duration_minutes)


def _normalize_status(value: str | None) -> str:
    return (value or "").strip().lower()


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _local_month(value: datetime | None) -> int:
    if value is None:
        return datetime.now(_DEFAULT_TZ).month
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_DEFAULT_TZ).month


def _river_valley_access(lat: float | None, lng: float | None) -> bool:
    if lat is None or lng is None:
        return False
    return any(
        zone.lat_min <= lat <= zone.lat_max and zone.lng_min <= lng <= zone.lng_max
        for zone in _RIVER_VALLEY_BOXES
    )


def apply_eta_adjustments(
    *,
    base_duration_min: int,
    depart_at: datetime | None,
    zone: str | None,
    lat: float | None,
    lng: float | None,
) -> tuple[int, list[schemas.DispatcherEtaAdjustment]]:
    adjustments: list[schemas.DispatcherEtaAdjustment] = []
    adjusted = base_duration_min
    if _local_month(depart_at) in settings.dispatcher_winter_months:
        multiplier = settings.dispatcher_winter_travel_multiplier
        if multiplier and multiplier != 1.0:
            multiplied = max(int(ceil(base_duration_min * multiplier)), base_duration_min)
            delta = multiplied - base_duration_min
            if delta:
                adjustments.append(
                    schemas.DispatcherEtaAdjustment(
                        kind="adjustment",
                        code="winter_travel_multiplier",
                        label=f"Winter +{int(round((multiplier - 1) * 100))}%",
                        delta_min=delta,
                        multiplier=multiplier,
                    )
                )
            adjusted = multiplied
        buffer_min = settings.dispatcher_winter_buffer_min
        if buffer_min > 0:
            adjusted += buffer_min
            adjustments.append(
                schemas.DispatcherEtaAdjustment(
                    kind="adjustment",
                    code="winter_buffer",
                    label=f"Winter buffer +{buffer_min}m",
                    delta_min=buffer_min,
                )
            )

    if zone == "Downtown":
        buffer_min = settings.dispatcher_downtown_parking_buffer_min
        if buffer_min > 0:
            adjusted += buffer_min
            adjustments.append(
                schemas.DispatcherEtaAdjustment(
                    kind="adjustment",
                    code="downtown_parking_buffer",
                    label=f"Downtown parking +{buffer_min}m",
                    delta_min=buffer_min,
                )
            )

    if _river_valley_access(lat, lng):
        adjustments.append(
            schemas.DispatcherEtaAdjustment(
                kind="note",
                code="river_valley_access",
                label="River Valley access",
            )
        )

    return adjusted, adjustments


def _cancellation_timestamp(booking: Booking) -> datetime | None:
    cancelled_at = getattr(booking, "cancelled_at", None)
    if cancelled_at:
        return _ensure_aware(cancelled_at)
    status_updated_at = getattr(booking, "status_updated_at", None)
    if status_updated_at:
        return _ensure_aware(status_updated_at)
    if booking.updated_at:
        return _ensure_aware(booking.updated_at)
    return None


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _normalize_skill_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def _make_alert(
    *,
    alert_type: str,
    severity: str,
    message: str,
    action: str,
    booking_ids: list[str] | None = None,
    worker_ids: list[int] | None = None,
) -> schemas.DispatcherAlert:
    alert_id = _alert_signature(
        alert_type=alert_type,
        action=action,
        booking_ids=booking_ids,
        worker_ids=worker_ids,
    )
    return schemas.DispatcherAlert(
        alert_id=alert_id,
        type=alert_type,
        severity=severity,
        message=message,
        action=action,
        booking_ids=booking_ids or [],
        worker_ids=worker_ids or [],
    )


def _alert_signature(
    *,
    alert_type: str,
    action: str,
    booking_ids: list[str] | None,
    worker_ids: list[int] | None,
) -> str:
    booking = ",".join(sorted(booking_ids or []))
    worker = ",".join(str(value) for value in sorted(worker_ids or []))
    signature = f"{alert_type}|{action}|{booking}|{worker}"
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]


async def _filter_acknowledged_alerts(
    session: AsyncSession,
    *,
    org_id,
    alerts: list[schemas.DispatcherAlert],
) -> list[schemas.DispatcherAlert]:
    now = datetime.now(timezone.utc)
    store = alert_state_store.get_alert_state_store(session)
    filtered: list[schemas.DispatcherAlert] = []
    for alert in alerts:
        if await store.is_acked(org_id, alert.alert_id, now):
            continue
        filtered.append(alert)
    return filtered


async def acknowledge_dispatcher_alert(
    session: AsyncSession,
    *,
    org_id,
    alert_id: str,
) -> None:
    now = datetime.now(timezone.utc)
    store = alert_state_store.get_alert_state_store(session)
    await store.ack(org_id, alert_id, now + _DISPATCHER_ALERT_ACK_TTL)


def _alert_sms_body(alert: schemas.DispatcherAlert) -> str:
    booking_summary = ""
    if alert.booking_ids:
        booking_summary = f" Booking IDs: {', '.join(alert.booking_ids)}."
    return f"Dispatcher CRITICAL alert: {alert.type}. {alert.message}.{booking_summary}"


async def send_critical_alert_sms(
    session: AsyncSession,
    *,
    org_id,
    identity,
    alerts: list[schemas.DispatcherAlert],
    adapter: TwilioCommunicationAdapter | NoopCommunicationAdapter | None,
) -> None:
    sms_to = settings.dispatcher_alert_sms_to
    if not sms_to:
        return
    now = datetime.now(timezone.utc)
    adapter = adapter or NoopCommunicationAdapter()
    store = alert_state_store.get_alert_state_store(session)
    for alert in alerts:
        if alert.severity != "critical":
            continue
        if await store.is_acked(org_id, alert.alert_id, now):
            continue
        if not await store.allow_sms_send(org_id, alert.alert_id, now, _DISPATCHER_ALERT_SMS_TTL):
            continue
        result = await adapter.send_sms(to_number=sms_to, body=_alert_sms_body(alert))
        await audit_service.record_action(
            session,
            identity=identity,
            org_id=org_id,
            action="dispatcher_alert_sms",
            resource_type="dispatcher_alert",
            resource_id=alert.alert_id,
            before=None,
            after={
                "status": result.status,
                "error_code": result.error_code,
                "alert_type": alert.type,
                "severity": alert.severity,
            },
        )
        await session.commit()


def resolve_day_window(target_date: date, tz_name: str) -> tuple[datetime, datetime]:
    tzinfo = ZoneInfo(tz_name)
    local_start = datetime.combine(target_date, datetime.min.time(), tzinfo=tzinfo)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


async def fetch_dispatcher_board(
    session: AsyncSession,
    *,
    org_id,
    target_date: date,
    tz_name: str,
    zone: str | None = None,
) -> DispatcherBoardResult:
    zone_filter = resolve_zone(zone)
    start_utc, end_utc = resolve_day_window(target_date, tz_name)
    zone_booking_ids = await _zone_filtered_booking_ids(
        session,
        org_id=org_id,
        start_utc=start_utc,
        end_utc=end_utc,
        zone=zone_filter,
    )
    if zone_filter is not None and not zone_booking_ids:
        server_time = datetime.now(timezone.utc)
        return DispatcherBoardResult(
            bookings=[],
            workers=[],
            server_time=server_time,
            data_version=0,
        )
    stmt = (
        select(Booking, ClientUser, ClientAddress, Worker)
        .select_from(Booking)
        .join(ClientUser, ClientUser.client_id == Booking.client_id, isouter=True)
        .join(ClientAddress, ClientAddress.address_id == Booking.address_id, isouter=True)
        .join(Worker, Worker.worker_id == Booking.assigned_worker_id, isouter=True)
        .where(
            Booking.org_id == org_id,
            Booking.starts_at >= start_utc,
            Booking.starts_at < end_utc,
            Booking.archived_at.is_(None),
        )
        .order_by(Worker.worker_id.asc().nulls_last(), Booking.starts_at.asc())
    )
    if zone_booking_ids is not None:
        stmt = stmt.where(Booking.booking_id.in_(zone_booking_ids))
    result = await session.execute(stmt)
    rows = result.all()

    bookings: list[schemas.DispatcherBoardBooking] = []
    workers_map: dict[int, schemas.DispatcherBoardWorkerSummary] = {}
    updated_at_values: list[datetime] = []

    for booking, client, address, worker in rows:
        starts_at = booking.starts_at
        duration_min = booking.duration_minutes
        ends_at = starts_at + timedelta(minutes=duration_min)
        updated_at = booking.updated_at or booking.created_at or datetime.now(timezone.utc)
        updated_at_values.append(updated_at)
        lat = getattr(address, "lat", None)
        lng = getattr(address, "lng", None)
        booking_payload = schemas.DispatcherBoardBooking(
            booking_id=booking.booking_id,
            status=booking.status,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_min=duration_min,
            client=schemas.DispatcherBoardClient(
                id=getattr(client, "client_id", None),
                name=getattr(client, "name", None),
                phone=getattr(client, "phone", None),
            ),
            address=schemas.DispatcherBoardAddress(
                id=getattr(address, "address_id", None),
                formatted=getattr(address, "address_text", None),
                lat=lat,
                lng=lng,
                zone=zone_for_point(lat, lng),
            ),
            assigned_worker=schemas.DispatcherBoardWorker(
                id=getattr(worker, "worker_id", None),
                display_name=getattr(worker, "name", None),
                phone=getattr(worker, "phone", None),
            )
            if worker
            else None,
            team_id=booking.team_id,
            updated_at=updated_at,
        )
        bookings.append(booking_payload)
        if worker:
            workers_map.setdefault(
                worker.worker_id,
                schemas.DispatcherBoardWorkerSummary(
                    worker_id=worker.worker_id,
                    display_name=worker.name,
                ),
            )

    workers = list(workers_map.values())
    server_time = datetime.now(timezone.utc)
    data_version = 0
    if updated_at_values:
        latest = max(updated_at_values)
        data_version = int(latest.timestamp() * 1000)

    return DispatcherBoardResult(
        bookings=bookings,
        workers=workers,
        server_time=server_time,
        data_version=data_version,
    )


async def fetch_dispatcher_stats(
    session: AsyncSession,
    *,
    org_id,
    target_date: date,
    tz_name: str,
    zone: str | None = None,
) -> DispatcherStatsResult:
    zone_filter = resolve_zone(zone)
    start_utc, end_utc = resolve_day_window(target_date, tz_name)
    zone_booking_ids = await _zone_filtered_booking_ids(
        session,
        org_id=org_id,
        start_utc=start_utc,
        end_utc=end_utc,
        zone=zone_filter,
    )
    status_lower = func.lower(Booking.status)
    duration_expr = func.coalesce(Booking.actual_duration_minutes, Booking.duration_minutes)
    stats_stmt = (
        select(
            func.sum(sa.case((status_lower == "done", 1), else_=0)).label("done_count"),
            func.sum(sa.case((status_lower == "in_progress", 1), else_=0)).label(
                "in_progress_count"
            ),
            func.sum(
                sa.case(
                    (status_lower.in_(["planned", "confirmed"]), 1),
                    else_=0,
                )
            ).label("planned_count"),
            func.avg(sa.case((status_lower == "done", duration_expr), else_=None)).label(
                "avg_duration_minutes"
            ),
        )
        .select_from(Booking)
        .join(ClientAddress, ClientAddress.address_id == Booking.address_id, isouter=True)
        .where(
            Booking.org_id == org_id,
            Booking.starts_at >= start_utc,
            Booking.starts_at < end_utc,
            Booking.archived_at.is_(None),
        )
    )
    if zone_booking_ids is not None and not zone_booking_ids:
        done_count = 0
        in_progress_count = 0
        planned_count = 0
        avg_hours = None
    else:
        if zone_booking_ids is not None:
            stats_stmt = stats_stmt.where(Booking.booking_id.in_(zone_booking_ids))
        stats_row = (await session.execute(stats_stmt)).first()
        done_count = int(stats_row.done_count or 0) if stats_row else 0
        in_progress_count = int(stats_row.in_progress_count or 0) if stats_row else 0
        planned_count = int(stats_row.planned_count or 0) if stats_row else 0
        avg_minutes = (
            float(stats_row.avg_duration_minutes)
            if stats_row and stats_row.avg_duration_minutes
            else None
        )
        avg_hours = round(avg_minutes / 60, 2) if avg_minutes is not None else None

    revenue_stmt = (
        select(Payment.amount_cents, ClientAddress.lat, ClientAddress.lng)
        .select_from(Payment)
        .join(Invoice, Invoice.invoice_id == Payment.invoice_id, isouter=True)
        .join(
            Booking,
            sa.or_(
                Booking.booking_id == Payment.booking_id,
                Booking.booking_id == Invoice.order_id,
            ),
            isouter=True,
        )
        .join(ClientAddress, ClientAddress.address_id == Booking.address_id, isouter=True)
        .where(
            Payment.org_id == org_id,
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            func.coalesce(Payment.received_at, Payment.created_at) >= start_utc,
            func.coalesce(Payment.received_at, Payment.created_at) < end_utc,
        )
    )
    revenue_rows = (await session.execute(revenue_stmt)).all()
    if zone_filter is not None:
        revenue_rows = [
            row for row in revenue_rows if _matches_zone(row.lat, row.lng, zone_filter)
        ]
    revenue_cents = sum(int(row.amount_cents or 0) for row in revenue_rows)

    return DispatcherStatsResult(
        done_count=done_count,
        in_progress_count=in_progress_count,
        planned_count=planned_count,
        avg_duration_hours=avg_hours,
        revenue_today_cents=revenue_cents,
    )


async def fetch_dispatcher_assignment_suggestions(
    session: AsyncSession,
    *,
    org_id,
    booking_id: str,
    limit: int = 5,
) -> DispatcherAssignmentSuggestionsResult:
    stmt = (
        select(Booking, ClientAddress, Lead)
        .select_from(Booking)
        .join(ClientAddress, ClientAddress.address_id == Booking.address_id, isouter=True)
        .join(Lead, Lead.lead_id == Booking.lead_id, isouter=True)
        .where(Booking.booking_id == booking_id, Booking.org_id == org_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise LookupError("booking_not_found")
    booking, address, lead = row

    starts_at = _ensure_aware(booking.starts_at)
    ends_at = _booking_end(booking)
    target_lat = getattr(address, "lat", None)
    target_lng = getattr(address, "lng", None)
    target_zone = zone_for_point(target_lat, target_lng)
    service_type = None
    if lead and getattr(lead, "structured_inputs", None):
        service_type = _normalize_skill_value((lead.structured_inputs or {}).get("cleaning_type"))

    workers_stmt = select(Worker).where(
        Worker.org_id == org_id,
        Worker.team_id == booking.team_id,
        Worker.is_active.is_(True),
        Worker.archived_at.is_(None),
    )
    workers = (await session.execute(workers_stmt)).scalars().all()
    if not workers:
        return DispatcherAssignmentSuggestionsResult(suggestions=[])

    worker_ids = [worker.worker_id for worker in workers]
    day_start = datetime.combine(starts_at.date(), datetime.min.time(), tzinfo=starts_at.tzinfo)
    day_end = day_start + timedelta(days=1)
    workload_stmt = (
        select(Booking.assigned_worker_id, func.count(Booking.booking_id).label("count"))
        .where(
            Booking.assigned_worker_id.in_(worker_ids),
            Booking.org_id == org_id,
            Booking.starts_at >= day_start,
            Booking.starts_at < day_end,
            Booking.status.in_(BLOCKING_STATUSES),
        )
        .group_by(Booking.assigned_worker_id)
    )
    workload_counts = {
        row.assigned_worker_id: int(row.count or 0)
        for row in (await session.execute(workload_stmt)).all()
        if row.assigned_worker_id is not None
    }
    max_workload = max(workload_counts.values(), default=0)

    origin_stmt = (
        select(
            Booking.assigned_worker_id.label("worker_id"),
            ClientAddress.lat.label("lat"),
            ClientAddress.lng.label("lng"),
            func.row_number()
            .over(
                partition_by=Booking.assigned_worker_id,
                order_by=Booking.starts_at.desc(),
            )
            .label("rn"),
        )
        .select_from(Booking)
        .join(ClientAddress, ClientAddress.address_id == Booking.address_id, isouter=True)
        .where(
            Booking.org_id == org_id,
            Booking.assigned_worker_id.in_(worker_ids),
            Booking.starts_at < starts_at,
            Booking.archived_at.is_(None),
        )
        .subquery()
    )
    origin_rows = await session.execute(
        select(origin_stmt.c.worker_id, origin_stmt.c.lat, origin_stmt.c.lng).where(
            origin_stmt.c.rn == 1
        )
    )
    origins = {row.worker_id: (row.lat, row.lng) for row in origin_rows if row.worker_id}

    suggestions: list[schemas.DispatcherAssignmentSuggestion] = []

    for worker in workers:
        conflicts = await ops_service.check_schedule_conflicts(
            session,
            org_id,
            starts_at=starts_at,
            ends_at=ends_at,
            team_id=booking.team_id,
            booking_id=booking.booking_id,
            worker_id=worker.worker_id,
        )
        blocking_conflict = any(
            conflict.get("kind") in {"worker_booking", "blackout", "external_block"} for conflict in conflicts
        )
        if blocking_conflict:
            continue

        eta_min = None
        if target_lat is not None and target_lng is not None:
            origin = origins.get(worker.worker_id)
            if origin and origin[0] is not None and origin[1] is not None:
                estimate, _cached = await route_estimates.estimate_route(
                    origin_lat=origin[0],
                    origin_lng=origin[1],
                    dest_lat=target_lat,
                    dest_lng=target_lng,
                    depart_at=starts_at,
                    mode="driving",
                )
                eta_min = estimate.duration_in_traffic_min or estimate.duration_min

        eta_adjustments: list[schemas.DispatcherEtaAdjustment] = []
        if eta_min is not None:
            eta_min, eta_adjustments = apply_eta_adjustments(
                base_duration_min=eta_min,
                depart_at=starts_at,
                zone=target_zone,
                lat=target_lat,
                lng=target_lng,
            )

        if eta_min is None:
            distance_score = 0.5
        else:
            distance_score = _clamp(
                1 - min(eta_min, SUGGEST_DISTANCE_MAX_MIN) / SUGGEST_DISTANCE_MAX_MIN
            )

        worker_skills = [
            normalized
            for normalized in (_normalize_skill_value(skill) for skill in (worker.skills or []))
            if normalized
        ]
        skill_score = 0.0
        if service_type and worker_skills:
            skill_score = 1.0 if service_type in worker_skills else 0.0

        rating_avg = worker.rating_avg or 0.0
        rating_score = _clamp((rating_avg - 1) / 4) if rating_avg else 0.0

        workload_count = workload_counts.get(worker.worker_id, 0)
        workload_score = (
            _clamp(1 - (workload_count / max_workload)) if max_workload > 0 else 1.0
        )

        score_total = (
            distance_score * SUGGEST_DISTANCE_WEIGHT
            + skill_score * SUGGEST_SKILL_WEIGHT
            + rating_score * SUGGEST_RATING_WEIGHT
            + workload_score * SUGGEST_WORKLOAD_WEIGHT
        )

        reasons = ["available"]
        if eta_min is None:
            reasons.append("location unknown")
        elif eta_min <= SUGGEST_CLOSEST_THRESHOLD_MIN:
            reasons.append("closest")
        if skill_score >= 1.0:
            reasons.append("skill match")
        if rating_score >= SUGGEST_HIGH_RATING_THRESHOLD:
            reasons.append("high rating")
        if workload_score >= SUGGEST_LIGHT_WORKLOAD_THRESHOLD and max_workload > 0:
            reasons.append("light workload")

        for adjustment in eta_adjustments:
            if adjustment.label not in reasons:
                reasons.append(adjustment.label)

        suggestions.append(
            schemas.DispatcherAssignmentSuggestion(
                worker_id=worker.worker_id,
                display_name=worker.name,
                score_total=round(score_total, 4),
                score_parts=schemas.DispatcherSuggestionScoreParts(
                    availability=1.0,
                    distance=round(distance_score, 4),
                    skill=round(skill_score, 4),
                    rating=round(rating_score, 4),
                    workload=round(workload_score, 4),
                ),
                eta_min=eta_min,
                reasons=reasons,
            )
        )

    suggestions.sort(
        key=lambda item: (
            -item.score_total,
            item.eta_min if item.eta_min is not None else 10**9,
            -item.score_parts.rating,
            item.worker_id,
        )
    )

    return DispatcherAssignmentSuggestionsResult(suggestions=suggestions[:limit])


_DISPATCHER_TEMPLATES: dict[str, dict[str, str]] = {
    "WORKER_EN_ROUTE_15MIN": {
        "en": (
            "Hi {worker_name}, reminder: booking {booking_id} starts at {start_time}. "
            "Please head to {address}. Reply if you're delayed."
        ),
        "ru": "",
    },
    "CLIENT_DELAY_TRAFFIC": {
        "en": (
            "Hi {client_name}, your cleaner is running about {delay_minutes} minutes late due to traffic. "
            "We'll keep you posted."
        ),
        "ru": "",
    },
    "CLIENT_DONE": {
        "en": "Hi {client_name}, your cleaning is complete at {address}. Thank you for choosing us!",
        "ru": "",
    },
}


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


def _render_template(template_id: str, locale: str, context: dict[str, str]) -> str:
    template = _DISPATCHER_TEMPLATES.get(template_id, {}).get(locale)
    if not template:
        raise LookupError("unknown_template")
    return template.format_map(_SafeFormatDict(context))


def _format_booking_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).strftime("%H:%M")


async def send_dispatcher_notification(
    session: AsyncSession,
    *,
    org_id,
    payload: schemas.DispatcherNotifyRequest,
    admin_user_id: str,
    adapter: TwilioCommunicationAdapter | NoopCommunicationAdapter | None,
) -> tuple[DispatcherCommunicationAudit, CommunicationResult]:
    stmt = (
        select(Booking, ClientUser, ClientAddress, Worker)
        .select_from(Booking)
        .join(ClientUser, ClientUser.client_id == Booking.client_id, isouter=True)
        .join(ClientAddress, ClientAddress.address_id == Booking.address_id, isouter=True)
        .join(Worker, Worker.worker_id == Booking.assigned_worker_id, isouter=True)
        .where(Booking.booking_id == payload.booking_id, Booking.org_id == org_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise LookupError("booking_not_found")

    booking, client, address, worker = row
    phone = None
    if payload.target == "client":
        phone = getattr(client, "phone", None)
    elif payload.target == "worker":
        phone = getattr(worker, "phone", None)

    status = "failed"
    provider_msg_id = None
    error_code = None

    if not phone:
        error_code = "missing_phone"
    else:
        adapter = adapter or NoopCommunicationAdapter()
        try:
            if payload.channel == "sms":
                context = {
                    "booking_id": booking.booking_id,
                    "client_name": getattr(client, "name", "") or "there",
                    "worker_name": getattr(worker, "name", "") or "team",
                    "start_time": _format_booking_time(booking.starts_at),
                    "address": getattr(address, "address_text", "") or "your location",
                    "delay_minutes": payload.params.get("delay_minutes", "15")
                    if payload.params
                    else "15",
                }
                context.update(payload.params or {})
                try:
                    body = _render_template(payload.template_id, payload.locale, context)
                except LookupError:
                    error_code = "unknown_template"
                else:
                    result = await adapter.send_sms(to_number=phone, body=body)
                    status = result.status
                    provider_msg_id = result.provider_msg_id
                    error_code = result.error_code
            else:
                result = await adapter.send_call(to_number=phone)
                status = result.status
                provider_msg_id = result.provider_msg_id
                error_code = result.error_code
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "dispatcher_notify_failed",
                extra={
                    "extra": {
                        "booking_id": payload.booking_id,
                        "template_id": payload.template_id,
                        "target": payload.target,
                        "channel": payload.channel,
                        "reason": type(exc).__name__,
                    }
                },
            )
            status = "failed"
            error_code = "send_failed"

    audit = DispatcherCommunicationAudit(
        org_id=org_id,
        booking_id=payload.booking_id,
        target=payload.target,
        channel=payload.channel,
        template_id=payload.template_id,
        admin_user_id=admin_user_id,
        status=status,
        provider_msg_id=provider_msg_id,
        error_code=error_code,
    )
    session.add(audit)
    await session.flush()
    logger.info(
        "dispatcher_notify_audit",
        extra={
            "extra": {
                "booking_id": payload.booking_id,
                "template_id": payload.template_id,
                "target": payload.target,
                "channel": payload.channel,
                "status": status,
            }
        },
    )
    return audit, CommunicationResult(status=status, provider_msg_id=provider_msg_id, error_code=error_code)


async def fetch_dispatcher_notification_audits(
    session: AsyncSession,
    *,
    org_id,
    booking_id: str,
    limit: int = 5,
) -> list[DispatcherCommunicationAudit]:
    stmt = (
        select(DispatcherCommunicationAudit)
        .where(
            DispatcherCommunicationAudit.org_id == org_id,
            DispatcherCommunicationAudit.booking_id == booking_id,
        )
        .order_by(DispatcherCommunicationAudit.sent_at.desc())
        .limit(limit)
    )
    return (await session.execute(stmt)).scalars().all()


async def fetch_dispatcher_alerts(
    session: AsyncSession,
    *,
    org_id,
    target_date: date,
    tz_name: str,
) -> DispatcherAlertsResult:
    start_utc, end_utc = resolve_day_window(target_date, tz_name)
    grace = timedelta(minutes=15)
    late_window_start = start_utc - timedelta(hours=1)
    cancellation_timestamp = (
        getattr(Booking, "cancelled_at", None)
        or getattr(Booking, "status_updated_at", None)
        or Booking.updated_at
    )
    booking_stmt = (
        select(Booking)
        .where(
            Booking.org_id == org_id,
            Booking.archived_at.is_(None),
            sa.or_(
                sa.and_(
                    Booking.starts_at >= late_window_start,
                    Booking.starts_at < end_utc,
                ),
                sa.and_(
                    func.lower(Booking.status) == "cancelled",
                    cancellation_timestamp >= start_utc,
                    cancellation_timestamp < end_utc,
                ),
            ),
        )
        .order_by(Booking.starts_at.asc())
    )
    bookings = (await session.execute(booking_stmt)).scalars().all()
    alerts: list[schemas.DispatcherAlert] = []

    bookings_by_worker: dict[int, list[Booking]] = {}
    for booking in bookings:
        if booking.assigned_worker_id:
            bookings_by_worker.setdefault(booking.assigned_worker_id, []).append(booking)

    for worker_id, worker_bookings in bookings_by_worker.items():
        worker_bookings.sort(key=lambda item: item.starts_at)
        overlap_ids: set[str] = set()
        for index, booking in enumerate(worker_bookings):
            booking_start = _ensure_aware(booking.starts_at)
            booking_end = booking_start + timedelta(minutes=booking.duration_minutes)
            for other in worker_bookings[index + 1 :]:
                other_start = _ensure_aware(other.starts_at)
                other_end = other_start + timedelta(minutes=other.duration_minutes)
                if other_start >= booking_end:
                    break
                if other_end > booking_start:
                    overlap_ids.update({booking.booking_id, other.booking_id})
        if overlap_ids:
            alerts.append(
                _make_alert(
                    alert_type="DOUBLE_BOOKING",
                    severity="critical",
                    message=f"Worker {worker_id} has overlapping bookings.",
                    action="reassign",
                    booking_ids=sorted(overlap_ids),
                    worker_ids=[worker_id],
                )
            )

    now_utc = datetime.now(timezone.utc)
    tzinfo = ZoneInfo(tz_name)
    for booking in bookings:
        if _normalize_status(booking.status) == "cancelled":
            cancelled_at = _cancellation_timestamp(booking)
            if cancelled_at and start_utc <= cancelled_at < end_utc:
                alerts.append(
                    _make_alert(
                        alert_type="CLIENT_CANCELLED_TODAY",
                        severity="info",
                        message="Client cancelled a booking today.",
                        action="notify_client",
                        booking_ids=[booking.booking_id],
                    )
                )

    for booking in bookings:
        if not booking.assigned_worker_id:
            continue
        booking_starts = _ensure_aware(booking.starts_at)
        if _normalize_status(booking.status) == "planned" and now_utc > booking_starts + grace:
            local_time = booking_starts.astimezone(tzinfo).strftime("%H:%M")
            alerts.append(
                _make_alert(
                    alert_type="LATE_WORKER",
                    severity="warn",
                    message=f"Worker {booking.assigned_worker_id} is late for a {local_time} booking.",
                    action="call_worker",
                    booking_ids=[booking.booking_id],
                    worker_ids=[booking.assigned_worker_id],
                )
            )

    available_workers = await session.scalar(
        select(func.count())
        .select_from(Worker)
        .where(
            Worker.org_id == org_id,
            Worker.is_active.is_(True),
            Worker.archived_at.is_(None),
        )
    )
    available_workers = int(available_workers or 0)
    booking_count = len(bookings)
    if available_workers and booking_count > available_workers:
        alerts.append(
            _make_alert(
                alert_type="WORKER_SHORTAGE",
                severity="warn",
                message=f"Bookings ({booking_count}) exceed available workers ({available_workers}).",
                action="reassign",
                booking_ids=[booking.booking_id for booking in bookings],
            )
        )

    return DispatcherAlertsResult(
        alerts=await _filter_acknowledged_alerts(session, org_id=org_id, alerts=alerts)
    )
