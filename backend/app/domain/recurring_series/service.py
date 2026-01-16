from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.availability import service as availability_service
from app.domain.bookings import service as booking_service
from app.domain.bookings.db_models import Booking, Team
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.org_settings import service as org_settings_service
from app.domain.pricing_settings.db_models import ServiceType
from app.domain.recurring_series import schemas
from app.domain.recurring_series.db_models import RecurringSeries
from app.domain.workers.db_models import Worker

DEFAULT_HORIZON_DAYS = 60
MAX_SCAN_YEARS = 5


@dataclass
class SeriesGenerationReport:
    created: list[schemas.OccurrenceReport]
    needs_assignment: list[schemas.OccurrenceReport]
    skipped: list[schemas.OccurrenceReport]
    conflicted: list[schemas.OccurrenceReport]
    horizon_end: datetime
    next_run_at: datetime | None


def _resolve_timezone(org_timezone: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(org_timezone or org_settings_service.DEFAULT_TIMEZONE)
    except Exception:  # noqa: BLE001
        return ZoneInfo(org_settings_service.DEFAULT_TIMEZONE)


def _normalized_weekdays(series: RecurringSeries) -> list[int]:
    if series.by_weekday:
        return series.by_weekday
    return [series.starts_on.weekday()]


def _normalized_monthdays(series: RecurringSeries) -> list[int]:
    if series.by_monthday:
        return series.by_monthday
    return [series.starts_on.day]


def _matches_recurrence(series: RecurringSeries, target_day: date) -> bool:
    if target_day < series.starts_on:
        return False
    if series.ends_on and target_day > series.ends_on:
        return False
    if series.frequency == "weekly":
        if target_day.weekday() not in _normalized_weekdays(series):
            return False
        weeks_since = (target_day - series.starts_on).days // 7
        return weeks_since % series.interval == 0
    if series.frequency == "monthly":
        if target_day.day not in _normalized_monthdays(series):
            return False
        months_since = (target_day.year - series.starts_on.year) * 12 + (
            target_day.month - series.starts_on.month
        )
        return months_since % series.interval == 0
    return False


def _iter_occurrences(
    series: RecurringSeries,
    start_local: datetime,
    end_local: datetime,
    org_tz: ZoneInfo,
) -> Iterable[datetime]:
    start_date = max(series.starts_on, start_local.date())
    end_date = end_local.date()
    if series.ends_on:
        end_date = min(end_date, series.ends_on)

    current = start_date
    while current <= end_date:
        if _matches_recurrence(series, current):
            occurrence = datetime.combine(current, series.start_time, tzinfo=org_tz)
            if occurrence >= start_local:
                yield occurrence
        current += timedelta(days=1)


def _next_occurrence(series: RecurringSeries, from_local: datetime, org_tz: ZoneInfo) -> datetime | None:
    if series.ends_on and from_local.date() > series.ends_on:
        return None
    scan_days = MAX_SCAN_YEARS * 366
    start_date = max(series.starts_on, from_local.date())
    for offset in range(scan_days + 1):
        day = start_date + timedelta(days=offset)
        if series.ends_on and day > series.ends_on:
            return None
        if _matches_recurrence(series, day):
            occurrence = datetime.combine(day, series.start_time, tzinfo=org_tz)
            if occurrence >= from_local:
                return occurrence
    return None


def _normalize_start_time(value: time) -> time:
    return value.replace(second=0, microsecond=0)


async def _validate_client(
    session: AsyncSession,
    org_id,
    client_id: str | None,
    *,
    allow_inactive: bool = False,
) -> ClientUser | None:
    if not client_id:
        return None
    criteria = [
        ClientUser.client_id == client_id,
        ClientUser.org_id == org_id,
    ]
    if not allow_inactive:
        criteria.append(ClientUser.is_active.is_(True))
    client = await session.scalar(select(ClientUser).where(*criteria))
    if client is None:
        raise LookupError("client_not_found")
    return client


async def _validate_address(
    session: AsyncSession,
    org_id,
    address_id: int | None,
    client_id: str | None,
    *,
    allow_inactive: bool = False,
) -> ClientAddress | None:
    if address_id is None:
        return None
    criteria = [
        ClientAddress.address_id == address_id,
        ClientAddress.org_id == org_id,
    ]
    if not allow_inactive:
        criteria.append(ClientAddress.is_active.is_(True))
    address = await session.scalar(select(ClientAddress).where(*criteria))
    if address is None:
        raise LookupError("address_not_found")
    if client_id and address.client_id != client_id:
        raise ValueError("address_client_mismatch")
    return address


async def _validate_service_type(
    session: AsyncSession,
    org_id,
    service_type_id: int | None,
    *,
    allow_inactive: bool = False,
) -> ServiceType | None:
    if service_type_id is None:
        return None
    criteria = [
        ServiceType.service_type_id == service_type_id,
        ServiceType.org_id == org_id,
    ]
    if not allow_inactive:
        criteria.append(ServiceType.active.is_(True))
    service_type = await session.scalar(select(ServiceType).where(*criteria))
    if service_type is None:
        raise LookupError("service_type_not_found")
    return service_type


async def _validate_team(session: AsyncSession, org_id, team_id: int | None) -> Team | None:
    if team_id is None:
        return None
    team = await session.scalar(
        select(Team).where(Team.team_id == team_id, Team.org_id == org_id)
    )
    if team is None:
        raise LookupError("team_not_found")
    return team


async def _validate_worker(
    session: AsyncSession,
    org_id,
    worker_id: int | None,
    *,
    allow_inactive: bool = False,
) -> Worker | None:
    if worker_id is None:
        return None
    criteria = [
        Worker.worker_id == worker_id,
        Worker.org_id == org_id,
    ]
    if not allow_inactive:
        criteria.append(Worker.is_active.is_(True))
    worker = await session.scalar(select(Worker).where(*criteria))
    if worker is None:
        raise LookupError("worker_not_found")
    return worker


async def _resolve_series_refs(
    session: AsyncSession,
    org_id,
    *,
    client_id: str | None,
    address_id: int | None,
    service_type_id: int | None,
    preferred_team_id: int | None,
    preferred_worker_id: int | None,
    allow_inactive_service: bool = False,
    allow_inactive_worker: bool = False,
    allow_inactive_client: bool = False,
    allow_inactive_address: bool = False,
) -> tuple[ClientUser | None, ClientAddress | None, ServiceType | None, Team | None, Worker | None, int | None]:
    client = await _validate_client(
        session, org_id, client_id, allow_inactive=allow_inactive_client
    )
    address = await _validate_address(
        session,
        org_id,
        address_id,
        client_id,
        allow_inactive=allow_inactive_address,
    )
    service_type = await _validate_service_type(
        session, org_id, service_type_id, allow_inactive=allow_inactive_service
    )
    worker = await _validate_worker(
        session, org_id, preferred_worker_id, allow_inactive=allow_inactive_worker
    )
    team = await _validate_team(session, org_id, preferred_team_id)
    resolved_team_id = preferred_team_id
    if worker and worker.team_id and preferred_team_id is None:
        resolved_team_id = worker.team_id
    if team and worker and worker.team_id != team.team_id:
        raise ValueError("worker_team_mismatch")
    return client, address, service_type, team, worker, resolved_team_id


async def list_series(session: AsyncSession, org_id) -> tuple[str, list[RecurringSeries]]:
    org_settings = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_timezone = org_settings_service.resolve_timezone(org_settings)
    stmt = (
        select(RecurringSeries)
        .where(RecurringSeries.org_id == org_id)
        .order_by(RecurringSeries.created_at.desc())
    )
    series = list((await session.execute(stmt)).scalars().all())
    return org_timezone, series


async def _created_count_map(session: AsyncSession, series_ids: list) -> dict:
    if not series_ids:
        return {}
    stmt = (
        select(Booking.recurring_series_id, Booking.booking_id)
        .where(Booking.recurring_series_id.in_(series_ids))
    )
    rows = (await session.execute(stmt)).all()
    counts: dict = {}
    for series_id, _booking_id in rows:
        counts[series_id] = counts.get(series_id, 0) + 1
    return counts


async def _load_related_maps(session: AsyncSession, series: list[RecurringSeries]):
    client_ids = {item.client_id for item in series if item.client_id}
    address_ids = {item.address_id for item in series if item.address_id}
    service_ids = {item.service_type_id for item in series if item.service_type_id}
    team_ids = {item.preferred_team_id for item in series if item.preferred_team_id}
    worker_ids = {item.preferred_worker_id for item in series if item.preferred_worker_id}

    client_map = {}
    if client_ids:
        clients = (
            await session.execute(select(ClientUser).where(ClientUser.client_id.in_(client_ids)))
        ).scalars()
        client_map = {client.client_id: client for client in clients}

    address_map = {}
    if address_ids:
        addresses = (
            await session.execute(
                select(ClientAddress).where(ClientAddress.address_id.in_(address_ids))
            )
        ).scalars()
        address_map = {address.address_id: address for address in addresses}

    service_map = {}
    if service_ids:
        services = (
            await session.execute(
                select(ServiceType).where(ServiceType.service_type_id.in_(service_ids))
            )
        ).scalars()
        service_map = {service.service_type_id: service for service in services}

    team_map = {}
    if team_ids:
        teams = (await session.execute(select(Team).where(Team.team_id.in_(team_ids)))).scalars()
        team_map = {team.team_id: team for team in teams}

    worker_map = {}
    if worker_ids:
        workers = (
            await session.execute(select(Worker).where(Worker.worker_id.in_(worker_ids)))
        ).scalars()
        worker_map = {worker.worker_id: worker for worker in workers}

    return client_map, address_map, service_map, team_map, worker_map


def _series_response(
    series: RecurringSeries,
    *,
    org_tz: ZoneInfo,
    created_count: int,
    client: ClientUser | None,
    address: ClientAddress | None,
    service_type: ServiceType | None,
    team: Team | None,
    worker: Worker | None,
) -> schemas.RecurringSeriesResponse:
    next_local = series.next_run_at.astimezone(org_tz) if series.next_run_at else None
    client_label = None
    if client:
        client_label = client.name or client.email
    address_label = None
    if address:
        address_label = address.address_text
    service_label = service_type.name if service_type else None
    team_label = team.name if team else None
    worker_label = worker.name if worker else None
    return schemas.RecurringSeriesResponse(
        series_id=series.series_id,
        org_id=series.org_id,
        client_id=series.client_id,
        address_id=series.address_id,
        service_type_id=series.service_type_id,
        preferred_team_id=series.preferred_team_id,
        preferred_worker_id=series.preferred_worker_id,
        status=series.status,
        starts_on=series.starts_on,
        start_time=series.start_time,
        frequency=series.frequency,
        interval=series.interval,
        by_weekday=series.by_weekday,
        by_monthday=series.by_monthday,
        ends_on=series.ends_on,
        duration_minutes=series.duration_minutes,
        horizon_days=series.horizon_days,
        next_run_at=series.next_run_at,
        next_occurrence_local=next_local,
        created_at=series.created_at,
        updated_at=series.updated_at,
        created_count=created_count,
        client_label=client_label,
        address_label=address_label,
        service_type_label=service_label,
        team_label=team_label,
        worker_label=worker_label,
    )


async def build_series_responses(
    session: AsyncSession,
    series: list[RecurringSeries],
    org_timezone: str,
) -> list[schemas.RecurringSeriesResponse]:
    org_tz = _resolve_timezone(org_timezone)
    counts = await _created_count_map(session, [item.series_id for item in series])
    client_map, address_map, service_map, team_map, worker_map = await _load_related_maps(
        session, series
    )
    return [
        _series_response(
            item,
            org_tz=org_tz,
            created_count=counts.get(item.series_id, 0),
            client=client_map.get(item.client_id),
            address=address_map.get(item.address_id),
            service_type=service_map.get(item.service_type_id),
            team=team_map.get(item.preferred_team_id),
            worker=worker_map.get(item.preferred_worker_id),
        )
        for item in series
    ]


async def create_series(
    session: AsyncSession,
    org_id,
    *,
    payload: schemas.RecurringSeriesCreate,
) -> RecurringSeries:
    client, address, service_type, team, worker, resolved_team_id = await _resolve_series_refs(
        session,
        org_id,
        client_id=payload.client_id,
        address_id=payload.address_id,
        service_type_id=payload.service_type_id,
        preferred_team_id=payload.preferred_team_id,
        preferred_worker_id=payload.preferred_worker_id,
    )
    starts_on = payload.starts_on
    start_time = _normalize_start_time(payload.start_time)
    series = RecurringSeries(
        org_id=org_id,
        client_id=client.client_id if client else None,
        address_id=address.address_id if address else None,
        service_type_id=service_type.service_type_id if service_type else None,
        preferred_team_id=resolved_team_id,
        preferred_worker_id=worker.worker_id if worker else None,
        status=payload.status,
        starts_on=starts_on,
        start_time=start_time,
        frequency=payload.frequency,
        interval=payload.interval,
        by_weekday=payload.by_weekday,
        by_monthday=payload.by_monthday,
        ends_on=payload.ends_on,
        duration_minutes=payload.duration_minutes,
        horizon_days=payload.horizon_days or DEFAULT_HORIZON_DAYS,
    )

    org_settings = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_tz = _resolve_timezone(org_settings_service.resolve_timezone(org_settings))
    now_local = datetime.now(org_tz)
    series.next_run_at = None
    if series.status == "active":
        next_local = _next_occurrence(series, now_local, org_tz)
        series.next_run_at = next_local.astimezone(timezone.utc) if next_local else None

    session.add(series)
    await session.commit()
    await session.refresh(series)
    return series


async def update_series(
    session: AsyncSession,
    org_id,
    series_id,
    *,
    payload: schemas.RecurringSeriesUpdate,
    fields_set: set[str],
) -> RecurringSeries:
    series = await session.get(RecurringSeries, series_id)
    if series is None or series.org_id != org_id:
        raise LookupError("series_not_found")

    client_id = series.client_id
    address_id = series.address_id
    service_type_id = series.service_type_id
    preferred_team_id = series.preferred_team_id
    preferred_worker_id = series.preferred_worker_id

    if "client_id" in fields_set:
        client_id = payload.client_id
    if "address_id" in fields_set:
        address_id = payload.address_id
    if "service_type_id" in fields_set:
        service_type_id = payload.service_type_id
    if "preferred_team_id" in fields_set:
        preferred_team_id = payload.preferred_team_id
    if "preferred_worker_id" in fields_set:
        preferred_worker_id = payload.preferred_worker_id

    should_validate_refs = bool(
        {
            "client_id",
            "address_id",
            "service_type_id",
            "preferred_team_id",
            "preferred_worker_id",
        }.intersection(fields_set)
    )
    client = address = service_type = worker = None
    resolved_team_id = preferred_team_id
    if should_validate_refs:
        client, address, service_type, _team, worker, resolved_team_id = await _resolve_series_refs(
            session,
            org_id,
            client_id=client_id,
            address_id=address_id,
            service_type_id=service_type_id,
            preferred_team_id=preferred_team_id,
            preferred_worker_id=preferred_worker_id,
            allow_inactive_service="service_type_id" not in fields_set,
            allow_inactive_worker="preferred_worker_id" not in fields_set,
            allow_inactive_client="client_id" not in fields_set,
            allow_inactive_address="address_id" not in fields_set,
        )

    if "client_id" in fields_set:
        series.client_id = client.client_id if client else None
    if "address_id" in fields_set:
        series.address_id = address.address_id if address else None
    if "service_type_id" in fields_set:
        series.service_type_id = service_type.service_type_id if service_type else None
    if "preferred_team_id" in fields_set or "preferred_worker_id" in fields_set:
        series.preferred_team_id = resolved_team_id
        series.preferred_worker_id = worker.worker_id if worker else None

    schedule_fields = {
        "status",
        "starts_on",
        "start_time",
        "frequency",
        "interval",
        "by_weekday",
        "by_monthday",
        "ends_on",
        "duration_minutes",
        "horizon_days",
    }

    if "status" in fields_set and payload.status is not None:
        series.status = payload.status
    if "starts_on" in fields_set and payload.starts_on is not None:
        series.starts_on = payload.starts_on
    if "start_time" in fields_set and payload.start_time is not None:
        series.start_time = _normalize_start_time(payload.start_time)
    if "frequency" in fields_set and payload.frequency is not None:
        series.frequency = payload.frequency
    if "interval" in fields_set and payload.interval is not None:
        series.interval = payload.interval
    if "by_weekday" in fields_set and payload.by_weekday is not None:
        series.by_weekday = payload.by_weekday
    if "by_monthday" in fields_set and payload.by_monthday is not None:
        series.by_monthday = payload.by_monthday
    if "ends_on" in fields_set:
        series.ends_on = payload.ends_on
    if "duration_minutes" in fields_set and payload.duration_minutes is not None:
        series.duration_minutes = payload.duration_minutes
    if "horizon_days" in fields_set and payload.horizon_days is not None:
        series.horizon_days = payload.horizon_days

    if schedule_fields.intersection(fields_set):
        org_settings = await org_settings_service.get_or_create_org_settings(session, org_id)
        org_tz = _resolve_timezone(org_settings_service.resolve_timezone(org_settings))
        now_local = datetime.now(org_tz)
        if series.status == "active":
            next_local = _next_occurrence(series, now_local, org_tz)
            series.next_run_at = next_local.astimezone(timezone.utc) if next_local else None
        else:
            series.next_run_at = series.next_run_at

    await session.commit()
    await session.refresh(series)
    return series


async def _worker_conflict(
    session: AsyncSession,
    org_id,
    worker: Worker,
    starts_at: datetime,
    ends_at: datetime,
) -> bool:
    blocks = await availability_service.list_worker_blocks(
        session,
        org_id,
        worker.worker_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    if blocks:
        return True

    bind = session.get_bind()
    booking_end = Booking.ends_at if hasattr(Booking, "ends_at") else None
    if booking_end is None:
        if bind and bind.dialect.name == "sqlite":
            booking_end = func.datetime(
                Booking.starts_at, func.printf("+%d minutes", Booking.duration_minutes)
            )
        else:
            booking_end = Booking.starts_at + func.make_interval(mins=Booking.duration_minutes)

    buffer_delta = timedelta(minutes=booking_service.BUFFER_MINUTES)
    stmt = select(Booking).where(
        Booking.org_id == org_id,
        Booking.assigned_worker_id == worker.worker_id,
        Booking.starts_at < ends_at + buffer_delta,
        booking_end > starts_at - buffer_delta,
        Booking.status.in_(booking_service.BLOCKING_STATUSES),
    )
    conflict = await session.scalar(stmt)
    return conflict is not None


async def generate_occurrences(
    session: AsyncSession,
    org_id,
    series_id,
    *,
    horizon_days: int | None = None,
) -> tuple[RecurringSeries, SeriesGenerationReport]:
    series = await session.get(RecurringSeries, series_id)
    if series is None or series.org_id != org_id:
        raise LookupError("series_not_found")
    if series.status != "active":
        raise ValueError("series_inactive")

    org_settings = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_tz = _resolve_timezone(org_settings_service.resolve_timezone(org_settings))
    now_local = datetime.now(org_tz)
    effective_horizon = horizon_days or series.horizon_days or DEFAULT_HORIZON_DAYS
    horizon_end_local = now_local + timedelta(days=effective_horizon)

    start_local = now_local
    if series.next_run_at:
        start_local = max(start_local, series.next_run_at.astimezone(org_tz))

    occurrences = list(_iter_occurrences(series, start_local, horizon_end_local, org_tz))

    created: list[schemas.OccurrenceReport] = []
    needs_assignment: list[schemas.OccurrenceReport] = []
    skipped: list[schemas.OccurrenceReport] = []
    conflicted: list[schemas.OccurrenceReport] = []

    team_id = series.preferred_team_id
    if team_id is None:
        team = await booking_service.ensure_default_team(session, org_id=org_id)
        team_id = team.team_id

    worker = None
    if series.preferred_worker_id is not None:
        worker = await session.scalar(
            select(Worker).where(
                Worker.worker_id == series.preferred_worker_id,
                Worker.org_id == org_id,
                Worker.is_active.is_(True),
            )
        )

    for occurrence_local in occurrences:
        occurrence_utc = occurrence_local.astimezone(timezone.utc)
        window_end = occurrence_utc + timedelta(minutes=series.duration_minutes)
        existing = await session.scalar(
            select(Booking).where(
                Booking.recurring_series_id == series.series_id,
                Booking.starts_at == occurrence_utc,
            )
        )
        if existing:
            skipped.append(
                schemas.OccurrenceReport(
                    scheduled_for=occurrence_utc,
                    booking_id=existing.booking_id,
                    reason="already_created",
                )
            )
            continue

        slot_available = await booking_service.is_slot_available(
            occurrence_utc,
            series.duration_minutes,
            session,
            team_id=team_id,
        )
        if not slot_available:
            conflicted.append(
                schemas.OccurrenceReport(
                    scheduled_for=occurrence_utc,
                    reason="team_conflict",
                )
            )
            continue

        assigned_worker_id = None
        needs_assignment_reason = None
        if worker is None and series.preferred_worker_id is not None:
            needs_assignment_reason = "preferred_worker_unavailable"
        elif worker is not None:
            worker_conflict = await _worker_conflict(session, org_id, worker, occurrence_utc, window_end)
            if worker_conflict:
                needs_assignment_reason = "worker_conflict"
            else:
                assigned_worker_id = worker.worker_id

        booking = Booking(
            org_id=org_id,
            client_id=series.client_id,
            address_id=series.address_id,
            team_id=team_id,
            assigned_worker_id=assigned_worker_id,
            starts_at=occurrence_utc,
            duration_minutes=series.duration_minutes,
            planned_minutes=series.duration_minutes,
            status="PENDING",
            scheduled_date=occurrence_local.date(),
            deposit_required=False,
            deposit_cents=None,
            deposit_policy=[],
            deposit_status=None,
            base_charge_cents=0,
            refund_total_cents=0,
            credit_note_total_cents=0,
            recurring_series_id=series.series_id,
        )
        session.add(booking)
        await session.flush()

        entry = schemas.OccurrenceReport(
            scheduled_for=occurrence_utc,
            booking_id=booking.booking_id,
            reason=needs_assignment_reason,
        )
        if needs_assignment_reason:
            needs_assignment.append(entry)
        else:
            created.append(entry)

    horizon_end_utc = horizon_end_local.astimezone(timezone.utc)
    next_local = _next_occurrence(series, horizon_end_local + timedelta(seconds=1), org_tz)
    series.next_run_at = next_local.astimezone(timezone.utc) if next_local else None
    await session.commit()
    await session.refresh(series)

    report = SeriesGenerationReport(
        created=created,
        needs_assignment=needs_assignment,
        skipped=skipped,
        conflicted=conflicted,
        horizon_end=horizon_end_utc,
        next_run_at=series.next_run_at,
    )
    return series, report
