from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
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
