from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.domain.leads.db_models import (
    Lead,
    LeadQuote,
    LeadQuoteFollowUp,
    LeadTouchpoint,
    ReferralCredit,
)
from app.domain.leads.statuses import default_lead_status
from app.domain.soft_delete_purge import run_soft_delete_purge
from app.settings import settings


def _lead_payload() -> dict:
    return {
        "org_id": settings.default_org_id,
        "name": "Soft Delete Lead",
        "phone": "555-222-0000",
        "structured_inputs": {"beds": 1, "baths": 1},
        "estimate_snapshot": {"quote": 100},
        "pricing_config_version": "v1",
        "config_hash": "hash",
        "status": default_lead_status(),
    }


@pytest.mark.anyio
async def test_soft_delete_purge_respects_grace_period(async_session_maker):
    original_grace = settings.retention_soft_deleted_days
    original_batch = settings.soft_delete_purge_batch_size
    settings.retention_soft_deleted_days = 10
    settings.soft_delete_purge_batch_size = 5
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            lead_old = Lead(**_lead_payload())
            lead_old.deleted_at = now - timedelta(days=12)
            lead_new = Lead(**_lead_payload())
            lead_new.deleted_at = now - timedelta(days=2)
            session.add_all([lead_old, lead_new])
            await session.commit()

        async with async_session_maker() as session:
            results = await run_soft_delete_purge(session, now=now)
            result = next(item for item in results if item.entity_type == "lead")
            assert result.deleted == 1

        async with async_session_maker() as session:
            remaining = await session.scalar(sa.select(sa.func.count(Lead.lead_id)))
            assert remaining == 1
    finally:
        settings.retention_soft_deleted_days = original_grace
        settings.soft_delete_purge_batch_size = original_batch


@pytest.mark.anyio
async def test_soft_delete_purge_skips_legal_hold(async_session_maker):
    original_grace = settings.retention_soft_deleted_days
    settings.retention_soft_deleted_days = 10
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            lead_hold = Lead(**_lead_payload())
            lead_hold.deleted_at = now - timedelta(days=12)
            lead_hold.legal_hold = True
            session.add(lead_hold)
            await session.commit()

        async with async_session_maker() as session:
            results = await run_soft_delete_purge(session, now=now)
            result = next(item for item in results if item.entity_type == "lead")
            assert result.deleted == 0
            assert result.held == 1

        async with async_session_maker() as session:
            remaining = await session.scalar(sa.select(sa.func.count(Lead.lead_id)))
            assert remaining == 1
    finally:
        settings.retention_soft_deleted_days = original_grace


@pytest.mark.anyio
async def test_soft_delete_purge_cascades_children(async_session_maker):
    original_grace = settings.retention_soft_deleted_days
    settings.retention_soft_deleted_days = 10
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            purge_lead = Lead(**_lead_payload())
            purge_lead.deleted_at = now - timedelta(days=20)
            keep_lead = Lead(**_lead_payload())
            session.add_all([purge_lead, keep_lead])
            await session.flush()

            quote = LeadQuote(
                lead_id=purge_lead.lead_id,
                org_id=purge_lead.org_id,
                amount=150,
                currency="CAD",
                service_type="standard",
                status="sent",
            )
            session.add(quote)
            await session.flush()
            session.add(
                LeadQuoteFollowUp(
                    quote_id=quote.quote_id,
                    org_id=purge_lead.org_id,
                    note="Follow up",
                )
            )
            session.add(
                LeadTouchpoint(
                    org_id=purge_lead.org_id,
                    lead_id=purge_lead.lead_id,
                    channel="web",
                )
            )
            session.add(
                ReferralCredit(
                    referrer_lead_id=purge_lead.lead_id,
                    referred_lead_id=keep_lead.lead_id,
                    applied_code="CODE123",
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            results = await run_soft_delete_purge(session, now=now)
            result = next(item for item in results if item.entity_type == "lead")
            assert result.deleted == 1

        async with async_session_maker() as session:
            lead_count = await session.scalar(sa.select(sa.func.count(Lead.lead_id)))
            quote_count = await session.scalar(sa.select(sa.func.count(LeadQuote.quote_id)))
            followup_count = await session.scalar(
                sa.select(sa.func.count(LeadQuoteFollowUp.followup_id))
            )
            touchpoint_count = await session.scalar(
                sa.select(sa.func.count(LeadTouchpoint.touchpoint_id))
            )
            referral_count = await session.scalar(sa.select(sa.func.count(ReferralCredit.credit_id)))
            assert lead_count == 1
            assert quote_count == 0
            assert followup_count == 0
            assert touchpoint_count == 0
            assert referral_count == 0
    finally:
        settings.retention_soft_deleted_days = original_grace


@pytest.mark.anyio
async def test_soft_delete_purge_is_idempotent(async_session_maker):
    original_grace = settings.retention_soft_deleted_days
    settings.retention_soft_deleted_days = 1
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            lead_old = Lead(**_lead_payload())
            lead_old.deleted_at = now - timedelta(days=5)
            session.add(lead_old)
            await session.commit()

        async with async_session_maker() as session:
            first = await run_soft_delete_purge(session, now=now)
            result = next(item for item in first if item.entity_type == "lead")
            assert result.deleted == 1

        async with async_session_maker() as session:
            second = await run_soft_delete_purge(session, now=now)
            result = next(item for item in second if item.entity_type == "lead")
            assert result.deleted == 0
    finally:
        settings.retention_soft_deleted_days = original_grace
