import httpx
import pytest

from app.domain.feature_modules import service as feature_service
from app.domain.integrations import gcal_service
from app.domain.integrations.db_models import IntegrationsGoogleAccount
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


async def _enable_gcal(session, org_id):
    await feature_service.upsert_org_feature_overrides(
        session,
        org_id,
        {"module.integrations": True, "integrations.google_calendar": True},
    )


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
