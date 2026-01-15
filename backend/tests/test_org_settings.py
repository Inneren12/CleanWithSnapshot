import pytest

from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole


@pytest.mark.anyio
async def test_owner_can_update_org_settings(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Settings Org")
        owner = await saas_service.create_user(session, "owner@settings.com", "secret")
        owner_membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@settings.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)
    viewer_token = saas_service.build_access_token(viewer, viewer_membership)

    read_resp = client.get(
        "/v1/admin/settings/org",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert read_resp.status_code == 200
    payload = read_resp.json()
    assert payload["timezone"] == "America/Edmonton"

    update_resp = client.patch(
        "/v1/admin/settings/org",
        json={
            "timezone": "America/Denver",
            "currency": "USD",
            "language": "ru",
            "legal_name": "Clean Co",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert update_resp.status_code == 200
    update_payload = update_resp.json()
    assert update_payload["timezone"] == "America/Denver"
    assert update_payload["currency"] == "USD"
    assert update_payload["language"] == "ru"
    assert update_payload["legal_name"] == "Clean Co"

    forbidden = client.patch(
        "/v1/admin/settings/org",
        json={"timezone": "America/Edmonton"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert forbidden.status_code == 403


@pytest.mark.anyio
async def test_timezone_updates_are_persisted(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Timezone Org")
        owner = await saas_service.create_user(session, "owner@tz.com", "secret")
        owner_membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)

    update_resp = client.patch(
        "/v1/admin/settings/org",
        json={"timezone": "America/Denver"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert update_resp.status_code == 200

    read_resp = client.get(
        "/v1/admin/settings/org",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert read_resp.status_code == 200
    assert read_resp.json()["timezone"] == "America/Denver"
