from datetime import datetime, timedelta, timezone

import pytest

from app.domain.feature_modules import service as feature_service
from app.domain.integrations import gcal_service
from app.domain.integrations.db_models import (
    GcalSyncMode,
    IntegrationsGcalCalendar,
    IntegrationsGcalSyncState,
    IntegrationsGoogleAccount,
)
from app.domain.saas import service as saas_service
from app.jobs import gcal_sync
from app.settings import settings


async def _enable_gcal(session, org_id):
    await feature_service.upsert_org_feature_overrides(
        session,
        org_id,
        {"module.integrations": True, "integrations.google_calendar": True},
    )


@pytest.mark.anyio
async def test_gcal_sync_job_gates_back_to_back(async_session_maker, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Job Org")
        await _enable_gcal(session, org.org_id)
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-token",
                token_scopes=["scope1"],
            )
        )
        session.add(
            IntegrationsGcalCalendar(
                org_id=org.org_id,
                calendar_id="primary",
                mode=GcalSyncMode.EXPORT,
            )
        )
        await session.commit()

    calls: list[tuple[datetime, datetime]] = []

    async def _export(session, org_id, *, from_date, to_date):
        calls.append((from_date, to_date))
        return None

    monkeypatch.setattr(gcal_service, "export_bookings_to_gcal", _export)
    monkeypatch.setattr(settings, "gcal_sync_interval_seconds", 3600)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        first = await gcal_sync.run_gcal_sync(session, now=now)
        second = await gcal_sync.run_gcal_sync(session, now=now + timedelta(seconds=30))
        state = await session.get(
            IntegrationsGcalSyncState,
            {"org_id": org.org_id, "calendar_id": "primary"},
        )

    assert first["processed"] == 1
    assert second["skipped"] >= 1
    assert len(calls) == 1
    assert state is not None
    assert state.last_sync_at.replace(tzinfo=timezone.utc) == now


@pytest.mark.anyio
async def test_gcal_sync_job_records_error(async_session_maker, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Job Error Org")
        await _enable_gcal(session, org.org_id)
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-token",
                token_scopes=["scope1"],
            )
        )
        session.add(
            IntegrationsGcalCalendar(
                org_id=org.org_id,
                calendar_id="primary",
                mode=GcalSyncMode.EXPORT,
            )
        )
        await session.commit()

    async def _export(session, org_id, *, from_date, to_date):
        raise ValueError("boom")

    monkeypatch.setattr(gcal_service, "export_bookings_to_gcal", _export)
    monkeypatch.setattr(settings, "gcal_sync_interval_seconds", 1)

    now = datetime(2024, 2, 1, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        result = await gcal_sync.run_gcal_sync(session, now=now)
        state = await session.get(
            IntegrationsGcalSyncState,
            {"org_id": org.org_id, "calendar_id": "primary"},
        )

    assert result["errors"] == 1
    assert state is not None
    assert state.last_error == "boom"
    assert state.last_sync_at.replace(tzinfo=timezone.utc) == now
