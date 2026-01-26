from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.analytics import retention as analytics_retention_service
from app.domain.analytics.db_models import Competitor, CompetitorMetric, EventLog
from app.domain.leads.db_models import (
    Lead,
    LeadQuote,
    LeadQuoteFollowUp,
    LeadTouchpoint,
    ReferralCredit,
)
from app.domain.logs import service as log_retention_service
from app.domain.reason_logs.db_models import ReasonLog
from app.domain.soft_delete_purge import service as soft_delete_purge_service
from app.settings import settings

FIXED_NOW = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _lead_payload(**overrides: object) -> dict[str, object]:
    payload = {
        "name": "Retention Lead",
        "phone": "+15555550100",
        "email": "lead@example.com",
        "structured_inputs": {"bedrooms": 2},
        "estimate_snapshot": {"total": 120},
        "pricing_config_version": "v1",
        "config_hash": "hash",
        "status": "NEW",
    }
    payload.update(overrides)
    return payload


async def _audit_entries(session, action: str) -> list[AdminAuditLog]:
    result = await session.execute(
        sa.select(AdminAuditLog).where(AdminAuditLog.action == action)
    )
    return list(result.scalars().all())


@pytest.mark.anyio
async def test_application_log_retention_compliance(async_session_maker):
    original_days = settings.retention_application_log_days
    settings.retention_application_log_days = 10
    try:
        cutoff = FIXED_NOW - timedelta(days=10)
        async with async_session_maker() as session:
            session.add_all(
                [
                    ReasonLog(
                        reason_id="log-old",
                        order_id="booking-old",
                        kind="system",
                        code="retention",
                        created_at=FIXED_NOW - timedelta(days=12),
                    ),
                    ReasonLog(
                        reason_id="log-new",
                        order_id="booking-new",
                        kind="system",
                        code="retention",
                        created_at=FIXED_NOW - timedelta(days=2),
                    ),
                    AdminAuditLog(
                        audit_id="audit-sentinel",
                        org_id=settings.default_org_id,
                        admin_id="admin-1",
                        action="audit-sentinel",
                        action_type="WRITE",
                        sensitivity_level="normal",
                        actor="tester",
                        role="system",
                        auth_method="system",
                        resource_type="test",
                        resource_id="test",
                        context={"note": "do not delete"},
                        before=None,
                        after=None,
                        created_at=FIXED_NOW - timedelta(days=365),
                    ),
                ]
            )
            await session.commit()

        async with async_session_maker() as session:
            result = await log_retention_service.purge_application_logs(
                session,
                now=FIXED_NOW,
                batch_size=50,
            )
            assert result.deleted == 1

        async with async_session_maker() as session:
            result = await log_retention_service.purge_application_logs(
                session,
                now=FIXED_NOW,
                batch_size=50,
            )
            assert result.deleted == 0

        async with async_session_maker() as session:
            remaining_logs = await session.scalar(sa.select(sa.func.count(ReasonLog.reason_id)))
            assert remaining_logs == 1
            remaining_audit = await session.scalar(
                sa.select(sa.func.count(AdminAuditLog.audit_id)).where(
                    AdminAuditLog.action == "audit-sentinel"
                )
            )
            assert remaining_audit == 1

            audit_entries = await _audit_entries(session, "log_retention_purge")
            contexts = [entry.context or {} for entry in audit_entries]
            relevant = [
                context
                for context in contexts
                if context.get("retention_days") == 10
                and context.get("cutoff") == cutoff.isoformat()
            ]
            assert len(relevant) == 2
            assert any(context.get("deleted") == 1 for context in relevant)
            assert any(context.get("deleted") == 0 for context in relevant)
            assert any(context.get("category") == "logs" for context in relevant)
    finally:
        settings.retention_application_log_days = original_days


@pytest.mark.anyio
async def test_analytics_retention_purges_raw_events_only(async_session_maker):
    original_days = settings.retention_analytics_event_days
    settings.retention_analytics_event_days = 30
    try:
        cutoff = FIXED_NOW - timedelta(days=30)
        async with async_session_maker() as session:
            competitor = Competitor(name="Bench Cleaners")
            session.add(competitor)
            await session.flush()
            session.add_all(
                [
                    CompetitorMetric(
                        competitor_id=competitor.competitor_id,
                        as_of_date=date(2023, 12, 1),
                        rating=4.8,
                        review_count=120,
                        avg_response_hours=1.5,
                    ),
                    EventLog(
                        event_id="event-old",
                        event_type="retention",
                        occurred_at=FIXED_NOW - timedelta(days=45),
                    ),
                    EventLog(
                        event_id="event-new",
                        event_type="retention",
                        occurred_at=FIXED_NOW - timedelta(days=5),
                    ),
                ]
            )
            await session.commit()

        async with async_session_maker() as session:
            result = await analytics_retention_service.purge_raw_events(
                session,
                now=FIXED_NOW,
                batch_size=50,
            )
            assert result.deleted == 1

        async with async_session_maker() as session:
            result = await analytics_retention_service.purge_raw_events(
                session,
                now=FIXED_NOW,
                batch_size=50,
            )
            assert result.deleted == 0

        async with async_session_maker() as session:
            remaining_events = await session.scalar(sa.select(sa.func.count(EventLog.event_id)))
            assert remaining_events == 1
            remaining_metrics = await session.scalar(
                sa.select(sa.func.count(CompetitorMetric.metric_id))
            )
            remaining_competitors = await session.scalar(
                sa.select(sa.func.count(Competitor.competitor_id))
            )
            assert remaining_metrics == 1
            assert remaining_competitors == 1

            audit_entries = await _audit_entries(session, "analytics_retention_enforced")
            contexts = [entry.context or {} for entry in audit_entries]
            relevant = [
                context
                for context in contexts
                if context.get("cutoff") == cutoff.isoformat()
                and context.get("retention_days") == 30
            ]
            assert len(relevant) == 2
            assert any(context.get("deleted") == 1 for context in relevant)
            assert any(context.get("deleted") == 0 for context in relevant)
            assert any(
                context.get("category") == "analytics"
                and context.get("classification") is not None
                for context in relevant
            )
    finally:
        settings.retention_analytics_event_days = original_days


