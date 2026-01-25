import asyncio

import pytest

from app.domain.org_settings import service as org_settings_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole, Organization
from app.infra.metrics import metrics


def _counter_value(counter, **labels) -> float:
    if labels:
        return counter.labels(**labels)._value.get()
    return counter._value.get()


@pytest.mark.anyio
async def test_org_user_quota_unlimited_allows_creation(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Unlimited Org")
        admin = await saas_service.create_user(session, "admin@unlimited.com", "AdminPass123!")
        membership = await saas_service.create_membership(session, org, admin, MembershipRole.ADMIN)
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.max_users = None
        await session.commit()

    token = saas_service.build_access_token(admin, membership)

    first = client.post(
        "/v1/iam/users",
        json={"email": "user1@unlimited.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/iam/users",
        json={"email": "user2@unlimited.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200


@pytest.mark.anyio
async def test_org_user_quota_allows_n_rejects_n_plus_one(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Quota Org")
        admin = await saas_service.create_user(session, "admin@quota.com", "AdminPass123!")
        membership = await saas_service.create_membership(session, org, admin, MembershipRole.ADMIN)
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.max_users = 1
        await session.commit()

    token = saas_service.build_access_token(admin, membership)

    first = client.post(
        "/v1/iam/users",
        json={"email": "user1@quota.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200

    baseline = _counter_value(metrics.org_user_quota_rejections, reason="max_users")

    second = client.post(
        "/v1/iam/users",
        json={"email": "user2@quota.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 409
    payload = second.json()
    assert payload["errors"][0]["code"] == "ORG_USER_QUOTA_EXCEEDED"
    assert _counter_value(metrics.org_user_quota_rejections, reason="max_users") == baseline + 1


@pytest.mark.anyio
async def test_org_user_quota_zero_rejects(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Zero Org")
        admin = await saas_service.create_user(session, "admin@zero.com", "AdminPass123!")
        membership = await saas_service.create_membership(session, org, admin, MembershipRole.ADMIN)
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.max_users = 0
        await session.commit()

    token = saas_service.build_access_token(admin, membership)

    response = client.post(
        "/v1/iam/users",
        json={"email": "blocked@zero.com", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    payload = response.json()
    assert payload["errors"][0]["code"] == "ORG_USER_QUOTA_EXCEEDED"


@pytest.mark.anyio
async def test_org_user_quota_concurrency(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Concurrent Org")
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.max_users = 1
        await session.commit()

    async def _attempt(email: str) -> str:
        async with async_session_maker() as session:
            org_ref = await session.get(Organization, org.org_id)
            try:
                await saas_service.enforce_org_user_quota(
                    session,
                    org.org_id,
                    attempted_action="test_concurrency",
                    audit_identity=None,
                )
                user = await saas_service.create_user(session, email)
                await saas_service.create_membership(session, org_ref, user, MembershipRole.WORKER)
                await asyncio.sleep(0.05)
                await session.commit()
                return "created"
            except saas_service.OrgUserQuotaExceeded:
                await session.rollback()
                return "rejected"

    results = await asyncio.gather(
        _attempt("user1@concurrency.com"),
        _attempt("user2@concurrency.com"),
    )

    assert results.count("created") == 1

    async with async_session_maker() as session:
        count = await saas_service.count_active_memberships(session, org.org_id)
        assert count == 1


@pytest.mark.anyio
async def test_org_user_quota_snapshot_in_settings(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Settings Quota Org")
        owner = await saas_service.create_user(session, "owner@settings-quota.com", "OwnerPass123!")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await session.commit()

    token = saas_service.build_access_token(owner, membership)

    read_resp = client.get(
        "/v1/admin/settings/org",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert read_resp.status_code == 200
    payload = read_resp.json()
    assert payload["current_users_count"] == 1
    assert payload["max_users"] is None

    update_resp = client.patch(
        "/v1/admin/settings/org",
        json={"max_users": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_resp.status_code == 200
    update_payload = update_resp.json()
    assert update_payload["max_users"] == 2
    assert update_payload["current_users_count"] == 1
