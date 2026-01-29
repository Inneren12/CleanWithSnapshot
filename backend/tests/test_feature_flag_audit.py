import base64

import pytest
import sqlalchemy as sa

from app.domain.config_audit import service as config_audit_service
from app.domain.feature_flag_audit import service as feature_flag_audit_service
from app.domain.feature_flag_audit.db_models import FeatureFlagAuditAction, FeatureFlagAuditLog
from app.domain.feature_modules import service as feature_service
from app.settings import settings


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.anyio
async def test_feature_flag_enable_disable_audited(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _basic_auth_header("owner", "secret")
    response = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.schedule": False}, "reason": "maintenance window"},
        headers=headers,
    )
    assert response.status_code == 200
    response = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.schedule": True}, "reason": "rollout complete"},
        headers=headers,
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        result = await session.execute(
            sa.select(FeatureFlagAuditLog)
            .where(FeatureFlagAuditLog.flag_key == "module.schedule")
            .order_by(FeatureFlagAuditLog.occurred_at.asc(), FeatureFlagAuditLog.audit_id.asc())
        )
        logs = result.scalars().all()
        assert len(logs) == 2
        assert {log.action for log in logs} == {
            FeatureFlagAuditAction.DISABLE.value,
            FeatureFlagAuditAction.ENABLE.value,
        }
        assert logs[0].actor_id == "owner"
        assert logs[0].actor_role == "owner"
        assert logs[0].auth_method == "basic"
        assert logs[1].rollout_context["percentage"] == 100
        assert logs[0].rollout_context["percentage"] == 0


@pytest.mark.anyio
async def test_feature_flag_explicit_enable_audited(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _basic_auth_header("owner", "secret")
    response = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.analytics": True}, "reason": "explicit enable"},
        headers=headers,
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        log = await session.scalar(
            sa.select(FeatureFlagAuditLog)
            .where(FeatureFlagAuditLog.flag_key == "module.analytics")
            .order_by(FeatureFlagAuditLog.occurred_at.desc(), FeatureFlagAuditLog.audit_id.desc())
        )
        assert log is not None
        assert log.action == FeatureFlagAuditAction.ENABLE.value


@pytest.mark.anyio
async def test_feature_flag_rollout_context_and_redaction(async_session_maker):
    async with async_session_maker() as session:
        await feature_flag_audit_service.audit_feature_flag_change(
            session,
            actor=config_audit_service.system_actor("tests"),
            org_id=settings.default_org_id,
            flag_key="module.quality",
            action=FeatureFlagAuditAction.ROLLOUT_CHANGE,
            before_state={
                "enabled": True,
                "percentage": 50,
                "targeting_rules": [{"user_ids": ["user-1"], "segment": "beta"}],
                "secret_key": "plaintext",
            },
            after_state={
                "enabled": True,
                "percentage": 75,
                "targeting_rules": [{"user_ids": ["user-2"], "segment": "beta"}],
            },
            rollout_context=feature_flag_audit_service.build_rollout_context(
                enabled=True,
                targeting_rules=[{"user_ids": ["user-2"], "segment": "beta"}],
                reason="increase rollout",
            ),
            request_id="req-ff-1",
        )
        await session.commit()

    async with async_session_maker() as session:
        log = await session.scalar(
            sa.select(FeatureFlagAuditLog).where(FeatureFlagAuditLog.flag_key == "module.quality")
        )
        assert log is not None
        assert log.rollout_context["percentage"] == 100
        assert log.rollout_context["targeting_rules"][0]["user_ids"] == "[REDACTED]"
        assert log.before_state["targeting_rules"][0]["user_ids"] == "[REDACTED]"
        assert log.before_state["secret_key"] == "[REDACTED]"


@pytest.mark.anyio
async def test_invalid_feature_flag_update_does_not_audit(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _basic_auth_header("owner", "secret")
    response = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": "not-a-dict"},
        headers=headers,
    )
    assert response.status_code == 422

    async with async_session_maker() as session:
        count = await session.scalar(sa.select(sa.func.count(FeatureFlagAuditLog.audit_id)))
        assert count == 0


@pytest.mark.anyio
async def test_feature_flag_audit_endpoint_filters(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _basic_auth_header("owner", "secret")
    response = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.inventory": False}},
        headers=headers,
    )
    assert response.status_code == 200

    response = client.get(
        "/v1/admin/settings/audit/feature-flags?limit=1&offset=0&flag_key=module.inventory",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["next_offset"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["flag_key"] == "module.inventory"


def test_feature_flag_evaluation_unchanged():
    overrides = {"module.analytics": False}
    assert feature_service.effective_feature_enabled_from_overrides(overrides, "module.analytics") is False
    assert feature_service.effective_feature_enabled_from_overrides(overrides, "module.schedule") is True
