from datetime import datetime, timedelta, timezone
import uuid

import pytest
import sqlalchemy as sa

from app.domain.analytics import retention as analytics_retention_service
from app.domain.analytics.db_models import Competitor, CompetitorMetric, EventLog
from app.domain.analytics.service import EventType, conversion_counts
from app.domain.leads.db_models import Lead
from app.settings import settings


def _lead_payload(now: datetime) -> dict:
    return {
        "org_id": settings.default_org_id,
        "name": "Retention Lead",
        "phone": "555-333-0000",
        "preferred_dates": ["Mon"],
        "structured_inputs": {"beds": 1, "baths": 1},
        "estimate_snapshot": {"quote": 100},
        "pricing_config_version": "v1",
        "config_hash": "hash",
        "status": "NEW",
        "referral_code": f"RET-{uuid.uuid4().hex[:8]}",
        "created_at": now,
        "updated_at": now,
    }


@pytest.mark.anyio
async def test_analytics_retention_purges_raw_events(async_session_maker):
    original_days = settings.retention_analytics_event_days
    settings.retention_analytics_event_days = 10
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add_all(
                [
                    EventLog(
                        event_id="event-old",
                        event_type="retention",
                        occurred_at=now - timedelta(days=12),
                    ),
                    EventLog(
                        event_id="event-new",
                        event_type="retention",
                        occurred_at=now - timedelta(days=2),
                    ),
                ]
            )
            await session.commit()

        async with async_session_maker() as session:
            result = await analytics_retention_service.purge_raw_events(session, now=now)
            assert result.deleted == 1

        async with async_session_maker() as session:
            remaining = await session.scalar(sa.select(sa.func.count(EventLog.event_id)))
            assert remaining == 1
    finally:
        settings.retention_analytics_event_days = original_days


@pytest.mark.anyio
async def test_analytics_retention_preserves_aggregates(async_session_maker):
    original_days = settings.retention_analytics_event_days
    settings.retention_analytics_event_days = 1
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            competitor = Competitor(name="Retention Competitor")
            session.add(competitor)
            await session.flush()
            session.add(
                CompetitorMetric(
                    competitor_id=competitor.competitor_id,
                    as_of_date=now.date(),
                    rating=4.8,
                    review_count=120,
                    avg_response_hours=2.5,
                )
            )
            session.add(
                EventLog(
                    event_id="event-old",
                    event_type="retention",
                    occurred_at=now - timedelta(days=5),
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            await analytics_retention_service.purge_raw_events(session, now=now)

        async with async_session_maker() as session:
            metrics_count = await session.scalar(
                sa.select(sa.func.count(CompetitorMetric.metric_id))
            )
            assert metrics_count == 1
    finally:
        settings.retention_analytics_event_days = original_days


@pytest.mark.anyio
async def test_analytics_retention_idempotent(async_session_maker):
    original_days = settings.retention_analytics_event_days
    settings.retention_analytics_event_days = 1
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add(
                EventLog(
                    event_id="event-old",
                    event_type="retention",
                    occurred_at=now - timedelta(days=5),
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            first = await analytics_retention_service.purge_raw_events(session, now=now)
            assert first.deleted == 1

        async with async_session_maker() as session:
            second = await analytics_retention_service.purge_raw_events(session, now=now)
            assert second.deleted == 0
    finally:
        settings.retention_analytics_event_days = original_days


@pytest.mark.anyio
async def test_analytics_retention_preserves_dashboard_queries(async_session_maker):
    original_days = settings.retention_analytics_event_days
    settings.retention_analytics_event_days = 7
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            lead = Lead(**_lead_payload(now))
            session.add(lead)
            await session.flush()
            session.add_all(
                [
                    EventLog(
                        event_id="event-old",
                        event_type=EventType.lead_created.value,
                        lead_id=lead.lead_id,
                        occurred_at=now - timedelta(days=10),
                    ),
                    EventLog(
                        event_id="event-new",
                        event_type=EventType.lead_created.value,
                        lead_id=lead.lead_id,
                        occurred_at=now - timedelta(days=1),
                    ),
                ]
            )
            await session.commit()

        async with async_session_maker() as session:
            await analytics_retention_service.purge_raw_events(session, now=now)

        async with async_session_maker() as session:
            counts = await conversion_counts(
                session,
                start=now - timedelta(days=5),
                end=now,
                org_id=settings.default_org_id,
            )
            assert counts[EventType.lead_created] == 1
    finally:
        settings.retention_analytics_event_days = original_days
