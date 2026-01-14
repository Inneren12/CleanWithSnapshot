from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, require_dispatch
from app.api.org_context import require_org_context
from app.dependencies import get_db_session
from app.domain.admin_audit import service as audit_service
from app.domain.bookings import service as booking_service
from app.domain.bookings.db_models import Booking, BookingWorker
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.dispatcher import schemas
from app.domain.dispatcher import service as dispatcher_service
from app.domain.ops import service as ops_service
from app.domain.workers.db_models import Worker

logger = logging.getLogger(__name__)

router = APIRouter()


async def _load_dispatcher_booking(
    session: AsyncSession,
    *,
    org_id,
    booking_id: str,
) -> schemas.DispatcherBoardBooking:
    stmt = (
        select(Booking, ClientUser, ClientAddress, Worker)
        .select_from(Booking)
        .join(ClientUser, ClientUser.client_id == Booking.client_id, isouter=True)
        .join(ClientAddress, ClientAddress.address_id == Booking.address_id, isouter=True)
        .join(Worker, Worker.worker_id == Booking.assigned_worker_id, isouter=True)
        .where(Booking.booking_id == booking_id, Booking.org_id == org_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    booking, client, address, worker = row
    starts_at = booking.starts_at
    duration_min = booking.duration_minutes
    updated_at = booking.updated_at or booking.created_at or datetime.now(timezone.utc)
    return schemas.DispatcherBoardBooking(
        booking_id=booking.booking_id,
        status=booking.status,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=duration_min),
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


@router.get(
    "/v1/admin/dispatcher/board",
    response_model=schemas.DispatcherBoardResponse,
    status_code=status.HTTP_200_OK,
)
async def get_dispatcher_board(
    board_date: date = Query(..., alias="date", description="Target date in YYYY-MM-DD"),
    tz: str = Query("America/Edmonton", description="IANA timezone, e.g. America/Edmonton"),
    zone: str | None = Query(None, description="Optional zone filter"),
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherBoardResponse:
    """Fetch dispatcher board bookings for a single day.

    Requires: DISPATCH permission (dispatcher/admin/owner roles).

    Returns booking timeline data, worker list, server time, and a polling-friendly
    data_version derived from the most recently updated booking in the window.
    """
    del identity
    try:
        ZoneInfo(tz)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid timezone") from exc

    result = await dispatcher_service.fetch_dispatcher_board(
        session,
        org_id=org_id,
        target_date=board_date,
        tz_name=tz,
        zone=zone,
    )

    return schemas.DispatcherBoardResponse(
        bookings=result.bookings,
        workers=result.workers,
        server_time=result.server_time,
        data_version=result.data_version,
    )


@router.get(
    "/v1/admin/dispatcher/alerts",
    response_model=schemas.DispatcherAlertsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_dispatcher_alerts(
    board_date: date = Query(..., alias="date", description="Target date in YYYY-MM-DD"),
    tz: str = Query("America/Edmonton", description="IANA timezone, e.g. America/Edmonton"),
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherAlertsResponse:
    """Fetch dispatcher alerts for a single day.

    Requires: DISPATCH permission (dispatcher/admin/owner roles).
    """
    del identity
    try:
        ZoneInfo(tz)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid timezone") from exc

    result = await dispatcher_service.fetch_dispatcher_alerts(
        session,
        org_id=org_id,
        target_date=board_date,
        tz_name=tz,
    )

    return schemas.DispatcherAlertsResponse(alerts=result.alerts)


@router.post(
    "/v1/admin/dispatcher/bookings/{booking_id}/reassign",
    response_model=schemas.DispatcherBoardBooking,
    status_code=status.HTTP_200_OK,
)
async def reassign_dispatcher_booking(
    booking_id: str,
    payload: schemas.DispatcherReassignRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherBoardBooking:
    booking_result = await session.execute(
        select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    worker_result = await session.execute(
        select(Worker).where(
            Worker.worker_id == payload.worker_id,
            Worker.org_id == org_id,
            Worker.is_active == True,  # noqa: E712
        )
    )
    worker = worker_result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    if worker.team_id != booking.team_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Worker must be on the same team")

    previous_worker_ids = (
        await session.execute(select(BookingWorker.worker_id).where(BookingWorker.booking_id == booking_id))
    ).scalars().all()
    before_state = {"assigned_worker_id": booking.assigned_worker_id, "assigned_worker_ids": previous_worker_ids}

    booking.assigned_worker_id = payload.worker_id
    await session.execute(sa.delete(BookingWorker).where(BookingWorker.booking_id == booking_id))
    session.add(BookingWorker(booking_id=booking_id, worker_id=payload.worker_id))

    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="booking_reassign",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before_state,
        after={"assigned_worker_id": payload.worker_id, "assigned_worker_ids": [payload.worker_id]},
    )
    await session.commit()
    return await _load_dispatcher_booking(session, org_id=org_id, booking_id=booking_id)


@router.post(
    "/v1/admin/dispatcher/bookings/{booking_id}/reschedule",
    response_model=schemas.DispatcherBoardBooking,
    status_code=status.HTTP_200_OK,
)
async def reschedule_dispatcher_booking(
    booking_id: str,
    payload: schemas.DispatcherRescheduleRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherBoardBooking:
    booking_result = await session.execute(
        select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    if booking.status in {"DONE", "CANCELLED"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking is no longer active")

    duration_minutes = int((payload.ends_at - payload.starts_at).total_seconds() // 60)
    if duration_minutes <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid time range")

    conflicts: list[dict] = []
    try:
        conflicts = await ops_service.check_schedule_conflicts(
            session,
            org_id,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            team_id=booking.team_id,
            booking_id=booking.booking_id,
            worker_id=booking.assigned_worker_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if conflicts and not payload.override_conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "conflict_with_existing_booking", "conflicts": conflicts},
        )

    before_state = {
        "starts_at": booking.starts_at.isoformat(),
        "duration_minutes": booking.duration_minutes,
    }
    booking = await booking_service.reschedule_booking(
        session,
        booking,
        payload.starts_at,
        duration_minutes,
        allow_conflicts=payload.override_conflicts,
    )
    after_state = {"starts_at": booking.starts_at.isoformat(), "duration_minutes": booking.duration_minutes}

    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="booking_reschedule",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before_state,
        after=after_state,
    )
    await session.commit()
    return await _load_dispatcher_booking(session, org_id=org_id, booking_id=booking_id)


@router.post(
    "/v1/admin/dispatcher/bookings/{booking_id}/status",
    response_model=schemas.DispatcherBoardBooking,
    status_code=status.HTTP_200_OK,
)
async def update_dispatcher_booking_status(
    booking_id: str,
    payload: schemas.DispatcherStatusRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherBoardBooking:
    booking_result = await session.execute(
        select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    if payload.status == "CANCELLED" and not payload.reason:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Cancellation reason is required")

    before_state = {"status": booking.status}
    booking.status = payload.status

    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="booking_status_update",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before_state,
        after={"status": payload.status, "reason": payload.reason},
    )
    await session.commit()
    return await _load_dispatcher_booking(session, org_id=org_id, booking_id=booking_id)
