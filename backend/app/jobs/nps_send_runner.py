from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feature_modules import service as feature_service
from app.domain.nps import send_service
from app.domain.nps import service as nps_service
from app.domain.outbox.db_models import OutboxEvent
from app.domain.notifications import email_service
from app.infra.communication import NoopCommunicationAdapter
from app.infra.email import NoopEmailAdapter
from app.settings import settings

logger = logging.getLogger(__name__)

PENDING_STATUSES = {"pending", "retry"}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _next_attempt(attempt: int) -> datetime:
    delay = settings.outbox_base_backoff_seconds * max(1, 2 ** max(0, attempt - 1))
    return _now() + timedelta(seconds=delay)


def _email_disabled(adapter: object | None) -> bool:
    if settings.email_mode == "off":
        return True
    return isinstance(adapter, NoopEmailAdapter)


def _sms_disabled(adapter: object | None) -> bool:
    if settings.sms_mode != "twilio":
        return True
    return adapter is None or isinstance(adapter, NoopCommunicationAdapter)


def _render_nps_sms(lead_name: str, survey_link: str) -> str:
    return f"Hi {lead_name}, how did we do? Share a quick score: {survey_link}"


def _mark_sent(event: OutboxEvent, *, reason: str | None = None) -> None:
    event.status = "sent"
    event.next_attempt_at = None
    event.last_error = reason


def _mark_retry(event: OutboxEvent, *, error: str | None = None) -> None:
    attempts = event.attempts or 0
    if attempts >= settings.outbox_max_attempts:
        event.status = "dead"
        event.next_attempt_at = None
    else:
        event.status = "retry"
        event.next_attempt_at = _next_attempt(attempts)
    event.last_error = error or "failed"


async def _process_event(
    session: AsyncSession,
    event: OutboxEvent,
    *,
    email_adapter: object | None,
    communication_adapter: object | None,
    base_url: str | None,
    period_start: datetime,
) -> tuple[bool, str | None]:
    attempts = (event.attempts or 0) + 1
    event.attempts = attempts

    booking_id = (event.payload_json or {}).get("booking_id")
    if not booking_id:
        _mark_sent(event, reason="missing_booking_id")
        return False, "missing_booking_id"

    if not base_url:
        _mark_sent(event, reason="missing_base_url")
        return False, "missing_base_url"

    booking, lead = await send_service.load_booking_and_lead(
        session, booking_id=booking_id, org_id=event.org_id
    )
    if booking is None:
        _mark_sent(event, reason="booking_not_found")
        return False, "booking_not_found"

    enabled = await feature_service.effective_feature_enabled(
        session, booking.org_id, "quality.nps"
    )
    if not enabled:
        _mark_sent(event, reason="feature_disabled")
        return False, "feature_disabled"

    gate = await send_service.evaluate_nps_send_gate(
        session, booking=booking, lead=lead, period_start=period_start
    )
    if not gate.allowed:
        _mark_sent(event, reason=gate.reason)
        return False, gate.reason

    if lead is None:
        _mark_sent(event, reason="lead_missing")
        return False, "lead_missing"

    token = await nps_service.issue_nps_token(session, booking=booking)
    survey_link = f"{base_url}/nps/{booking.booking_id}?token={token.token}"

    if lead.email and not _email_disabled(email_adapter):
        queued = await email_service.send_nps_survey_email(
            session,
            None,
            booking,
            lead,
            survey_link,
        )
        if queued:
            _mark_sent(event)
            return True, None
        _mark_retry(event, error="email_enqueue_failed")
        return False, "email_enqueue_failed"

    if lead.phone and not _sms_disabled(communication_adapter):
        try:
            result = await communication_adapter.send_sms(
                to_number=lead.phone,
                body=_render_nps_sms(lead.name, survey_link),
            )
        except Exception as exc:  # noqa: BLE001
            _mark_retry(event, error=type(exc).__name__)
            return False, type(exc).__name__
        if result.status == "sent":
            _mark_sent(event)
            return True, None
        if result.error_code in {"sms_disabled", "twilio_not_configured"}:
            _mark_sent(event, reason=result.error_code)
            return False, result.error_code
        _mark_retry(event, error=result.error_code or "sms_failed")
        return False, result.error_code or "sms_failed"

    if _email_disabled(email_adapter):
        _mark_sent(event, reason="email_disabled")
        return False, "email_disabled"
    if _sms_disabled(communication_adapter):
        _mark_sent(event, reason="sms_disabled")
        return False, "sms_disabled"

    _mark_sent(event, reason="no_delivery_channel")
    return False, "no_delivery_channel"


async def run_nps_send_runner(
    session: AsyncSession,
    email_adapter: object | None,
    communication_adapter: object | None,
    *,
    base_url: str | None = None,
) -> dict[str, int]:
    resolved_base = send_service.resolve_public_base_url(base_url)
    period_start = send_service.nps_send_period_start()
    now = _now()

    result = await session.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.kind == send_service.NPS_OUTBOX_KIND,
            OutboxEvent.status.in_(PENDING_STATUSES),
            OutboxEvent.next_attempt_at <= now,
        )
        .order_by(OutboxEvent.created_at)
        .limit(settings.job_outbox_batch_size)
    )
    events = result.scalars().all()

    sent = 0
    skipped = 0
    for event in events:
        delivered, reason = await _process_event(
            session,
            event,
            email_adapter=email_adapter,
            communication_adapter=communication_adapter,
            base_url=resolved_base,
            period_start=period_start,
        )
        if delivered:
            sent += 1
        else:
            skipped += 1
            logger.info(
                "nps_send_skipped",
                extra={
                    "extra": {
                        "event_id": str(event.event_id),
                        "reason": reason,
                    }
                },
            )
    if events:
        await session.commit()
    return {"sent": sent, "skipped": skipped}
