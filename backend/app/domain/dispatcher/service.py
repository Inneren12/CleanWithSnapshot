from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.dispatcher import schemas
from app.domain.workers.db_models import Worker


@dataclass(frozen=True)
class DispatcherBoardResult:
    bookings: list[schemas.DispatcherBoardBooking]
    workers: list[schemas.DispatcherBoardWorkerSummary]
    server_time: datetime
    data_version: int


@dataclass(frozen=True)
class DispatcherAlertsResult:
    alerts: list[schemas.DispatcherAlert]


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
    del zone
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
                lat=None,
                lng=None,
                zone=None,
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
