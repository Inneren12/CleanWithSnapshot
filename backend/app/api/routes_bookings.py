from datetime import timedelta
import uuid

import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import require_admin
from app.api.problem_details import problem_details
from app.api import entitlements
from app.domain.saas import billing_service
from app.domain.analytics.service import (
    EventType,
    estimated_duration_from_booking,
    estimated_revenue_from_lead,
    log_event,
)
from app.domain.bookings.db_models import Booking, Team, TeamBlackout, TeamWorkingHours
from app.dependencies import get_db_session
from app.domain.bookings import schemas as booking_schemas
from app.domain.bookings import service as booking_service
from app.domain.leads.db_models import Lead
from app.domain.clients import service as client_service
from app.domain.notifications import email_service
from app.infra import stripe_client as stripe_infra
from app.infra.stripe_idempotency import make_stripe_idempotency_key
from app.infra.captcha import log_captcha_event, log_captcha_unavailable, verify_turnstile
from app.infra.email import resolve_app_email_adapter
from app.settings import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _stripe_client(request: Request):
    if getattr(request.app.state, "stripe_client", None):
        return request.app.state.stripe_client
    services = getattr(request.app.state, "services", None)
    if services and getattr(services, "stripe_client", None):
        return services.stripe_client
    return stripe_infra.resolve_client(request.app.state)


def _validate_lead_contact(lead: Lead | None) -> None:
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    missing = []
    if not lead.name or not lead.name.strip():
        missing.append("full_name")
    if not lead.phone or not lead.phone.strip():
        missing.append("phone")
    if not lead.address or not lead.address.strip():
        missing.append("address")
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required fields: {', '.join(missing)}",
        )


@router.get("/v1/slots", response_model=booking_schemas.SlotAvailabilityResponse)
async def get_slots(
    query: booking_schemas.SlotQuery = Depends(),
    session: AsyncSession = Depends(get_db_session),
) -> booking_schemas.SlotAvailabilityResponse:
    slot_result = await booking_service.suggest_slots(
        query.date,
        query.duration_minutes,
        session,
        time_window=query.time_window(),
        service_type=query.service_type.value if query.service_type else None,
    )
    return booking_schemas.SlotAvailabilityResponse(
        date=query.date,
        duration_minutes=query.duration_minutes,
        slots=slot_result.slots,
        clarifier=slot_result.clarifier,
    )


@router.get(
    "/v1/admin/working-hours",
    response_model=list[booking_schemas.WorkingHoursResponse],
)
async def list_working_hours(
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    role: str = Depends(require_admin),
) -> list[booking_schemas.WorkingHoursResponse]:
    del role
    org_id = entitlements.resolve_org_id(http_request)
    result = await session.execute(
        select(TeamWorkingHours)
        .join(Team, Team.team_id == TeamWorkingHours.team_id)
        .where(Team.org_id == org_id)
    )
    records = result.scalars().all()
    return [
        booking_schemas.WorkingHoursResponse(
            id=record.id,
            team_id=record.team_id,
            day_of_week=record.day_of_week,
            start_time=record.start_time,
            end_time=record.end_time,
        )
        for record in records
    ]