@pytest.mark.anyio
async def test_soft_delete_purge_grace_period_and_legal_hold(async_session_maker):
    original_days = settings.retention_soft_deleted_days
    settings.retention_soft_deleted_days = 30
    try:
        cutoff = FIXED_NOW - timedelta(days=30)
        async with async_session_maker() as session:
            lead_old = Lead(
                **_lead_payload(
                    lead_id="lead-old",
                    deleted_at=FIXED_NOW - timedelta(days=40),
                    legal_hold=False,
                )
            )
            lead_new = Lead(
                **_lead_payload(
                    lead_id="lead-new",
                    deleted_at=FIXED_NOW - timedelta(days=10),
                    legal_hold=False,
                )
            )
            lead_held = Lead(
                **_lead_payload(
                    lead_id="lead-held",
                    deleted_at=FIXED_NOW - timedelta(days=40),
                    legal_hold=True,
                )
            )
            session.add_all([lead_old, lead_new, lead_held])
            session.add_all(
                [
                    LeadQuote(
                        quote_id="quote-old",
                        lead_id=lead_old.lead_id,
                        org_id=settings.default_org_id,
                        amount=15000,
                        currency="CAD",
                        service_type="deep",
                        status="sent",
                        created_at=FIXED_NOW - timedelta(days=45),
                    ),
                    LeadQuoteFollowUp(
                        followup_id="followup-old",
                        quote_id="quote-old",
                        org_id=settings.default_org_id,
                        note="follow up",
                        created_by="tester",
                        created_at=FIXED_NOW - timedelta(days=43),
                    ),
                    LeadTouchpoint(
                        touchpoint_id="00000000-0000-0000-0000-000000000030",
                        org_id=settings.default_org_id,
                        lead_id=lead_old.lead_id,
                        occurred_at=FIXED_NOW - timedelta(days=42),
                        channel="email",
                        source="retention",
                        campaign="cleanup",
                        medium="newsletter",
                        keyword="retention",
                        landing_page="/",
                        metadata_json={"note": "touch"},
                    ),
                    ReferralCredit(
                        credit_id="credit-old",
                        referrer_lead_id=lead_old.lead_id,
                        referred_lead_id=lead_new.lead_id,
                        applied_code="REF123",
                        created_at=FIXED_NOW - timedelta(days=44),
                    ),
                ]
            )
            await session.commit()

        async with async_session_maker() as session:
            results = await soft_delete_purge_service.run_soft_delete_purge(
                session,
                now=FIXED_NOW,
            )
            lead_result = next(result for result in results if result.entity_type == "lead")
            assert lead_result.deleted == 1
            assert lead_result.held == 1

        async with async_session_maker() as session:
            results = await soft_delete_purge_service.run_soft_delete_purge(
                session,
                now=FIXED_NOW,
            )
            lead_result = next(result for result in results if result.entity_type == "lead")
            assert lead_result.deleted == 0
            assert lead_result.held == 1

        async with async_session_maker() as session:
            remaining_leads = await session.scalar(sa.select(sa.func.count(Lead.lead_id)))
            assert remaining_leads == 2
            remaining_quotes = await session.scalar(
                sa.select(sa.func.count(LeadQuote.quote_id))
            )
            remaining_followups = await session.scalar(
                sa.select(sa.func.count(LeadQuoteFollowUp.followup_id))
            )
            remaining_touchpoints = await session.scalar(
                sa.select(sa.func.count(LeadTouchpoint.touchpoint_id))
            )
            remaining_credits = await session.scalar(
                sa.select(sa.func.count(ReferralCredit.credit_id))
            )
            assert remaining_quotes == 0
            assert remaining_followups == 0
            assert remaining_touchpoints == 0
            assert remaining_credits == 0

            audit_entries = await _audit_entries(session, "soft_delete_purge")
            contexts = [entry.context or {} for entry in audit_entries]
            relevant = [
                context
                for context in contexts
                if context.get("grace_period_days") == 30
                and context.get("cutoff") == cutoff.isoformat()
                and context.get("entity_type") == "lead"
            ]
            assert len(relevant) == 2
            assert any(context.get("deleted") == 1 for context in relevant)
            assert any(context.get("deleted") == 0 for context in relevant)
            assert any(context.get("category") == "soft_delete_purge" for context in relevant)
    finally:
        settings.retention_soft_deleted_days = original_days
