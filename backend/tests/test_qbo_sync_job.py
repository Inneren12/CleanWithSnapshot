from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.domain.feature_modules import service as feature_service
from app.domain.integrations import qbo_service
from app.domain.integrations.db_models import AccountingSyncState, IntegrationsAccountingAccount
from app.domain.saas import service as saas_service
from app.jobs import qbo_sync
from app.settings import settings


async def _enable_qbo(session, org_id):
    await feature_service.upsert_org_feature_overrides(
        session,
        org_id,
        {"module.integrations": True, "integrations.accounting.quickbooks": True},
    )


@pytest.mark.anyio
async def test_qbo_sync_job_gates_back_to_back(async_session_maker, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Job Org")
        await _enable_qbo(session, org.org_id)
        session.add(
            IntegrationsAccountingAccount(
                org_id=org.org_id,
                provider=qbo_service.QBO_PROVIDER,
                encrypted_refresh_token="refresh-token",
                realm_id="realm-1",
            )
        )
        await session.commit()

    calls: list[tuple[str, datetime]] = []

    async def _push(session, org_id, *, from_date, to_date):
        calls.append(("push", datetime.combine(from_date, datetime.min.time(), tzinfo=timezone.utc)))
        return SimpleNamespace(created=0, updated=0, skipped=0)

    async def _pull(session, org_id, *, from_date, to_date):
        calls.append(("pull", datetime.combine(from_date, datetime.min.time(), tzinfo=timezone.utc)))
        return SimpleNamespace(payments_recorded=0, payments_skipped=0)

    monkeypatch.setattr(qbo_service, "push_invoices_to_qbo", _push)
    monkeypatch.setattr(qbo_service, "pull_invoice_status_from_qbo", _pull)
    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")
    monkeypatch.setattr(settings, "qbo_sync_interval_seconds", 3600)

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        first = await qbo_sync.run_qbo_sync(session, now=now)
        second = await qbo_sync.run_qbo_sync(session, now=now + timedelta(seconds=30))
        state = await session.get(
            AccountingSyncState,
            {"org_id": org.org_id, "provider": qbo_service.QBO_PROVIDER},
        )

    assert first["processed"] == 1
    assert second["skipped"] >= 1
    assert len(calls) == 2
    assert state is not None
    assert state.last_sync_at.replace(tzinfo=timezone.utc) == now
    assert state.cursor == now.date().isoformat()


@pytest.mark.anyio
async def test_qbo_sync_job_records_error(async_session_maker, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Job Error Org")
        await _enable_qbo(session, org.org_id)
        session.add(
            IntegrationsAccountingAccount(
                org_id=org.org_id,
                provider=qbo_service.QBO_PROVIDER,
                encrypted_refresh_token="refresh-token",
                realm_id="realm-2",
            )
        )
        await session.commit()

    async def _push(session, org_id, *, from_date, to_date):
        raise ValueError("boom")

    monkeypatch.setattr(qbo_service, "push_invoices_to_qbo", _push)
    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")
    monkeypatch.setattr(settings, "qbo_sync_interval_seconds", 1)

    now = datetime(2024, 2, 1, tzinfo=timezone.utc)
    async with async_session_maker() as session:
        result = await qbo_sync.run_qbo_sync(session, now=now)
        state = await session.get(
            AccountingSyncState,
            {"org_id": org.org_id, "provider": qbo_service.QBO_PROVIDER},
        )

    assert result["errors"] == 1
    assert state is not None
    assert state.last_error == "boom"
    assert state.last_sync_at.replace(tzinfo=timezone.utc) == now


@pytest.mark.anyio
async def test_qbo_sync_job_skips_when_disabled(async_session_maker, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Job Disabled Org")
        session.add(
            IntegrationsAccountingAccount(
                org_id=org.org_id,
                provider=qbo_service.QBO_PROVIDER,
                encrypted_refresh_token="refresh-token",
                realm_id="realm-3",
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    async with async_session_maker() as session:
        result = await qbo_sync.run_qbo_sync(session)
        state = await session.get(
            AccountingSyncState,
            {"org_id": org.org_id, "provider": qbo_service.QBO_PROVIDER},
        )

    assert result["processed"] == 0
    assert result["errors"] == 0
    assert result["skipped"] >= 1
    assert state is None
