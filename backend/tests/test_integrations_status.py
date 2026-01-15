import pytest

from app.domain.feature_modules import service as feature_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


@pytest.mark.anyio
async def test_owner_can_read_integrations_status_masked(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Integrations Org")
        owner = await saas_service.create_user(session, "owner@integrations.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await session.commit()

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_live_1234567890")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_123456")
    monkeypatch.setattr(settings, "sms_mode", "twilio")
    monkeypatch.setattr(settings, "call_mode", "off")
    monkeypatch.setattr(settings, "twilio_account_sid", "AC1234567890")
    monkeypatch.setattr(settings, "twilio_auth_token", "secret-token")
    monkeypatch.setattr(settings, "twilio_sms_from", "+15551234567")
    monkeypatch.setattr(settings, "email_mode", "sendgrid")
    monkeypatch.setattr(settings, "sendgrid_api_key", "SG.secret")
    monkeypatch.setattr(settings, "email_from", "billing@example.com")

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/settings/integrations",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["stripe"]["connected"] is True
    assert payload["stripe"]["account"] != "sk_live_1234567890"
    assert "***" in payload["stripe"]["account"]
    assert payload["twilio"]["connected"] is True
    assert payload["twilio"]["account"] != "AC1234567890"
    assert "***" in payload["twilio"]["account"]
    assert payload["twilio"]["sms_from"] != "+15551234567"
    assert "***" in payload["twilio"]["sms_from"]
    assert payload["email"]["connected"] is True
    assert payload["email"]["sender"] != "billing@example.com"
    assert "***" in payload["email"]["sender"]


@pytest.mark.anyio
async def test_integrations_status_requires_owner(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Integrations Guard Org")
        owner = await saas_service.create_user(session, "owner@guard.com", "secret")
        owner_membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        dispatcher = await saas_service.create_user(session, "dispatcher@guard.com", "secret")
        dispatcher_membership = await saas_service.create_membership(
            session, org, dispatcher, MembershipRole.DISPATCHER
        )
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)
    dispatcher_token = saas_service.build_access_token(dispatcher, dispatcher_membership)

    allowed = client.get(
        "/v1/admin/settings/integrations",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert allowed.status_code == 200

    blocked = client.get(
        "/v1/admin/settings/integrations",
        headers={"Authorization": f"Bearer {dispatcher_token}"},
    )
    assert blocked.status_code == 403


@pytest.mark.anyio
async def test_integrations_status_respects_feature_flag(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Integrations Flag Org")
        owner = await saas_service.create_user(session, "owner@flag.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"module.integrations": False},
        )
        await session.commit()

    owner_token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/settings/integrations",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 403
