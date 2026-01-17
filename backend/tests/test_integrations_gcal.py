import datetime as dt
import httpx
import pytest
from sqlalchemy import select

from app.domain.feature_modules import service as feature_service
from app.domain.integrations import gcal_service
from app.domain.integrations.db_models import (
    GcalSyncMode,
    IntegrationsGcalCalendar,
    IntegrationsGoogleAccount,
    ScheduleExternalBlock,
)
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


async def _enable_gcal(session, org_id):
    await feature_service.upsert_org_feature_overrides(
        session,
        org_id,
        {"module.integrations": True, "integrations.google_calendar": True},
    )


def _transport_for_events(events: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        if request.url.host == "www.googleapis.com" and "calendar/v3/calendars" in str(request.url):
            return httpx.Response(200, json={"items": events})
        return httpx.Response(404, json={"error": "unknown"})

    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_gcal_status_reflects_db(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Status Org")
        owner = await saas_service.create_user(session, "owner@gcal.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        session.add(
            IntegrationsGoogleAccount(
                org_id=org.org_id,
                encrypted_refresh_token="refresh-token",
                token_scopes=["scope1"],
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/integrations/google/status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True


@pytest.mark.anyio
async def test_owner_can_connect_and_disconnect_google_calendar(
    async_session_maker, client, monkeypatch
):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Connect Org")
        owner = await saas_service.create_user(session, "owner@gcal-connect.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"refresh_token": "refresh-123", "scope": "scope1 scope2"})

    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", httpx.MockTransport(handler))

    owner_token = saas_service.build_access_token(owner, membership)
    callback = client.post(
        "/v1/admin/integrations/google/connect/callback",
        json={"code": "auth-code", "state": str(org.org_id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert callback.status_code == 200
    assert callback.json()["connected"] is True

    status_resp = client.get(
        "/v1/admin/integrations/google/status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["connected"] is True

    disconnect = client.post(
        "/v1/admin/integrations/google/disconnect",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert disconnect.status_code == 200
    assert disconnect.json()["connected"] is False


@pytest.mark.anyio
async def test_viewer_cannot_connect_or_disconnect_google_calendar(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Viewer Org")
        owner = await saas_service.create_user(session, "owner@gcal-viewer.com", "secret")
        await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@gcal-viewer.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await _enable_gcal(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    start_resp = client.post(
        "/v1/admin/integrations/google/connect/start",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert start_resp.status_code == 403

    disconnect_resp = client.post(
        "/v1/admin/integrations/google/disconnect",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert disconnect_resp.status_code == 403


@pytest.mark.anyio
async def test_viewer_can_read_google_calendar_status(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Viewer Status Org")
        owner = await saas_service.create_user(session, "owner@gcal-viewer-status.com", "secret")
        await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@gcal-viewer-status.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await _enable_gcal(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    response = client.get(
        "/v1/admin/integrations/google/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    assert response.json()["connected"] is False


@pytest.mark.anyio
async def test_google_calendar_oauth_tokens_not_logged(async_session_maker, client, monkeypatch, caplog):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Log Org")
        owner = await saas_service.create_user(session, "owner@gcal-log.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_gcal(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"refresh_token": "refresh-logged", "scope": "scope1"})

    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", httpx.MockTransport(handler))

    owner_token = saas_service.build_access_token(owner, membership)
    with caplog.at_level("INFO"):
        response = client.post(
            "/v1/admin/integrations/google/connect/callback",
            json={"code": "auth-code", "state": str(org.org_id)},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    assert response.status_code == 200
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "refresh-logged" not in combined


@pytest.mark.anyio
async def test_import_sync_creates_external_blocks(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Import Org")
        owner = await saas_service.create_user(session, "owner@gcal-import.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
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
                mode=GcalSyncMode.IMPORT,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    events = [
        {
            "id": "evt-1",
            "summary": "Blocked",
            "start": {"dateTime": "2025-02-01T10:00:00Z"},
            "end": {"dateTime": "2025-02-01T11:00:00Z"},
        },
        {
            "id": "evt-2",
            "summary": "Out of office",
            "start": {"dateTime": "2025-02-02T09:00:00Z"},
            "end": {"dateTime": "2025-02-02T10:30:00Z"},
        },
    ]
    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", _transport_for_events(events))

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.post(
        "/v1/admin/integrations/google/gcal/import_sync",
        params={"from": "2025-02-01T00:00:00Z", "to": "2025-02-03T00:00:00Z"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    assert response.json()["imported"] == 2

    async with async_session_maker() as session:
        blocks = (
            await session.execute(
                select(ScheduleExternalBlock).where(ScheduleExternalBlock.org_id == org.org_id)
            )
        ).scalars().all()
        assert {block.external_event_id for block in blocks} == {"evt-1", "evt-2"}


@pytest.mark.anyio
async def test_import_sync_updates_existing_blocks(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Gcal Import Update Org")
        owner = await saas_service.create_user(session, "owner@gcal-import-update.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
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
                mode=GcalSyncMode.IMPORT,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://example.com/callback")

    original_events = [
        {
            "id": "evt-1",
            "summary": "Blocked",
            "start": {"dateTime": "2025-03-01T10:00:00Z"},
            "end": {"dateTime": "2025-03-01T11:00:00Z"},
        }
    ]
    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", _transport_for_events(original_events))
    owner_token = saas_service.build_access_token(owner, membership)
    response = client.post(
        "/v1/admin/integrations/google/gcal/import_sync",
        params={"from": "2025-03-01T00:00:00Z", "to": "2025-03-02T00:00:00Z"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200

    updated_events = [
        {
            "id": "evt-1",
            "summary": "Blocked Updated",
            "start": {"dateTime": "2025-03-01T12:00:00Z"},
            "end": {"dateTime": "2025-03-01T13:30:00Z"},
        }
    ]
    monkeypatch.setattr(gcal_service, "TOKEN_EXCHANGE_TRANSPORT", _transport_for_events(updated_events))
    response = client.post(
        "/v1/admin/integrations/google/gcal/import_sync",
        params={"from": "2025-03-01T00:00:00Z", "to": "2025-03-02T00:00:00Z"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        block = await session.scalar(
            select(ScheduleExternalBlock).where(
                ScheduleExternalBlock.org_id == org.org_id,
                ScheduleExternalBlock.external_event_id == "evt-1",
            )
        )
        assert block is not None
        assert block.summary == "Blocked Updated"
        starts_at = block.starts_at
        ends_at = block.ends_at
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=dt.timezone.utc)
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=dt.timezone.utc)
        assert starts_at == dt.datetime(2025, 3, 1, 12, 0, tzinfo=dt.timezone.utc)
        assert ends_at == dt.datetime(2025, 3, 1, 13, 30, tzinfo=dt.timezone.utc)
