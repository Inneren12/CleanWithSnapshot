import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientUser
from app.domain.nps.db_models import NpsResponse, NpsToken, SupportTicket

logger = logging.getLogger(__name__)

TICKET_STATUSES = {"OPEN", "IN_PROGRESS", "RESOLVED"}
NPS_SEGMENTS = {"promoter", "passive", "detractor"}


@dataclass
class NpsTokenResult:
    booking_id: str
    client_id: str | None
    email: str | None
    issued_at: datetime
    expires_at: datetime


def _token_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        normalized = expires_at.replace(tzinfo=timezone.utc)
    else:
        normalized = expires_at.astimezone(timezone.utc)
    return normalized < datetime.now(timezone.utc)


async def issue_nps_token(
    session: AsyncSession,
    *,
    booking: Booking,
    ttl_days: int = 30,
) -> NpsToken:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=ttl_days)
    for _ in range(5):
        token_value = secrets.token_urlsafe(32)
        token = NpsToken(
            token=token_value,
            org_id=booking.org_id,
            booking_id=booking.booking_id,
            client_id=booking.client_id,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(token)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            continue
        return token
    raise ValueError("token_generation_failed")


async def fetch_token(
    session: AsyncSession, *, token: str, booking_id: str | None = None
) -> NpsToken | None:
    stmt = select(NpsToken).where(NpsToken.token == token)
    if booking_id:
        stmt = stmt.where(NpsToken.booking_id == booking_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def fetch_token_with_booking(
    session: AsyncSession, *, token: str, booking_id: str | None = None
) -> tuple[NpsToken, Booking] | None:
    stmt = (
        select(NpsToken, Booking)
        .join(Booking, Booking.booking_id == NpsToken.booking_id)
        .where(NpsToken.token == token, Booking.org_id == NpsToken.org_id)
    )
    if booking_id:
        stmt = stmt.where(NpsToken.booking_id == booking_id)
    result = await session.execute(stmt)
    return result.first()


def verify_nps_token(token_record: NpsToken) -> NpsTokenResult:
    if _token_expired(token_record.expires_at):
        raise ValueError("token_expired")
    return NpsTokenResult(
        booking_id=token_record.booking_id,
        client_id=token_record.client_id,
        email=None,
        issued_at=token_record.created_at,
        expires_at=token_record.expires_at,
    )


async def get_existing_response_by_token(
    session: AsyncSession, token: str
) -> NpsResponse | None:
    stmt = select(NpsResponse).where(NpsResponse.token == token).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_existing_response(
    session: AsyncSession, order_id: str, *, org_id: uuid.UUID | None = None
) -> NpsResponse | None:
    stmt = (
        select(NpsResponse)
        .where(NpsResponse.order_id == order_id)
        .order_by(NpsResponse.created_at.desc())
        .limit(1)
    )
    if org_id:
        stmt = stmt.where(NpsResponse.org_id == org_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def record_response(
    session: AsyncSession,
    *,
    token_record: NpsToken,
    booking: Booking,
    score: int,
    comment: str | None,
) -> NpsResponse:
    existing = await get_existing_response_by_token(session, token_record.token)
    if existing:
        if token_record.used_at is None:
            token_record.used_at = datetime.now(timezone.utc)
        return existing

    response = NpsResponse(
        org_id=token_record.org_id,
        token=token_record.token,
        order_id=booking.booking_id,
        client_id=booking.client_id,
        score=score,
        comment=comment,
    )
    session.add(response)
    token_record.used_at = datetime.now(timezone.utc)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await get_existing_response_by_token(session, token_record.token)
        if existing:
            return existing
        raise
    logger.info(
        "nps_submitted",
        extra={
            "extra": {
                "order_id": booking.booking_id,
                "client_id": booking.client_id,
                "score": score,
            }
        },
    )
    return response


async def get_existing_ticket(session: AsyncSession, order_id: str) -> SupportTicket | None:
    stmt = select(SupportTicket).where(SupportTicket.order_id == order_id).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def ensure_ticket_for_low_score(
    session: AsyncSession,
    *,
    booking: Booking,
    score: int,
    comment: str | None,
    client: ClientUser | None,
) -> SupportTicket | None:
    existing = await get_existing_ticket(session, booking.booking_id)
    if existing:
        return existing

    subject = f"Low NPS for order {booking.booking_id}"
    body_parts = [
        f"Score: {score}",
        f"Order ID: {booking.booking_id}",
    ]
    if client and client.email:
        body_parts.append(f"Client email: {client.email}")
    if comment:
        body_parts.append("Comment: " + comment)
    body = "\n".join(body_parts)

    ticket = SupportTicket(
        order_id=booking.booking_id,
        client_id=booking.client_id,
        status="OPEN",
        priority="high" if score <= 1 else "normal",
        subject=subject,
        body=body,
    )
    session.add(ticket)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing_ticket = await get_existing_ticket(session, booking.booking_id)
        if existing_ticket:
            return existing_ticket
        raise
    logger.info(
        "ticket_created_from_nps",
        extra={
            "extra": {
                "order_id": booking.booking_id,
                "client_id": booking.client_id,
                "score": score,
            }
        },
    )
    return ticket


async def list_tickets(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    priority_filter: str | None = None,
    order_id: str | None = None,
) -> list[SupportTicket]:
    stmt = (
        select(SupportTicket)
        .join(Booking, SupportTicket.order_id == Booking.booking_id)
        .order_by(SupportTicket.created_at.desc())
    )
    if org_id:
        stmt = stmt.where(Booking.org_id == org_id)
    if status_filter:
        if status_filter not in TICKET_STATUSES:
            raise ValueError("invalid_status")
        stmt = stmt.where(SupportTicket.status == status_filter)
    if priority_filter:
        stmt = stmt.where(SupportTicket.priority == priority_filter)
    if order_id:
        stmt = stmt.where(SupportTicket.order_id == order_id)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_responses(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    start: datetime,
    end: datetime,
    segment: str | None = None,
) -> list[NpsResponse]:
    stmt = (
        select(NpsResponse)
        .where(
            NpsResponse.org_id == org_id,
            NpsResponse.created_at >= start,
            NpsResponse.created_at <= end,
        )
        .order_by(NpsResponse.created_at.desc())
    )
    if segment:
        if segment not in NPS_SEGMENTS:
            raise ValueError("invalid_segment")
        if segment == "promoter":
            stmt = stmt.where(NpsResponse.score >= 9)
        elif segment == "passive":
            stmt = stmt.where(NpsResponse.score.between(7, 8))
        else:
            stmt = stmt.where(NpsResponse.score <= 6)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_top_detractors(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    start: datetime,
    end: datetime,
    limit: int = 5,
) -> list[NpsResponse]:
    if limit < 1 or limit > 50:
        raise ValueError("invalid_limit")
    stmt = (
        select(NpsResponse)
        .where(
            NpsResponse.org_id == org_id,
            NpsResponse.created_at >= start,
            NpsResponse.created_at <= end,
            NpsResponse.score <= 6,
        )
        .order_by(NpsResponse.score.asc(), NpsResponse.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_ticket_status(
    session: AsyncSession, ticket_id: str, status: str, *, org_id: uuid.UUID | None = None
) -> SupportTicket | None:
    if status not in TICKET_STATUSES:
        raise ValueError("invalid_status")

    stmt = select(SupportTicket).join(Booking, SupportTicket.order_id == Booking.booking_id)
    if org_id:
        stmt = stmt.where(Booking.org_id == org_id)
    stmt = stmt.where(SupportTicket.id == ticket_id)
    result = await session.execute(stmt)
    ticket = result.scalar_one_or_none()
    if ticket is None:
        return None
    ticket.status = status
    await session.flush()
    return ticket