@router.post(
    "/v1/admin/working-hours",
    response_model=booking_schemas.WorkingHoursResponse,
)
async def upsert_working_hours(
    payload: booking_schemas.WorkingHoursUpdateRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    role: str = Depends(require_admin),
) -> booking_schemas.WorkingHoursResponse:
    del role
    org_id = entitlements.resolve_org_id(http_request)
    team = (
        await session.execute(
            select(Team).where(Team.team_id == payload.team_id, Team.org_id == org_id)
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    existing_result = await session.execute(
        select(TeamWorkingHours)
        .join(Team, Team.team_id == TeamWorkingHours.team_id)
        .where(
            TeamWorkingHours.team_id == payload.team_id,
            TeamWorkingHours.day_of_week == payload.day_of_week,
            Team.org_id == org_id,
        )
    )
    record = existing_result.scalar_one_or_none()
    if record:
        record.start_time = payload.start_time
        record.end_time = payload.end_time
    else:
        record = TeamWorkingHours(
            team_id=payload.team_id,
            day_of_week=payload.day_of_week,
            start_time=payload.start_time,
            end_time=payload.end_time,
        )
        session.add(record)

    await session.commit()
    await session.refresh(record)
    return booking_schemas.WorkingHoursResponse(
        id=record.id,
        team_id=record.team_id,
        day_of_week=record.day_of_week,
        start_time=record.start_time,
        end_time=record.end_time,
    )


@router.get(
    "/v1/admin/blackouts", response_model=list[booking_schemas.BlackoutResponse]
)
async def list_blackouts(
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    role: str = Depends(require_admin),
) -> list[booking_schemas.BlackoutResponse]:
    del role
    org_id = entitlements.resolve_org_id(http_request)
    result = await session.execute(
        select(TeamBlackout)
        .join(Team, Team.team_id == TeamBlackout.team_id)
        .where(Team.org_id == org_id)
    )
    records = result.scalars().all()
    return [
        booking_schemas.BlackoutResponse(
            id=record.id,
            team_id=record.team_id,
            starts_at=record.starts_at,
            ends_at=record.ends_at,
            reason=record.reason,
        )
        for record in records
    ]


@router.post(
    "/v1/admin/blackouts", response_model=booking_schemas.BlackoutResponse
)
async def create_blackout(
    payload: booking_schemas.BlackoutCreateRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    role: str = Depends(require_admin),
) -> booking_schemas.BlackoutResponse:
    del role
    org_id = entitlements.resolve_org_id(http_request)
    team = (
        await session.execute(
            select(Team).where(Team.team_id == payload.team_id, Team.org_id == org_id)
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    blackout = TeamBlackout(
        team_id=payload.team_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        reason=payload.reason,
    )
    session.add(blackout)
    await session.commit()
    await session.refresh(blackout)
    return booking_schemas.BlackoutResponse(
        id=blackout.id,
        team_id=blackout.team_id,
        starts_at=blackout.starts_at,
        ends_at=blackout.ends_at,
        reason=blackout.reason,
    )


@router.delete("/v1/admin/blackouts/{blackout_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blackout(
    blackout_id: int,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    role: str = Depends(require_admin),
) -> None:
    del role
    org_id = entitlements.resolve_org_id(http_request)
    blackout = (
        await session.execute(
            select(TeamBlackout)
            .join(Team, Team.team_id == TeamBlackout.team_id)
            .where(TeamBlackout.id == blackout_id, Team.org_id == org_id)
        )
    ).scalar_one_or_none()
    if blackout:
        await session.delete(blackout)
        await session.commit()
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blackout not found")
    return None


@router.post("/v1/bookings", response_model=booking_schemas.BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    request: booking_schemas.BookingCreateRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> booking_schemas.BookingResponse:
    request_id = getattr(http_request.state, "request_id", None)
    captcha_required = settings.captcha_mode != "off" and settings.captcha_enabled
    if captcha_required:
        if settings.captcha_mode == "turnstile" and not settings.turnstile_secret_key:
            log_captcha_unavailable(
                "turnstile_secret_missing",
                request_id=request_id,
                mode=settings.captcha_mode,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="captcha_unavailable"
            )
        if not request.captcha_token:
            log_captcha_event(
                "missing_token",
                request_id=request_id,
                mode=settings.captcha_mode,
                provider=settings.captcha_mode,
            )
            raise HTTPException(status_code=422, detail="captcha_required")
        turnstile_transport = getattr(http_request.app.state, "turnstile_transport", None)
        remote_ip = http_request.client.host if http_request.client else None
        captcha_ok = await verify_turnstile(
            request.captcha_token,
            remote_ip,
            transport=turnstile_transport,
        )
        if not captcha_ok:
            log_captcha_event(
                "failed",
                request_id=request_id,
                mode=settings.captcha_mode,
                provider=settings.captcha_mode,
            )
            raise HTTPException(status_code=422, detail="captcha_failed")
        log_captcha_event(
            "success",
            request_id=request_id,
            mode=settings.captcha_mode,
            provider=settings.captcha_mode,
        )

    start = request.normalized_start()
    org_id = entitlements.resolve_org_id(http_request)
    await entitlements.require_booking_entitlement(http_request, session=session)
    if not request.lead_id:
        raise HTTPException(status_code=422, detail="lead_id is required")
    lead = await session.get(Lead, request.lead_id)
    _validate_lead_contact(lead)

    client_id: str | None = None
    if lead and lead.email:
        client_user = await client_service.get_or_create_client(
            session, lead.email, name=lead.name, commit=False
        )
        if client_user.is_blocked:
            return problem_details(
                http_request,
                status=status.HTTP_403_FORBIDDEN,
                title="Booking blocked",
                detail="Client is blocked from booking.",
            )
        client_id = client_user.client_id

    risk_assessment = await booking_service.evaluate_risk(
        session=session,
        lead=lead,
        client_id=client_id,
        starts_at=start,
        postal_code=lead.postal_code if lead else None,
    )

    deposit_decision = await booking_service.evaluate_deposit_policy(
        session=session,
        lead=lead,
        starts_at=start,
        deposit_percent=settings.deposit_percent,
        deposits_enabled=settings.deposits_enabled,
        service_type=request.service_type.value if request.service_type else None,
        force_deposit=risk_assessment.requires_deposit,
        extra_reasons=[f"risk_{risk_assessment.band.value.lower()}"]
        if risk_assessment.requires_deposit
        else None,
    )
    if deposit_decision.required and deposit_decision.deposit_cents is None:
        deposit_decision = booking_service.downgrade_deposit_requirement(
            deposit_decision, reason="deposit_estimate_unavailable"
        )
    if deposit_decision.required and not settings.stripe_secret_key:
        deposit_decision = booking_service.downgrade_deposit_requirement(
            deposit_decision, reason="stripe_unavailable"
        )

    checkout_url: str | None = None
    email_adapter = resolve_app_email_adapter(http_request)
    booking: Booking | None = None

    # ── Phase 1: call Stripe BEFORE opening any DB transaction ───────────────
    # We generate the booking_id up-front so it can be embedded in the Stripe
    # session metadata without requiring an open transaction.
    pending_booking_id = str(uuid.uuid4())
    stripe_checkout_session = None

    if deposit_decision.required and deposit_decision.deposit_cents:
        stripe_client = _stripe_client(http_request)
        metadata: dict[str, str] = {"booking_id": pending_booking_id}
        if request.lead_id:
            metadata["lead_id"] = request.lead_id
        deposit_idempotency_key = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id=pending_booking_id,
            amount_cents=deposit_decision.deposit_cents,
            currency=settings.deposit_currency,
        )
        try:
            stripe_checkout_session = await stripe_infra.call_stripe_client_method(
                stripe_client,
                "create_checkout_session",
                amount_cents=deposit_decision.deposit_cents,
                currency=settings.deposit_currency,
                success_url=settings.stripe_success_url.replace("{BOOKING_ID}", pending_booking_id),
                cancel_url=settings.stripe_cancel_url.replace("{BOOKING_ID}", pending_booking_id),
                metadata=metadata,
                idempotency_key=deposit_idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001
            deposit_decision = booking_service.downgrade_deposit_requirement(
                deposit_decision, reason="checkout_unavailable"
            )
            logger.warning(
                "stripe_checkout_creation_failed",
                extra={
                    "extra": {
                        "event": "policy_downgraded",
                        "booking_id": pending_booking_id,
                        "lead_id": request.lead_id,
                        "reason": type(exc).__name__,
                    }
                },
            )

    # ── Phase 2: write booking record inside a DB transaction ─────────────────
    # If this fails after Stripe already created a session, we compensate by
    # expiring the Stripe session (best-effort).
    try:
        transaction_ctx = session.begin_nested() if session.in_transaction() else session.begin()
        async with transaction_ctx:
            booking = await booking_service.create_booking(
                starts_at=start,
                duration_minutes=request.duration_minutes,
                lead_id=request.lead_id,
                session=session,
                org_id=org_id,
                deposit_decision=deposit_decision,
                policy_snapshot=deposit_decision.policy_snapshot,
                risk_assessment=risk_assessment,
                manage_transaction=False,
                client_id=client_id,
                lead=lead,
                service_type=request.service_type,
                booking_id=pending_booking_id,
            )

            try:
                if booking.lead_id and lead:
                    await log_event(
                        session,
                        event_type=EventType.booking_created,
                        booking=booking,
                        lead=lead,
                        estimated_revenue_cents=estimated_revenue_from_lead(lead),
                        estimated_duration_minutes=estimated_duration_from_booking(booking),
                    )
                else:
                    await log_event(
                        session,
                        event_type=EventType.booking_created,
                        booking=booking,
                        estimated_duration_minutes=estimated_duration_from_booking(booking),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "analytics_log_failed",
                    extra={
                        "extra": {
                            "event_type": "booking_created",
                            "booking_id": booking.booking_id,
                            "lead_id": booking.lead_id,
                            "reason": type(exc).__name__,
                        }
                    },
                )

            if stripe_checkout_session is not None:
                checkout_url = (
                    getattr(stripe_checkout_session, "url", None)
                    or stripe_checkout_session.get("url")
                )
                payment_intent = (
                    getattr(stripe_checkout_session, "payment_intent", None)
                    or stripe_checkout_session.get("payment_intent")
                )
                await booking_service.attach_checkout_session(
                    session,
                    booking.booking_id,
                    stripe_checkout_session.id,
                    payment_intent_id=payment_intent,
                    commit=False,
                )

        if booking is not None:
            await session.refresh(booking)
    except ValueError as exc:
        # Slot conflict or other domain validation: compensate Stripe if needed.
        if stripe_checkout_session is not None:
            try:
                stripe_client = _stripe_client(http_request)
                await stripe_infra.call_stripe_client_method(
                    stripe_client,
                    "cancel_checkout_session",
                    session_id=stripe_checkout_session.id,
                )
            except Exception as cancel_exc:  # noqa: BLE001
                logger.warning(
                    "stripe_session_cancel_failed",
                    extra={
                        "extra": {
                            "event": "compensation_failed",
                            "booking_id": pending_booking_id,
                            "lead_id": request.lead_id,
                            "stripe_session_id": stripe_checkout_session.id,
                            "reason": type(cancel_exc).__name__,
                        }
                    },
                )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception:
        # Unexpected DB failure: compensate Stripe if needed.
        if stripe_checkout_session is not None:
            try:
                stripe_client = _stripe_client(http_request)
                await stripe_infra.call_stripe_client_method(
                    stripe_client,
                    "cancel_checkout_session",
                    session_id=stripe_checkout_session.id,
                )
            except Exception as cancel_exc:  # noqa: BLE001
                logger.warning(
                    "stripe_session_cancel_failed",
                    extra={
                        "extra": {
                            "event": "compensation_failed",
                            "booking_id": pending_booking_id,
                            "lead_id": request.lead_id,
                            "stripe_session_id": stripe_checkout_session.id,
                            "reason": type(cancel_exc).__name__,
                        }
                    },
                )
        raise

    if booking.lead_id and lead:
        try:
            await email_service.send_booking_pending_email(session, email_adapter, booking, lead)
        except Exception:  # noqa: BLE001
            logger.warning(
                "booking_pending_email_failed",
                extra={"extra": {"booking_id": booking.booking_id, "lead_id": booking.lead_id}},
            )

    if entitlements.has_tenant_identity(http_request):
        await billing_service.record_usage_event(
            session,
            org_id,
            metric="booking_created",
            quantity=1,
            resource_id=booking.booking_id,
        )
    await session.commit()

    return booking_schemas.BookingResponse(
        booking_id=booking.booking_id,
        status=booking.status,
        starts_at=booking.starts_at,
        duration_minutes=booking.duration_minutes,
        deposit_required=booking.deposit_required,
        deposit_cents=booking.deposit_cents,
        deposit_policy=booking.deposit_policy,
        deposit_status=booking.deposit_status,
        checkout_url=checkout_url,
        policy_snapshot=booking.policy_snapshot,
        risk_score=booking.risk_score,
        risk_band=booking.risk_band,
        risk_reasons=booking.risk_reasons,
        cancellation_exception=booking.cancellation_exception,
        cancellation_exception_note=booking.cancellation_exception_note,
    )


@router.post("/v1/admin/cleanup", status_code=status.HTTP_202_ACCEPTED)
async def cleanup_pending_bookings(
    session: AsyncSession = Depends(get_db_session),
    role: str = Depends(require_admin),
) -> dict[str, int]:
    deleted = await booking_service.cleanup_stale_bookings(session, timedelta(minutes=30))
    return {"deleted": deleted}
