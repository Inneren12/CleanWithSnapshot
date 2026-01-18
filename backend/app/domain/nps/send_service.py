from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking, EmailEvent
from app.domain.leads.db_models import Lead
from app.domain.nps import service as nps_service
from app.domain.notifications import email_service
from app.domain.outbox.db_models import OutboxEvent
from app.domain.outbox.service import enqueue_outbox_event
from app.settings import settings

NPS_OUTBOX_KIND = "nps_send"


@dataclass(frozen=True)
class NpsSendGate:
    allowed: bool
    reason: str | None = None


def resolve_public_base_url(base_url: str | None = None) -> str | None:
    base = base_url or settings.public_base_url or settings.client_portal_base_url
    if not base:
        return None
    return base.rstrip("/")


def nps_send_period_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(tz=timezone.utc)
    return now - timedelta(days=settings.nps_send_period_days)


async def enqueue_nps_send(
    session: AsyncSession,
    *,
    org_id,
    booking_id: str,
    requested_by: str | None = None,
) -> OutboxEvent:
    payload = {"booking_id": booking_id, "requested_by": requested_by}
    dedupe_key = f"nps_send:{booking_id}"
    return await enqueue_outbox_event(
        session,
        org_id=org_id,
        kind=NPS_OUTBOX_KIND,
        payload=payload,
        dedupe_key=dedupe_key,
    )


async def _booking_already_sent(session: AsyncSession, booking_id: str) -> bool:
    stmt = (
        select(EmailEvent.event_id)
        .where(
            EmailEvent.booking_id == booking_id,
            EmailEvent.email_type == email_service.EMAIL_TYPE_NPS_SURVEY,
        )
        .limit(1)
    )
    return (await session.scalar(stmt)) is not None


async def _client_sent_within_period(
    session: AsyncSession,
    *,
    org_id,
    client_id: str,
    period_start: datetime,
) -> bool:
    stmt = (
        select(EmailEvent.event_id)
        .join(Booking, Booking.booking_id == EmailEvent.booking_id)
        .where(
            Booking.org_id == org_id,
            Booking.client_id == client_id,
            EmailEvent.email_type == email_service.EMAIL_TYPE_NPS_SURVEY,
            EmailEvent.created_at >= period_start,
        )
        .limit(1)
    )
    return (await session.scalar(stmt)) is not None


async def evaluate_nps_send_gate(
    session: AsyncSession,
    *,
    booking: Booking,
    lead: Lead | None,
    period_start: datetime,
) -> NpsSendGate:
    if booking.status != "DONE":
        return NpsSendGate(False, "booking_not_done")
    if lead is None:
        return NpsSendGate(False, "lead_missing")
    if not lead.email and not lead.phone:
        return NpsSendGate(False, "lead_missing_contact")
    response = await nps_service.get_existing_response(
        session, booking.booking_id, org_id=booking.org_id
    )
    if response is not None:
        return NpsSendGate(False, "nps_response_exists")
    if await _booking_already_sent(session, booking.booking_id):
        return NpsSendGate(False, "booking_already_sent")
    if booking.client_id and await _client_sent_within_period(
        session,
        org_id=booking.org_id,
        client_id=booking.client_id,
        period_start=period_start,
    ):
        return NpsSendGate(False, "client_period_limit")
    if lead.email and await email_service.is_unsubscribed(
        session, lead.email, email_service.SCOPE_NPS, booking.org_id
    ):
        return NpsSendGate(False, "unsubscribed")
    return NpsSendGate(True)


async def load_booking_and_lead(
    session: AsyncSession, *, booking_id: str, org_id
) -> tuple[Booking | None, Lead | None]:
    stmt = (
        select(Booking, Lead)
        .join(Lead, Lead.lead_id == Booking.lead_id, isouter=True)
        .where(Booking.booking_id == booking_id, Booking.org_id == org_id)
    )
    result = await session.execute(stmt)
    row = result.first()
    if not row:
        return None, None
    return row[0], row[1]
