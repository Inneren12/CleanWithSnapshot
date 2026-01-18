import uuid
from datetime import datetime, timezone

import pytest

from app.domain.feature_modules import service as feature_service
from app.domain.leads import statuses as lead_statuses
from app.domain.leads.db_models import Lead
from app.domain.leads_nurture import service as nurture_service
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
from app.domain.notifications import email_service
from app.domain.org_settings import service as org_settings_service
from app.domain.org_settings.db_models import OrganizationSettings
from app.domain.saas import service as saas_service
from app.infra.communication import NoopCommunicationAdapter
from app.infra.email import NoopEmailAdapter
from app.jobs import leads_nurture_runner
from app.settings import settings


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _enable_nurture(session, org_id: uuid.UUID) -> None:
    await feature_service.upsert_org_feature_overrides(
        session,
        org_id,
        {"module.leads": True, "leads.nurture": True},
    )


async def _create_lead(session, *, org_id: uuid.UUID, email: str | None) -> Lead:
    lead = Lead(
        lead_id=str(uuid.uuid4()),
        org_id=org_id,
        name="Nurture Lead",
        phone="780-555-0101",
        email=email,
        postal_code=None,
        address="123 Org Street",
        preferred_dates=["Mon morning"],
        access_notes=None,
        parking=None,
        pets=None,
        allergies=None,
        notes=None,
        structured_inputs={"beds": 1, "baths": 1, "cleaning_type": "standard"},
        estimate_snapshot={"total": 0},
        pricing_config_version="test",
        config_hash="test",
        status=lead_statuses.LEAD_STATUS_NEW,
    )
    session.add(lead)
    await session.flush()
    return lead


async def _seed_nurture(
    session,
    *,
    org_id: uuid.UUID,
    lead: Lead,
    channel: NurtureChannel,
    now: datetime,
    payload: dict | None = None,
) -> NurtureStepLog:
    campaign = NurtureCampaign(
        org_id=org_id,
        key="welcome",
        name="Welcome",
        enabled=True,
    )
    session.add(campaign)
    await session.flush()

    step = NurtureStep(
        org_id=org_id,
        campaign_id=campaign.campaign_id,
        step_index=0,
        delay_hours=0,
        channel=channel,
        template_key=None,
        payload_json=payload or {},
        active=True,
    )
    session.add(step)
    await session.flush()

    enrollment = NurtureEnrollment(
        org_id=org_id,
        lead_id=lead.lead_id,
        campaign_id=campaign.campaign_id,
        enrolled_at=now,
        status=NurtureEnrollmentStatus.active,
    )
    session.add(enrollment)
    await session.flush()

    log = NurtureStepLog(
        org_id=org_id,
        enrollment_id=enrollment.enrollment_id,
        step_index=0,
        planned_at=now,
        status=NurtureStepLogStatus.planned,
        idempotency_key=nurture_service.build_idempotency_key(enrollment.enrollment_id, 0),
    )
    session.add(log)
    await session.flush()
    return log


