from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.dispatcher.db_models import DispatcherCommunicationAudit
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, Payment
from app.domain.dispatcher import schemas
from app.domain.notifications.email_service import LOCAL_TZ
from app.domain.workers.db_models import Worker
from app.infra.communication import CommunicationResult, NoopCommunicationAdapter, TwilioCommunicationAdapter

logger = logging.getLogger(__name__)


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

_ZONE_LOOKUP = {zone.name.lower(): zone for zone in _ZONE_BOXES}
_ZONE_ALIASES = {
    "whyte": "whyte/old strathcona",
    "old strathcona": "whyte/old strathcona",
    "st albert": "st. albert",
}


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


def _apply_zone_filter(stmt: sa.Select, zone: _ZoneBox | None) -> sa.Select:
    if zone is None:
        return stmt
    return stmt.where(
        ClientAddress.lat.isnot(None),
        ClientAddress.lng.isnot(None),
        ClientAddress.lat >= zone.lat_min,
        ClientAddress.lat <= zone.lat_max,
        ClientAddress.lng >= zone.lng_min,
        ClientAddress.lng <= zone.lng_max,
    )


def _booking_end(booking: Booking) -> datetime:
    return _ensure_aware(booking.starts_at) + timedelta(minutes=booking.duration_minutes)


def _normalize_status(value: str | None) -> str:
    return (value or "").strip().lower()


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _make_alert(
    *,
    alert_type: str,
    severity: str,
    message: str,
    action: str,
    booking_ids: list[str] | None = None,
    worker_ids: list[int] | None = None,
) -> schemas.DispatcherAlert:
    return schemas.DispatcherAlert(
        type=alert_type,
        severity=severity,
        message=message,
        action=action,
        booking_ids=booking_ids or [],
        worker_ids=worker_ids or [],
    )


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
    stmt = _apply_zone_filter(stmt, zone_filter)
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
    stats_stmt = _apply_zone_filter(stats_stmt, zone_filter)
    stats_row = (await session.execute(stats_stmt)).first()
    done_count = int(stats_row.done_count or 0) if stats_row else 0
    in_progress_count = int(stats_row.in_progress_count or 0) if stats_row else 0
    planned_count = int(stats_row.planned_count or 0) if stats_row else 0
    avg_minutes = float(stats_row.avg_duration_minutes) if stats_row and stats_row.avg_duration_minutes else None
    avg_hours = round(avg_minutes / 60, 2) if avg_minutes is not None else None

    revenue_stmt = (
        select(func.coalesce(func.sum(func.coalesce(Payment.amount_cents, 0)), 0).label("revenue_cents"))
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
    revenue_stmt = _apply_zone_filter(revenue_stmt, zone_filter)
    revenue_row = (await session.execute(revenue_stmt)).first()
    revenue_cents = int(revenue_row.revenue_cents or 0) if revenue_row else 0

    return DispatcherStatsResult(
        done_count=done_count,
        in_progress_count=in_progress_count,
        planned_count=planned_count,
        avg_duration_hours=avg_hours,
        revenue_today_cents=revenue_cents,
    )


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
    booking_stmt = (
        select(Booking)
        .where(
            Booking.org_id == org_id,
            Booking.starts_at >= start_utc,
            Booking.starts_at < end_utc,
            Booking.archived_at.is_(None),
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
    grace = timedelta(minutes=15)
    tzinfo = ZoneInfo(tz_name)
    for booking in bookings:
        if _normalize_status(booking.status) == "cancelled" and booking.updated_at:
            updated_at = _ensure_aware(booking.updated_at)
            if start_utc <= updated_at < end_utc:
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

    return DispatcherAlertsResult(alerts=alerts)
