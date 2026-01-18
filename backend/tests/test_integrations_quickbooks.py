import httpx
import pytest

from app.domain.feature_modules import service as feature_service
from app.domain.integrations import qbo_service
from app.domain.integrations.db_models import IntegrationsAccountingAccount
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


async def _enable_quickbooks(session, org_id):
    await feature_service.upsert_org_feature_overrides(
        session,
        org_id,
        {"module.integrations": True, "integrations.accounting.quickbooks": True},
    )


@pytest.mark.anyio
async def test_qbo_status_reflects_db(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Status Org")
        owner = await saas_service.create_user(session, "owner@qbo.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_quickbooks(session, org.org_id)
        session.add(
            IntegrationsAccountingAccount(
                org_id=org.org_id,
                provider=qbo_service.QBO_PROVIDER,
                encrypted_refresh_token="refresh-token",
                realm_id="realm-1",
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/integrations/accounting/quickbooks/status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True
    assert payload["realm_id"] == "realm-1"


@pytest.mark.anyio
async def test_owner_can_connect_and_disconnect_quickbooks(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Connect Org")
        owner = await saas_service.create_user(session, "owner@qbo-connect.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await _enable_quickbooks(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"refresh_token": "refresh-123"})

    monkeypatch.setattr(qbo_service, "TOKEN_EXCHANGE_TRANSPORT", httpx.MockTransport(handler))

    owner_token = saas_service.build_access_token(owner, membership)
    callback = client.post(
        "/v1/admin/integrations/accounting/quickbooks/connect/callback",
        json={"code": "auth-code", "realm_id": "realm-123", "state": str(org.org_id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert callback.status_code == 200
    assert callback.json()["connected"] is True

    status_resp = client.get(
        "/v1/admin/integrations/accounting/quickbooks/status",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["connected"] is True

    disconnect = client.post(
        "/v1/admin/integrations/accounting/quickbooks/disconnect",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert disconnect.status_code == 200
    assert disconnect.json()["connected"] is False


@pytest.mark.anyio
async def test_viewer_cannot_connect_or_disconnect_quickbooks(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Viewer Org")
        owner = await saas_service.create_user(session, "owner@qbo-viewer.com", "secret")
        await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@qbo-viewer.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await _enable_quickbooks(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    start_resp = client.post(
        "/v1/admin/integrations/accounting/quickbooks/connect/start",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert start_resp.status_code == 403

    disconnect_resp = client.post(
        "/v1/admin/integrations/accounting/quickbooks/disconnect",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert disconnect_resp.status_code == 403


@pytest.mark.anyio
async def test_viewer_can_read_quickbooks_status(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "QBO Viewer Status Org")
        owner = await saas_service.create_user(session, "owner@qbo-viewer-status.com", "secret")
        await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@qbo-viewer-status.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await _enable_quickbooks(session, org.org_id)
        await session.commit()

    monkeypatch.setattr(settings, "quickbooks_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "quickbooks_oauth_client_secret", "client-secret")
    monkeypatch.setattr(settings, "quickbooks_oauth_redirect_uri", "https://example.com/callback")

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    response = client.get(
        "/v1/admin/integrations/accounting/quickbooks/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    assert response.json()["connected"] is False