@pytest.mark.anyio
async def test_nurture_runner_idempotent(async_session_maker):
    now = datetime(2024, 1, 2, 18, 0, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Runner Org")
        await _enable_nurture(session, org.org_id)
        lead = await _create_lead(session, org_id=org.org_id, email=None)
        log = await _seed_nurture(
            session,
            org_id=org.org_id,
            lead=lead,
            channel=NurtureChannel.log_only,
            now=now,
        )
        await session.commit()

    async with async_session_maker() as session:
        result = await leads_nurture_runner.run_leads_nurture_runner(
            session,
            NoopEmailAdapter(),
            NoopCommunicationAdapter(),
            now=now,
        )
        refreshed = await session.get(NurtureStepLog, log.log_id)

    assert result["sent"] == 1
    assert refreshed.status == NurtureStepLogStatus.sent
    assert _as_utc(refreshed.sent_at) == now

    async with async_session_maker() as session:
        result = await leads_nurture_runner.run_leads_nurture_runner(
            session,
            NoopEmailAdapter(),
            NoopCommunicationAdapter(),
            now=now,
        )
        refreshed = await session.get(NurtureStepLog, log.log_id)

    assert result["sent"] == 0
    assert refreshed.status == NurtureStepLogStatus.sent
    assert _as_utc(refreshed.sent_at) == now


@pytest.mark.anyio
async def test_nurture_runner_defers_quiet_hours(async_session_maker):
    now = datetime(2024, 1, 7, 9, 0, tzinfo=timezone.utc)
    expected = datetime(2024, 1, 8, 15, 0, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Quiet Org")
        await _enable_nurture(session, org.org_id)
        settings_record = OrganizationSettings(
            org_id=org.org_id,
            timezone="America/Edmonton",
            business_hours=org_settings_service.DEFAULT_BUSINESS_HOURS,
            holidays=[],
            branding={},
            referral_credit_trigger=org_settings_service.DEFAULT_REFERRAL_CREDIT_TRIGGER,
            finance_ready=False,
        )
        session.add(settings_record)
        lead = await _create_lead(session, org_id=org.org_id, email=None)
        log = await _seed_nurture(
            session,
            org_id=org.org_id,
            lead=lead,
            channel=NurtureChannel.log_only,
            now=now,
        )
        await session.commit()

    async with async_session_maker() as session:
        result = await leads_nurture_runner.run_leads_nurture_runner(
            session,
            NoopEmailAdapter(),
            NoopCommunicationAdapter(),
            now=now,
        )
        refreshed = await session.get(NurtureStepLog, log.log_id)

    assert result["deferred"] == 1
    assert refreshed.status == NurtureStepLogStatus.planned
    assert refreshed.sent_at is None
    assert _as_utc(refreshed.planned_at) == expected
    assert refreshed.error == "quiet_hours"


@pytest.mark.anyio
async def test_nurture_runner_respects_unsubscribe(async_session_maker):
    now = datetime(2024, 1, 3, 18, 0, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Opt Out Org")
        await _enable_nurture(session, org.org_id)
        lead = await _create_lead(session, org_id=org.org_id, email="lead@example.com")
        log = await _seed_nurture(
            session,
            org_id=org.org_id,
            lead=lead,
            channel=NurtureChannel.email,
            now=now,
            payload={"subject": "Hello", "body": "Welcome"},
        )
        await session.flush()
        await email_service.register_unsubscribe(
            session, recipient=lead.email, scope=email_service.SCOPE_MARKETING, org_id=org.org_id
        )
        await session.commit()

    async with async_session_maker() as session:
        result = await leads_nurture_runner.run_leads_nurture_runner(
            session,
            NoopEmailAdapter(),
            NoopCommunicationAdapter(),
            now=now,
        )
        refreshed = await session.get(NurtureStepLog, log.log_id)

    assert result["skipped"] == 1
    assert refreshed.status == NurtureStepLogStatus.skipped
    assert _as_utc(refreshed.sent_at) == now
    assert refreshed.error == "unsubscribed"


@pytest.mark.anyio
async def test_nurture_runner_skips_when_email_disabled(async_session_maker):
    now = datetime(2024, 1, 4, 18, 0, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Email Off Org")
        await _enable_nurture(session, org.org_id)
        lead = await _create_lead(session, org_id=org.org_id, email="lead@example.com")
        log = await _seed_nurture(
            session,
            org_id=org.org_id,
            lead=lead,
            channel=NurtureChannel.email,
            now=now,
            payload={"subject": "Hello", "body": "Welcome"},
        )
        await session.commit()

    settings.email_mode = "off"

    async with async_session_maker() as session:
        result = await leads_nurture_runner.run_leads_nurture_runner(
            session,
            NoopEmailAdapter(),
            NoopCommunicationAdapter(),
            now=now,
        )
        refreshed = await session.get(NurtureStepLog, log.log_id)

    assert result["skipped"] == 1
    assert refreshed.status == NurtureStepLogStatus.skipped
    assert _as_utc(refreshed.sent_at) == now
    assert refreshed.error == "email_disabled"
