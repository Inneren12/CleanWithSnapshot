from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.domain.analytics.db_models import EventLog
from app.domain.data_retention import RetentionCategory, enforce_retention
from app.domain.leads.db_models import Lead
from app.domain.leads.statuses import default_lead_status
from app.domain.reason_logs.db_models import ReasonLog
from app.jobs import data_retention
from app.settings import settings


def _lead_payload() -> dict:
    return {
        "org_id": settings.default_org_id,
        "name": "Retention Lead",
        "phone": "555-222-0000",
        "structured_inputs": {"beds": 1, "baths": 1},
        "estimate_snapshot": {"quote": 100},
        "pricing_config_version": "v1",
        "config_hash": "hash",
        "status": default_lead_status,
    }


@pytest.mark.anyio
async def test_retention_respects_configured_days(async_session_maker):
    original_app_days = settings.retention_application_log_days
    original_event_days = settings.retention_analytics_event_days
    original_soft_days = settings.retention_soft_deleted_days
    settings.retention_application_log_days = 10
    settings.retention_analytics_event_days = 10
    settings.retention_soft_deleted_days = 10
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add(
                ReasonLog(
                    reason_id="reason-old",
                    order_id="booking-1",
                    kind="system",
                    code="retention",
                    created_at=now - timedelta(days=12),
                )
            )
            session.add(
                ReasonLog(
                    reason_id="reason-new",
                    order_id="booking-2",
                    kind="system",
                    code="retention",
                    created_at=now - timedelta(days=2),
                )
            )
            session.add(
                EventLog(
                    event_id="event-old",
                    event_type="retention",
                    occurred_at=now - timedelta(days=12),
                )
            )
            session.add(
                EventLog(
                    event_id="event-new",
                    event_type="retention",
                    occurred_at=now - timedelta(days=2),
                )
            )
            lead_old = Lead(**_lead_payload())
            lead_old.deleted_at = now - timedelta(days=12)
            lead_new = Lead(**_lead_payload())
            lead_new.deleted_at = now - timedelta(days=2)
            session.add_all([lead_old, lead_new])
            await session.commit()

        async with async_session_maker() as session:
            result_logs = await enforce_retention(
                session, category=RetentionCategory.APPLICATION_LOGS, now=now
            )
            result_events = await enforce_retention(
                session, category=RetentionCategory.ANALYTICS_EVENTS, now=now
            )
            result_soft = await enforce_retention(
                session, category=RetentionCategory.SOFT_DELETED_ENTITIES, now=now
            )
            assert result_logs.deleted == 1
            assert result_events.deleted == 1
            assert result_soft.deleted == 1

        async with async_session_maker() as session:
            remaining_logs = await session.scalar(sa.select(sa.func.count(ReasonLog.reason_id)))
            remaining_events = await session.scalar(sa.select(sa.func.count(EventLog.event_id)))
            remaining_leads = await session.scalar(sa.select(sa.func.count(Lead.lead_id)))
            assert remaining_logs == 1
            assert remaining_events == 1
            assert remaining_leads == 1
    finally:
        settings.retention_application_log_days = original_app_days
        settings.retention_analytics_event_days = original_event_days
        settings.retention_soft_deleted_days = original_soft_days


@pytest.mark.anyio
async def test_recent_data_not_deleted(async_session_maker):
    original_app_days = settings.retention_application_log_days
    settings.retention_application_log_days = 10
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add(
                ReasonLog(
                    reason_id="reason-recent",
                    order_id="booking-3",
                    kind="system",
                    code="retention",
                    created_at=now - timedelta(days=2),
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            result = await enforce_retention(
                session, category=RetentionCategory.APPLICATION_LOGS, now=now
            )
            assert result.deleted == 0

        async with async_session_maker() as session:
            remaining_logs = await session.scalar(sa.select(sa.func.count(ReasonLog.reason_id)))
            assert remaining_logs == 1
    finally:
        settings.retention_application_log_days = original_app_days


@pytest.mark.anyio
async def test_job_idempotency(async_session_maker):
    original_app_days = settings.retention_application_log_days
    settings.retention_application_log_days = 1
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add(
                ReasonLog(
                    reason_id="reason-idempotent",
                    order_id="booking-4",
                    kind="system",
                    code="retention",
                    created_at=now - timedelta(days=5),
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            first = await data_retention.run_data_retention_daily(session)
            assert first[RetentionCategory.APPLICATION_LOGS.value] == 1

        async with async_session_maker() as session:
            second = await data_retention.run_data_retention_daily(session)
            assert second[RetentionCategory.APPLICATION_LOGS.value] == 0
    finally:
        settings.retention_application_log_days = original_app_days


@pytest.mark.anyio
async def test_categories_without_retention_config_untouched(async_session_maker):
    original_app_days = settings.retention_application_log_days
    settings.retention_application_log_days = None
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add(
                ReasonLog(
                    reason_id="reason-disabled",
                    order_id="booking-5",
                    kind="system",
                    code="retention",
                    created_at=now - timedelta(days=50),
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            result = await enforce_retention(
                session, category=RetentionCategory.APPLICATION_LOGS, now=now
            )
            assert result.status == "disabled"
            assert result.deleted == 0

        async with async_session_maker() as session:
            remaining_logs = await session.scalar(sa.select(sa.func.count(ReasonLog.reason_id)))
            assert remaining_logs == 1
    finally:
        settings.retention_application_log_days = original_app_days
