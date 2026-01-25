from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.domain.feature_flag_audit.db_models import FeatureFlagAuditAction, FeatureFlagAuditLog
from app.domain.feature_flags.db_models import FeatureFlagDefinition
from app.domain.feature_modules.db_models import OrgFeatureConfig
from app.domain.feature_modules import service as feature_service
from app.domain.saas import service as saas_service
from app.settings import settings


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.anyio
async def test_feature_flag_creation_requires_metadata(client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _basic_auth_header("owner", "secret")
    response = client.post(
        "/v1/admin/settings/feature-flags",
        json={"key": "test.metadata", "owner": "platform", "purpose": "required"},
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.anyio
async def test_feature_flag_update_blocked_when_expired(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    expired_at = datetime.now(tz=timezone.utc) - timedelta(days=1)
    async with async_session_maker() as session:
        session.add(
            FeatureFlagDefinition(
                key="test.expired",
                owner="platform",
                purpose="expired flag",
                expires_at=expired_at,
                lifecycle_state="active",
            )
        )
        await session.commit()

    headers = _basic_auth_header("owner", "secret")
    response = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"test.expired": True}, "reason": "attempt"},
        headers=headers,
    )
    assert response.status_code == 400

    response = client.patch(
        "/v1/admin/settings/features",
        json={
            "overrides": {"test.expired": True},
            "allow_expired_override": True,
            "override_reason": "incident rollback",
        },
        headers=headers,
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        override_log = await session.scalar(
            sa.select(FeatureFlagAuditLog).where(
                FeatureFlagAuditLog.flag_key == "test.expired",
                FeatureFlagAuditLog.action == FeatureFlagAuditAction.OVERRIDE.value,
            )
        )
        assert override_log is not None


@pytest.mark.anyio
async def test_expired_flags_auto_disable(async_session_maker):
    expired_at = datetime.now(tz=timezone.utc) - timedelta(days=2)
    async with async_session_maker() as session:
        session.add(
            FeatureFlagDefinition(
                key="test.expired-eval",
                owner="platform",
                purpose="expired evaluation",
                expires_at=expired_at,
                lifecycle_state="active",
            )
        )
        session.add(
            OrgFeatureConfig(
                org_id=settings.default_org_id,
                feature_overrides={"test.expired-eval": True},
            )
        )
        await session.commit()

    async with async_session_maker() as session:
        enabled = await feature_service.effective_feature_enabled(
            session, settings.default_org_id, "test.expired-eval"
        )
        assert enabled is False


@pytest.mark.anyio
async def test_feature_flag_lifecycle_transitions_audited(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _basic_auth_header("owner", "secret")
    expires_at = (datetime.now(tz=timezone.utc) + timedelta(days=30)).isoformat()
    response = client.post(
        "/v1/admin/settings/feature-flags",
        json={
            "key": "test.lifecycle",
            "owner": "platform",
            "purpose": "lifecycle coverage",
            "expires_at": expires_at,
        },
        headers=headers,
    )
    assert response.status_code == 201

    response = client.patch(
        "/v1/admin/settings/feature-flags/test.lifecycle",
        json={"lifecycle_state": "active"},
        headers=headers,
    )
    assert response.status_code == 200

    response = client.patch(
        "/v1/admin/settings/feature-flags/test.lifecycle",
        json={"lifecycle_state": "expired"},
        headers=headers,
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        result = await session.execute(
            sa.select(FeatureFlagAuditLog.action).where(
                FeatureFlagAuditLog.flag_key == "test.lifecycle"
            )
        )
        actions = {row[0] for row in result.fetchall()}
        assert FeatureFlagAuditAction.CREATE.value in actions
        assert FeatureFlagAuditAction.ACTIVATE.value in actions
        assert FeatureFlagAuditAction.EXPIRE.value in actions


@pytest.mark.anyio
async def test_legacy_flag_without_metadata_still_loads(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Legacy Flags Org")
        session.add(
            OrgFeatureConfig(
                org_id=org.org_id,
                feature_overrides={"legacy.missing": True},
            )
        )
        await session.commit()

    headers = _basic_auth_header("owner", "secret")
    response = client.get(
        "/v1/admin/settings/features",
        headers={**headers, "X-Test-Org": str(org.org_id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["overrides"]["legacy.missing"] is True
