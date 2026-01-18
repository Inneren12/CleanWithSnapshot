from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feature_modules import service as feature_service
from app.domain.leads.db_models import Lead
from app.domain.leads_nurture.db_models import (
    NurtureCampaign,
    NurtureEnrollment,
    NurtureStep,
    NurtureStepLog,
)
from app.domain.leads_nurture.statuses import (
    NurtureChannel,
    NurtureEnrollmentStatus,
    NurtureStepLogStatus,
)
from app.domain.message_templates import service as message_template_service
from app.domain.notifications import email_service
from app.domain.org_settings import service as org_settings_service
from app.infra.communication import NoopCommunicationAdapter, TwilioCommunicationAdapter
from app.infra.email import EmailAdapter, NoopEmailAdapter
from app.settings import settings

logger = logging.getLogger(__name__)

DAY_KEYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def _parse_local_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        hour_str, minute_str = value.split(":", 1)
        return time(hour=int(hour_str), minute=int(minute_str))
    except (ValueError, TypeError):
        return None


def _within_business_hours(local_dt: datetime, business_hours: dict) -> bool:
    day_key = DAY_KEYS[local_dt.weekday()]
    config = business_hours.get(day_key) or {}
    if not config.get("enabled", False):
        return False
    start = _parse_local_time(config.get("start"))
    end = _parse_local_time(config.get("end"))
    if not start or not end:
        return False
    now_time = local_dt.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= now_time <= end
    return now_time >= start or now_time <= end


def _next_business_start(local_dt: datetime, business_hours: dict) -> datetime:
    for day_offset in range(0, 8):
        candidate_date = local_dt.date() + timedelta(days=day_offset)
        day_key = DAY_KEYS[candidate_date.weekday()]
        config = business_hours.get(day_key) or {}
        if not config.get("enabled", False):
            continue
        start = _parse_local_time(config.get("start"))
        if not start:
            continue
        start_local = datetime.combine(candidate_date, start, tzinfo=local_dt.tzinfo)
        if day_offset == 0 and start_local <= local_dt:
            continue
        return start_local
    return local_dt + timedelta(hours=1)


def _resolve_message(step: NurtureStep, templates: dict[str, str]) -> tuple[str, str] | None:
    payload = step.payload_json or {}
    subject = payload.get("subject") or "Cleaning follow-up"
    body = payload.get("body")
    if not body and step.template_key:
        body = templates.get(step.template_key)
    if not body:
        return None
    return subject, body


async def _load_due_logs(
    session: AsyncSession,
    *,
    now: datetime,
    org_id: uuid.UUID | None = None,
) -> list[tuple[NurtureStepLog, NurtureEnrollment, NurtureCampaign, NurtureStep]]:
    lookback = timedelta(hours=settings.leads_nurture_runner_lookback_hours)
    window_start = now - lookback
    stmt = (
        sa.select(NurtureStepLog, NurtureEnrollment, NurtureCampaign, NurtureStep)
        .join(NurtureEnrollment, NurtureStepLog.enrollment_id == NurtureEnrollment.enrollment_id)
        .join(
            NurtureCampaign,
            sa.and_(
                NurtureEnrollment.campaign_id == NurtureCampaign.campaign_id,
                NurtureCampaign.org_id == NurtureStepLog.org_id,
            ),
        )
        .join(
            NurtureStep,
            sa.and_(
                NurtureStep.campaign_id == NurtureCampaign.campaign_id,
                NurtureStep.step_index == NurtureStepLog.step_index,
                NurtureStep.org_id == NurtureStepLog.org_id,
            ),
        )
        .where(
            NurtureStepLog.status == NurtureStepLogStatus.planned,
            NurtureStepLog.sent_at.is_(None),
            NurtureStepLog.planned_at <= now,
            NurtureStepLog.planned_at >= window_start,
            NurtureEnrollment.status == NurtureEnrollmentStatus.active,
            NurtureCampaign.enabled.is_(True),
            NurtureStep.active.is_(True),
        )
        .order_by(NurtureStepLog.planned_at.asc(), NurtureStepLog.step_index.asc())
        .limit(settings.leads_nurture_runner_batch_size)
    )
    if org_id:
        stmt = stmt.where(NurtureStepLog.org_id == org_id)
    bind = session.get_bind()
    dialect = bind.dialect.name if bind else ""
    if dialect == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    result = await session.execute(stmt)
    return list(result.all())


