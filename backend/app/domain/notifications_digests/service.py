from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.feature_modules import service as feature_service
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, Payment
from app.domain.notifications_center import service as notifications_service
from app.domain.notifications_digests import db_models
from app.domain.org_settings import service as org_settings_service

logger = logging.getLogger(__name__)

DIGEST_DEFINITIONS = {
    "daily_summary": {
        "schedule": "daily",
        "label": "Daily summary",
    },
    "weekly_analytics": {
        "schedule": "weekly",
        "label": "Weekly analytics summary",
    },
    "monthly_report": {
        "schedule": "monthly",
        "label": "Monthly report",
    },
}

DIGEST_KEYS = list(DIGEST_DEFINITIONS.keys())


@dataclass(frozen=True)
class DigestPayload:
    digest_key: str
    subject: str
    body: str
    recipients: list[str]


def _normalize_recipients(recipients: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in recipients or []:
        email = raw.strip().lower()
        if not email or email in seen:
            continue
        normalized.append(email)
        seen.add(email)
    return normalized


async def get_or_create_digest_settings(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> list[db_models.NotificationDigestSetting]:
    result = await session.execute(
        sa.select(db_models.NotificationDigestSetting).where(
            db_models.NotificationDigestSetting.org_id == org_id
        )
    )
    existing = {record.digest_key: record for record in result.scalars()}
    created: list[db_models.NotificationDigestSetting] = []
    for digest_key in DIGEST_KEYS:
        if digest_key in existing:
            continue
        definition = DIGEST_DEFINITIONS[digest_key]
        record = db_models.NotificationDigestSetting(
            org_id=org_id,
            digest_key=digest_key,
            enabled=False,
            schedule=definition["schedule"],
            recipients=[],
        )
        session.add(record)
        created.append(record)
        existing[digest_key] = record
    if created:
        await session.flush()
    ordered = [existing[key] for key in DIGEST_KEYS if key in existing]
    return ordered


async def list_digest_settings(
    session: AsyncSession, org_id: uuid.UUID
) -> list[db_models.NotificationDigestSetting]:
    return await get_or_create_digest_settings(session, org_id)


async def apply_digest_settings_update(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    updates: list,
) -> list[db_models.NotificationDigestSetting]:
    settings = await get_or_create_digest_settings(session, org_id)
    by_key = {record.digest_key: record for record in settings}

    for update in updates:
        record = by_key.get(update.digest_key)
        if record is None:
            continue
        if update.enabled is not None:
            record.enabled = bool(update.enabled)
        if update.schedule is not None:
            record.schedule = update.schedule
        if update.recipients is not None:
            record.recipients = _normalize_recipients(update.recipients)

    await session.flush()
    return [by_key[key] for key in DIGEST_KEYS if key in by_key]


def _start_end_for_date(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min).replace(tzinfo=tz)
    end = datetime.combine(day, time.max).replace(tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _period_key_for_schedule(schedule: str, now: datetime, tz: ZoneInfo) -> str:
    localized = now.astimezone(tz)
    if schedule == "daily":
        return localized.strftime("%Y-%m-%d")
    if schedule == "weekly":
        iso_year, iso_week, _ = localized.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if schedule == "monthly":
        return localized.strftime("%Y-%m")
    raise ValueError("unknown_schedule")


async def _get_or_create_digest_state(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    digest_key: str,
) -> db_models.NotificationDigestState:
    stmt = (
        sa.select(db_models.NotificationDigestState)
        .where(
            db_models.NotificationDigestState.org_id == org_id,
            db_models.NotificationDigestState.digest_key == digest_key,
        )
        .with_for_update()
    )
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()
    if record is not None:
        return record
    record = db_models.NotificationDigestState(org_id=org_id, digest_key=digest_key)
    session.add(record)
    await session.flush()
    return record


async def _today_booking_summary(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    org_timezone: str,
    now: datetime,
) -> dict[str, int]:
    tz = ZoneInfo(org_timezone)
    today = now.astimezone(tz).date()
    start_at, end_at = _start_end_for_date(today, tz)
    stmt = (
        sa.select(Booking.status, sa.func.count())
        .where(
            Booking.org_id == org_id,
            Booking.starts_at >= start_at,
            Booking.starts_at <= end_at,
        )
        .group_by(Booking.status)
    )
    rows = await session.execute(stmt)
    counts = {status: count for status, count in rows.all()}
    total = int(sum(counts.values()))
    return {
        "total": total,
        "pending": int(counts.get("PENDING", 0)),
        "confirmed": int(counts.get("CONFIRMED", 0)),
        "done": int(counts.get("DONE", 0)),
        "cancelled": int(counts.get("CANCELLED", 0)),
    }


async def _overdue_invoice_snapshot(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    as_of_date: date,
) -> dict[str, int]:
    paid_subq = (
        sa.select(
            Payment.invoice_id.label("invoice_id"),
            sa.func.coalesce(sa.func.sum(Payment.amount_cents), 0).label("paid_cents"),
        )
        .where(Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED)
        .group_by(Payment.invoice_id)
        .subquery()
    )
    balance_expr = Invoice.total_cents - sa.func.coalesce(paid_subq.c.paid_cents, 0)
    stmt = (
        sa.select(sa.func.count(Invoice.invoice_id), sa.func.coalesce(sa.func.sum(balance_expr), 0))
        .select_from(Invoice)
        .outerjoin(paid_subq, paid_subq.c.invoice_id == Invoice.invoice_id)
        .where(
            Invoice.org_id == org_id,
            Invoice.due_date.isnot(None),
            Invoice.due_date < as_of_date,
            Invoice.status.in_(
                {
                    invoice_statuses.INVOICE_STATUS_SENT,
                    invoice_statuses.INVOICE_STATUS_PARTIAL,
                    invoice_statuses.INVOICE_STATUS_OVERDUE,
                }
            ),
        )
    )
    result = await session.execute(stmt)
    count, total_cents = result.one()
    return {"count": int(count or 0), "total_cents": int(total_cents or 0)}


async def build_digest_payload(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    digest_key: str,
    recipients: list[str],
    now: datetime,
) -> DigestPayload:
    if digest_key not in DIGEST_DEFINITIONS:
        raise ValueError("unknown_digest_key")

    org_settings = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_timezone = org_settings_service.resolve_timezone(org_settings)
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    user_key = f"digest:{digest_key}"

    urgent_events = await notifications_service.list_urgent_unread_notifications(
        session,
        org_id=org_id,
        user_key=user_key,
        limit=5,
    )
    booking_summary = await _today_booking_summary(
        session,
        org_id=org_id,
        org_timezone=org_timezone,
        now=now_utc,
    )
    overdue_snapshot = await _overdue_invoice_snapshot(
        session,
        org_id=org_id,
        as_of_date=now_utc.astimezone(ZoneInfo(org_timezone)).date(),
    )

    subject = f"{DIGEST_DEFINITIONS[digest_key]['label']} digest"
    lines = [
        f"Digest: {digest_key}",
        f"Generated at: {now_utc.isoformat()}",
        "",
        "Unread critical notifications:",
    ]
    if urgent_events:
        for event in urgent_events:
            lines.append(f"- {event.title}")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "Today's bookings summary:",
            f"- Total: {booking_summary['total']}",
            f"- Pending: {booking_summary['pending']}",
            f"- Confirmed: {booking_summary['confirmed']}",
            f"- Done: {booking_summary['done']}",
            f"- Cancelled: {booking_summary['cancelled']}",
            "",
            "Overdue invoices snapshot:",
            f"- Count: {overdue_snapshot['count']}",
            f"- Total outstanding cents: {overdue_snapshot['total_cents']}",
        ]
    )

    return DigestPayload(
        digest_key=digest_key,
        subject=subject,
        body="\n".join(lines),
        recipients=_normalize_recipients(recipients),
    )


async def run_digest_delivery(
    session: AsyncSession,
    adapter,
    *,
    schedule: str,
    now: datetime | None = None,
) -> dict[str, int]:
    now_utc = now or datetime.now(tz=timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    settings_stmt = sa.select(db_models.NotificationDigestSetting).where(
        db_models.NotificationDigestSetting.enabled.is_(True),
        db_models.NotificationDigestSetting.schedule == schedule,
    )
    result = await session.execute(settings_stmt)
    settings_rows = list(result.scalars())
    if not settings_rows:
        return {"sent": 0, "skipped": 0}

    sent = 0
    skipped = 0
    state_updates = 0
    for setting in settings_rows:
        org_settings = await org_settings_service.get_or_create_org_settings(session, setting.org_id)
        org_timezone = org_settings_service.resolve_timezone(org_settings)
        period_key = _period_key_for_schedule(schedule, now_utc, ZoneInfo(org_timezone))
        state = await _get_or_create_digest_state(
            session, org_id=setting.org_id, digest_key=setting.digest_key
        )
        if state.last_sent_period_key == period_key:
            skipped += 1
            continue
        enabled_module = await feature_service.effective_feature_enabled(
            session, setting.org_id, "module.notifications_center"
        )
        if not enabled_module:
            skipped += 1
            continue
        payload = await build_digest_payload(
            session,
            org_id=setting.org_id,
            digest_key=setting.digest_key,
            recipients=setting.recipients or [],
            now=now_utc,
        )
        if not payload.recipients:
            skipped += 1
            continue
        if adapter is None:
            logger.warning("digest_email_adapter_missing", extra={"extra": {"digest": setting.digest_key}})
            skipped += 1
            continue
        sent_for_digest = 0
        for recipient in payload.recipients:
            delivered = await adapter.send_email(recipient, payload.subject, payload.body)
            if delivered:
                sent += 1
                sent_for_digest += 1
            else:
                skipped += 1
        if sent_for_digest:
            state.last_sent_at = now_utc
            state.last_sent_period_key = period_key
            state_updates += 1
    if state_updates:
        await session.commit()
    return {"sent": sent, "skipped": skipped}
