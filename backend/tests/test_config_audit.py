import base64

import pytest
import sqlalchemy as sa

from app.domain.config_audit import ConfigAuditAction, ConfigActorType, ConfigScope
from app.domain.config_audit import service as config_audit_service
from app.domain.config_audit.db_models import ConfigAuditLog
from app.domain.integrations import qbo_service
from app.settings import settings


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.anyio
async def test_org_settings_update_audited_once(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _basic_auth_header("owner", "secret")
    response = client.patch(
        "/v1/admin/settings/org",
        json={"timezone": "UTC", "legal_name": "New Legal Name"},
        headers=headers,
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        result = await session.execute(sa.select(ConfigAuditLog))
        logs = result.scalars().all()
        assert len(logs) == 1
        log = logs[0]
        assert log.config_scope == ConfigScope.ORG_SETTINGS.value
        assert log.config_key == "org_settings"
        assert log.action == ConfigAuditAction.UPDATE.value
        assert log.actor_type == ConfigActorType.ADMIN.value
        assert log.actor_id == "owner"
        assert log.actor_role == "owner"
        assert log.auth_method == "basic"
        assert log.before_value["timezone"] == "America/Edmonton"
        assert log.after_value["timezone"] == "UTC"
        assert log.after_value["legal_name"] == "New Legal Name"


@pytest.mark.anyio
async def test_invalid_org_settings_update_does_not_audit(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _basic_auth_header("owner", "secret")
    response = client.patch(
        "/v1/admin/settings/org",
        json={"timezone": "Not/AZone"},
        headers=headers,
    )
    assert response.status_code == 422

    async with async_session_maker() as session:
        count = await session.scalar(sa.select(sa.func.count(ConfigAuditLog.audit_id)))
        assert count == 0


@pytest.mark.anyio
async def test_integration_audit_redacts_sensitive_fields(async_session_maker):
    async with async_session_maker() as session:
        await qbo_service.upsert_account(
            session,
            settings.default_org_id,
            "refresh-secret",
            "realm-123",
            audit_actor=config_audit_service.system_actor("tests"),
            request_id="req-1",
        )
        await session.commit()

    async with async_session_maker() as session:
        log = await session.scalar(
            sa.select(ConfigAuditLog).where(
                ConfigAuditLog.config_key == "integrations.accounting.quickbooks"
            )
        )
        assert log is not None
        assert log.after_value["encrypted_refresh_token"] == "[REDACTED]"


@pytest.mark.anyio
async def test_config_audit_endpoint_paginates(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _basic_auth_header("owner", "secret")
    response = client.patch(
        "/v1/admin/settings/org",
        json={"timezone": "UTC"},
        headers=headers,
    )
    assert response.status_code == 200

    response = client.patch(
        "/v1/admin/settings/features",
        json={"overrides": {"module.integrations": True}},
        headers=headers,
    )
    assert response.status_code == 200

    response = client.get(
        "/v1/admin/settings/audit/config?limit=1&offset=0",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["next_offset"] == 1
    assert len(payload["items"]) == 1
