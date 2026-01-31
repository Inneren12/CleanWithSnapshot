from __future__ import annotations

import uuid

import pytest

from app.domain.feature_modules import service as feature_service
from app.domain.feature_modules.db_models import OrgFeatureConfig
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


@pytest.mark.anyio
async def test_rollout_percentage_is_deterministic(async_session_maker):
    settings.feature_flag_rollout_salt = "feature-flag-rollout-v1"
    org_one = uuid.UUID("00000000-0000-0000-0000-000000000001")
    org_two = uuid.UUID("00000000-0000-0000-0000-000000000002")

    async with async_session_maker() as session:
        session.add(
            OrgFeatureConfig(
                org_id=org_one,
                feature_overrides={"module.analytics": {"percentage": 25}},
            )
        )
        session.add(
            OrgFeatureConfig(
                org_id=org_two,
                feature_overrides={"module.analytics": {"percentage": 25}},
            )
        )
        await session.commit()

    async with async_session_maker() as session:
        enabled_one = await feature_service.effective_feature_enabled(
            session, org_one, "module.analytics"
        )
        enabled_two = await feature_service.effective_feature_enabled(
            session, org_two, "module.analytics"
        )
        enabled_one_repeat = await feature_service.effective_feature_enabled(
            session, org_one, "module.analytics"
        )

    assert enabled_one is True
    assert enabled_two is False
    assert enabled_one == enabled_one_repeat


@pytest.mark.anyio
async def test_boolean_override_wins_over_percentage(async_session_maker):
    org_id = uuid.UUID("00000000-0000-0000-0000-000000000003")
    async with async_session_maker() as session:
        session.add(
            OrgFeatureConfig(
                org_id=org_id,
                feature_overrides={"module.analytics": {"enabled": False, "percentage": 100}},
            )
        )
        await session.commit()

    async with async_session_maker() as session:
        enabled = await feature_service.effective_feature_enabled(
            session, org_id, "module.analytics"
        )

    assert enabled is False


@pytest.mark.anyio
async def test_rollout_percentage_validation_in_admin_api(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Rollout Org")
        owner = await saas_service.create_user(session, "owner@rollout.com", "secret")
        owner_membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)

    valid_resp = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.schedule": {"percentage": 25}}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert valid_resp.status_code == 200
    payload = valid_resp.json()
    assert payload["overrides"]["module.schedule"]["percentage"] == 25

    invalid_resp = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.schedule": {"percentage": 33}}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert invalid_resp.status_code == 422
