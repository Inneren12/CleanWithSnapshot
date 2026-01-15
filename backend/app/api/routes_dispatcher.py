from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, require_dispatch
from app.api.problem_details import problem_details
from app.api.org_context import require_org_context
from app.dependencies import get_db_session
from app.domain.admin_audit import service as audit_service
from app.domain.bookings import service as booking_service
from app.domain.bookings.db_models import Booking, BookingWorker
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.dispatcher import context as dispatcher_context
from app.domain.dispatcher import route_estimates
from app.domain.dispatcher import schemas
from app.domain.dispatcher import service as dispatcher_service
from app.domain.feature_modules import service as feature_service
from app.domain.ops import service as ops_service
from app.domain.workers.db_models import Worker
from app.infra.communication import resolve_app_communication_adapter

logger = logging.getLogger(__name__)

router = APIRouter()


async def _require_schedule_enabled(
    request: Request, session: AsyncSession, org_id: uuid.UUID
):
    enabled = await feature_service.effective_feature_enabled(session, org_id, "module.schedule")
    if not enabled:
        return problem_details(
            request=request,
            status=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail="Disabled by org settings",
        )
    return None


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
    lat = getattr(address, "lat", None)
    lng = getattr(address, "lng", None)
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
            lat=lat,
            lng=lng,
            zone=dispatcher_service.zone_for_point(lat, lng),
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
    request: Request,
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
    guard = await _require_schedule_enabled(request, session, org_id)
    if guard:
        return guard
    try:
        ZoneInfo(tz)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid timezone") from exc
    try:
        dispatcher_service.resolve_zone(zone)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid zone") from exc

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
    "/v1/admin/dispatcher/stats",
    response_model=schemas.DispatcherStatsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_dispatcher_stats(
    request: Request,
    stats_date: date = Query(..., alias="date", description="Target date in YYYY-MM-DD"),
    tz: str = Query("America/Edmonton", description="IANA timezone, e.g. America/Edmonton"),
    zone: str | None = Query(None, description="Optional zone filter"),
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherStatsResponse:
    """Fetch dispatcher stats for a single day.

    Revenue is derived from succeeded payments received during the day window (cents).
    """
    guard = await _require_schedule_enabled(request, session, org_id)
    if guard:
        return guard
    try:
        ZoneInfo(tz)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid timezone") from exc
    try:
        dispatcher_service.resolve_zone(zone)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid zone") from exc

    result = await dispatcher_service.fetch_dispatcher_stats(
        session,
        org_id=org_id,
        target_date=stats_date,
        tz_name=tz,
        zone=zone,
    )
    return schemas.DispatcherStatsResponse(
        done_count=result.done_count,
        in_progress_count=result.in_progress_count,
        planned_count=result.planned_count,
        avg_duration_hours=result.avg_duration_hours,
        revenue_today=result.revenue_today_cents,
    )


@router.get(
    "/v1/admin/dispatcher/alerts",
    response_model=schemas.DispatcherAlertsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_dispatcher_alerts(
    request: Request,
    board_date: date = Query(..., alias="date", description="Target date in YYYY-MM-DD"),
    tz: str = Query("America/Edmonton", description="IANA timezone, e.g. America/Edmonton"),
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherAlertsResponse:
    """Fetch dispatcher alerts for a single day.

    Requires: DISPATCH permission (dispatcher/admin/owner roles).
    """
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

    adapter = resolve_app_communication_adapter(request)
    await dispatcher_service.send_critical_alert_sms(
        session,
        org_id=org_id,
        identity=identity,
        alerts=result.alerts,
        adapter=adapter,
    )

    return schemas.DispatcherAlertsResponse(alerts=result.alerts)


@router.get(
    "/v1/admin/dispatcher/context",
    response_model=schemas.DispatcherContextResponse,
    status_code=status.HTTP_200_OK,
)
async def get_dispatcher_context(
    tz: str = Query("America/Edmonton", description="IANA timezone, e.g. America/Edmonton"),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherContextResponse:
    """Fetch dispatcher context (weather + traffic risk)."""
    try:
        ZoneInfo(tz)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid timezone") from exc

    return await dispatcher_context.fetch_dispatcher_context(tz)


@router.post(
    "/v1/admin/dispatcher/alerts/ack",
    response_model=schemas.DispatcherAlertAckResponse,
    status_code=status.HTTP_200_OK,
)
async def ack_dispatcher_alert(
    payload: schemas.DispatcherAlertAckRequest,
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherAlertAckResponse:
    del identity
    await dispatcher_service.acknowledge_dispatcher_alert(
        session,
        org_id=org_id,
        alert_id=payload.alert_id,
    )
    await session.commit()
    return schemas.DispatcherAlertAckResponse(status="ok")


@router.post(
    "/v1/admin/dispatcher/routes/estimate",
    response_model=schemas.DispatcherRouteEstimateResponse,
    status_code=status.HTTP_200_OK,
)
async def estimate_dispatcher_route(
    payload: schemas.DispatcherRouteEstimateRequest,
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherRouteEstimateResponse:
    """Estimate travel distance/time between two coordinates.

    Requires: DISPATCH permission (dispatcher/admin/owner roles).
    """
    del org_id
    del identity
    estimate, cached = await route_estimates.estimate_route(
        origin_lat=payload.origin.lat,
        origin_lng=payload.origin.lng,
        dest_lat=payload.dest.lat,
        dest_lng=payload.dest.lng,
        depart_at=payload.depart_at,
        mode=payload.mode,
    )
    base_duration_min = estimate.duration_in_traffic_min or estimate.duration_min
    adjusted_duration_min, adjustments = dispatcher_service.apply_eta_adjustments(
        base_duration_min=base_duration_min,
        depart_at=payload.depart_at,
        zone=dispatcher_service.zone_for_point(payload.dest.lat, payload.dest.lng),
        lat=payload.dest.lat,
        lng=payload.dest.lng,
    )
    return schemas.DispatcherRouteEstimateResponse(
        distance_km=estimate.distance_km,
        duration_min=adjusted_duration_min,
        duration_in_traffic_min=estimate.duration_in_traffic_min,
        provider=estimate.provider,
        cached=cached,
        base_duration_min=base_duration_min,
        adjustments=adjustments,
    )


@router.get(
    "/v1/admin/dispatcher/assign/suggest",
    response_model=schemas.DispatcherAssignmentSuggestionsResponse,
    status_code=status.HTTP_200_OK,
)
async def suggest_dispatcher_assignments(
    booking_id: str = Query(..., description="Booking ID"),
    limit: int = Query(5, ge=1, le=25),
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherAssignmentSuggestionsResponse:
    """Suggest workers for a booking assignment.

    Requires: DISPATCH permission (dispatcher/admin/owner roles).
    """
    del identity
    try:
        result = await dispatcher_service.fetch_dispatcher_assignment_suggestions(
            session,
            org_id=org_id,
            booking_id=booking_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found") from exc

    return schemas.DispatcherAssignmentSuggestionsResponse(suggestions=result.suggestions)


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

    duration_minutes = booking.duration_minutes or ops_service.DEFAULT_SLOT_DURATION_MINUTES
    ends_at = booking.starts_at + timedelta(minutes=duration_minutes)
    try:
        conflicts = await ops_service.check_schedule_conflicts(
            session,
            org_id,
            starts_at=booking.starts_at,
            ends_at=ends_at,
            team_id=booking.team_id,
            booking_id=booking.booking_id,
            worker_id=payload.worker_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "conflict_with_existing_booking", "conflicts": conflicts},
        )

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
    "/v1/admin/dispatcher/notify",
    response_model=schemas.DispatcherNotifyResponse,
    status_code=status.HTTP_200_OK,
)
async def notify_dispatcher_target(
    payload: schemas.DispatcherNotifyRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherNotifyResponse:
    adapter = resolve_app_communication_adapter(request)
    try:
        audit, result = await dispatcher_service.send_dispatcher_notification(
            session,
            org_id=org_id,
            payload=payload,
            admin_user_id=identity.username,
            adapter=adapter,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await session.commit()
    return schemas.DispatcherNotifyResponse(
        audit_id=audit.audit_id,
        status=result.status,
        error_code=result.error_code,
        provider_msg_id=result.provider_msg_id,
        sent_at=audit.sent_at,
    )


@router.get(
    "/v1/admin/dispatcher/notify/audit",
    response_model=schemas.DispatcherNotifyAuditResponse,
    status_code=status.HTTP_200_OK,
)
async def list_dispatcher_notify_audits(
    booking_id: str = Query(..., description="Booking id"),
    limit: int = Query(5, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    org_id=Depends(require_org_context),
    identity: AdminIdentity = Depends(require_dispatch),
) -> schemas.DispatcherNotifyAuditResponse:
    del identity
    audits = await dispatcher_service.fetch_dispatcher_notification_audits(
        session, org_id=org_id, booking_id=booking_id, limit=limit
    )
    return schemas.DispatcherNotifyAuditResponse(
        audits=[
            schemas.DispatcherNotifyAuditEntry(
                audit_id=audit.audit_id,
                booking_id=audit.booking_id,
                target=audit.target,
                channel=audit.channel,
                template_id=audit.template_id,
                admin_user_id=audit.admin_user_id,
                status=audit.status,
                error_code=audit.error_code,
                provider_msg_id=audit.provider_msg_id,
                sent_at=audit.sent_at,
            )
            for audit in audits
        ]
    )


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
