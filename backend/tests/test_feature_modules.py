import pytest

from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole


@pytest.mark.anyio
async def test_owner_can_update_feature_config(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Feature Org")
        owner = await saas_service.create_user(session, "owner@example.com", "secret")
        owner_membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        dispatcher = await saas_service.create_user(session, "dispatcher@example.com", "secret")
        dispatcher_membership = await saas_service.create_membership(
            session, org, dispatcher, MembershipRole.DISPATCHER
        )
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)
    dispatcher_token = saas_service.build_access_token(dispatcher, dispatcher_membership)

    read_resp = client.get(
        "/v1/admin/settings/features",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert read_resp.status_code == 200
    payload = read_resp.json()
    assert payload["defaults"]["module.dashboard"] is True

    update_resp = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.schedule": False}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert update_resp.status_code == 200
    update_payload = update_resp.json()
    assert update_payload["overrides"]["module.schedule"] is False

    forbidden = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.schedule": True}},
        headers={"Authorization": f"Bearer {dispatcher_token}"},
    )
    assert forbidden.status_code == 403


@pytest.mark.anyio
async def test_user_ui_prefs_are_scoped_to_self(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Prefs Org")
        owner = await saas_service.create_user(session, "owner@prefs.com", "secret")
        owner_membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer = await saas_service.create_user(session, "viewer@prefs.com", "secret")
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)
    viewer_token = saas_service.build_access_token(viewer, viewer_membership)

    update_resp = client.patch(
        "/v1/admin/users/me/ui_prefs",
        json={"hidden_keys": ["dashboard.weather", "finance.reports"]},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["hidden_keys"] == ["dashboard.weather", "finance.reports"]

    viewer_resp = client.get(
        "/v1/admin/users/me/ui_prefs",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert viewer_resp.status_code == 200
    assert viewer_resp.json()["hidden_keys"] == []


@pytest.mark.anyio
async def test_disabled_feature_blocks_dispatcher_board(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Guard Org")
        owner = await saas_service.create_user(session, "owner@guard.com", "secret")
        owner_membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        dispatcher = await saas_service.create_user(session, "dispatch@guard.com", "secret")
        dispatcher_membership = await saas_service.create_membership(
            session, org, dispatcher, MembershipRole.DISPATCHER
        )
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)
    dispatcher_token = saas_service.build_access_token(dispatcher, dispatcher_membership)

    disable_resp = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.schedule": False}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert disable_resp.status_code == 200

    blocked = client.get(
        "/v1/admin/dispatcher/board?date=2026-01-10",
        headers={"Authorization": f"Bearer {dispatcher_token}"},
    )
    assert blocked.status_code == 403