async def run_leads_nurture_runner(
    session: AsyncSession,
    email_adapter: EmailAdapter | NoopEmailAdapter | None,
    communication_adapter: TwilioCommunicationAdapter | NoopCommunicationAdapter | None,
    *,
    now: datetime | None = None,
    org_id: uuid.UUID | None = None,
) -> dict[str, int]:
    now = now or datetime.now(tz=timezone.utc)
    due_logs = await _load_due_logs(session, now=now, org_id=org_id)
    if not due_logs:
        return {"sent": 0, "skipped": 0, "deferred": 0, "failed": 0, "gated": 0}

    sent = 0
    skipped = 0
    deferred = 0
    failed = 0
    gated = 0

    feature_cache: dict[uuid.UUID, bool] = {}
    settings_cache: dict[uuid.UUID, tuple[ZoneInfo, dict]] = {}
    template_cache: dict[uuid.UUID, dict[str, str]] = {}

    for log, enrollment, campaign, step in due_logs:
        org_key = log.org_id
        if org_key not in feature_cache:
            module_enabled = await feature_service.effective_feature_enabled(
                session, org_key, "module.leads"
            )
            nurture_enabled = await feature_service.effective_feature_enabled(
                session, org_key, "leads.nurture"
            )
            feature_cache[org_key] = bool(module_enabled and nurture_enabled)
        if not feature_cache[org_key]:
            gated += 1
            continue

        if org_key not in settings_cache:
            org_settings = await org_settings_service.get_or_create_org_settings(session, org_key)
            tz_name = org_settings_service.resolve_timezone(org_settings)
            try:
                org_tz = ZoneInfo(tz_name)
            except Exception:  # noqa: BLE001
                org_tz = ZoneInfo(org_settings_service.DEFAULT_TIMEZONE)
            business_hours = org_settings_service.resolve_business_hours(org_settings)
            settings_cache[org_key] = (org_tz, business_hours)
        org_tz, business_hours = settings_cache[org_key]
        now_local = now.astimezone(org_tz)

        if not _within_business_hours(now_local, business_hours):
            next_start = _next_business_start(now_local, business_hours)
            log.planned_at = next_start.astimezone(timezone.utc)
            log.error = "quiet_hours"
            await session.commit()
            deferred += 1
            continue

        lead = await session.scalar(
            sa.select(Lead).where(Lead.org_id == log.org_id, Lead.lead_id == enrollment.lead_id)
        )
        if not lead:
            log.status = NurtureStepLogStatus.skipped
            log.sent_at = now
            log.error = "missing_lead"
            await session.commit()
            skipped += 1
            continue

        if org_key not in template_cache:
            templates = await message_template_service.list_templates(session, org_id=org_key)
            template_cache[org_key] = {template.name: template.body for template in templates}
        templates = template_cache[org_key]

        if step.channel == NurtureChannel.log_only:
            log.status = NurtureStepLogStatus.sent
            log.sent_at = now
            log.error = "log_only"
            await session.commit()
            sent += 1
            continue

        message = _resolve_message(step, templates)
        if not message:
            log.status = NurtureStepLogStatus.failed
            log.sent_at = now
            log.error = "missing_message"
            await session.commit()
            failed += 1
            continue

        subject, body = message
        if step.channel == NurtureChannel.email:
            if not lead.email:
                log.status = NurtureStepLogStatus.skipped
                log.sent_at = now
                log.error = "missing_email"
                await session.commit()
                skipped += 1
                continue
            if await email_service.is_unsubscribed(
                session, lead.email, email_service.SCOPE_MARKETING, org_key
            ):
                log.status = NurtureStepLogStatus.skipped
                log.sent_at = now
                log.error = "unsubscribed"
                await session.commit()
                skipped += 1
                continue

            unsubscribe_url = email_service.build_unsubscribe_link(
                lead.email, email_service.SCOPE_MARKETING, org_key
            )
            headers = {"List-Unsubscribe": f"<{unsubscribe_url}>"} if unsubscribe_url else None
            body = email_service.append_unsubscribe_footer(body, unsubscribe_url)

            adapter_disabled = settings.email_mode == "off" or isinstance(
                email_adapter, NoopEmailAdapter
            )
            if adapter_disabled or email_adapter is None:
                log.status = NurtureStepLogStatus.skipped
                log.sent_at = now
                log.error = "email_disabled"
                await session.commit()
                skipped += 1
                continue
            try:
                delivered = await email_adapter.send_email(
                    recipient=lead.email,
                    subject=subject,
                    body=body,
                    headers=headers,
                )
            except Exception as exc:  # noqa: BLE001
                log.status = NurtureStepLogStatus.failed
                log.sent_at = now
                log.error = f"email_error:{type(exc).__name__}"
                await session.commit()
                failed += 1
                continue

            if delivered:
                log.status = NurtureStepLogStatus.sent
                log.sent_at = now
                log.error = None
                await session.commit()
                sent += 1
            else:
                log.status = NurtureStepLogStatus.skipped
                log.sent_at = now
                log.error = "email_disabled"
                await session.commit()
                skipped += 1
            continue

        if step.channel == NurtureChannel.sms:
            if not lead.phone:
                log.status = NurtureStepLogStatus.skipped
                log.sent_at = now
                log.error = "missing_phone"
                await session.commit()
                skipped += 1
                continue
            adapter_disabled = settings.sms_mode != "twilio" or isinstance(
                communication_adapter, NoopCommunicationAdapter
            )
            if adapter_disabled or communication_adapter is None:
                log.status = NurtureStepLogStatus.skipped
                log.sent_at = now
                log.error = "sms_disabled"
                await session.commit()
                skipped += 1
                continue
            try:
                result = await communication_adapter.send_sms(to_number=lead.phone, body=body)
            except Exception as exc:  # noqa: BLE001
                log.status = NurtureStepLogStatus.failed
                log.sent_at = now
                log.error = f"sms_error:{type(exc).__name__}"
                await session.commit()
                failed += 1
                continue
            if result.status == "sent":
                log.status = NurtureStepLogStatus.sent
                log.sent_at = now
                log.error = None
                await session.commit()
                sent += 1
            elif result.error_code in {"sms_disabled", "twilio_not_configured"}:
                log.status = NurtureStepLogStatus.skipped
                log.sent_at = now
                log.error = result.error_code
                await session.commit()
                skipped += 1
            else:
                log.status = NurtureStepLogStatus.failed
                log.sent_at = now
                log.error = result.error_code or "sms_failed"
                await session.commit()
                failed += 1
            continue

        logger.warning(
            "nurture_unknown_channel",
            extra={"extra": {"org_id": str(org_key), "step_index": step.step_index}},
        )
        log.status = NurtureStepLogStatus.failed
        log.sent_at = now
        log.error = "unknown_channel"
        await session.commit()
        failed += 1

    return {
        "sent": sent,
        "skipped": skipped,
        "deferred": deferred,
        "failed": failed,
        "gated": gated,
    }
