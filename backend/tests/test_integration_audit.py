import base64
import json

import pytest
import sqlalchemy as sa

from app.api.admin_auth import AdminIdentity, AdminRole
from app.domain.config_audit import service as config_audit_service
from app.domain.integration_audit import IntegrationAuditAction
from app.domain.integration_audit.db_models import IntegrationAuditLog
from app.domain.integration_audit import service as integration_audit_service
from app.domain.integrations import gcal_service, qbo_service
from app.domain.saas import service as saas_service
from app.settings import settings


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.anyio
async def test_integration_enable_disable_audited(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Integration Audit Org")
        await gcal_service.upsert_google_account(
            session,
            org.org_id,
            "refresh-token",
            ["scope1"],
            audit_actor=config_audit_service.system_actor("tests"),
            request_id="req-1",
        )
        await gcal_service.disconnect_google_calendar(
            session,
            org.org_id,
            audit_actor=config_audit_service.system_actor("tests"),
            request_id="req-2",
        )
        await session.commit()

    async with async_session_maker() as session:
        logs = (
            await session.scalars(
                sa.select(IntegrationAuditLog)
                .where(
                    IntegrationAuditLog.integration_type == "google_calendar",
                    IntegrationAuditLog.org_id == org.org_id,
                )
                .order_by(IntegrationAuditLog.occurred_at.asc(), IntegrationAuditLog.audit_id.asc())
            )
        ).all()
        assert len(logs) == 2
        assert logs[0].action == IntegrationAuditAction.ENABLE.value
        assert logs[1].action == IntegrationAuditAction.DELETE.value


@pytest.mark.anyio
async def test_integration_secret_rotation_redacted(async_session_maker):
    async with async_session_maker() as session:
        await qbo_service.upsert_account(
            session,
            settings.default_org_id,
            "refresh-secret-1",
            "realm-123",
            audit_actor=config_audit_service.system_actor("tests"),
            request_id="req-1",
        )
        await qbo_service.upsert_account(
            session,
            settings.default_org_id,
            "refresh-secret-2",
            "realm-123",
            audit_actor=config_audit_service.system_actor("tests"),
            request_id="req-2",
        )
        await session.commit()

    async with async_session_maker() as session:
        logs = (
            await session.scalars(
                sa.select(IntegrationAuditLog)
                .where(
                    IntegrationAuditLog.integration_type == "quickbooks",
                    IntegrationAuditLog.request_id.in_(["req-1", "req-2"]),
                )
                .order_by(IntegrationAuditLog.occurred_at.asc(), IntegrationAuditLog.audit_id.asc())
            )
        ).all()
        assert len(logs) == 2
        rotation_log = logs[1]
        assert rotation_log.action == IntegrationAuditAction.ROTATE_SECRET.value
        assert rotation_log.after_state["encrypted_refresh_token"] == "***REDACTED***"
        assert rotation_log.after_state["encrypted_refresh_token_present"] is True
        assert rotation_log.after_state["encrypted_refresh_token_fingerprint"].startswith("sha256:")
        assert "encrypted_refresh_token" in rotation_log.redaction_map
        assert "refresh-secret-2" not in json.dumps(rotation_log.after_state)


@pytest.mark.anyio
async def test_integration_actor_attribution(async_session_maker):
    identity = AdminIdentity(username="owner", role=AdminRole.OWNER, org_id=settings.default_org_id)
    actor = config_audit_service.admin_actor(identity, auth_method="basic")

    async with async_session_maker() as session:
        await gcal_service.upsert_google_account(
            session,
            settings.default_org_id,
            "refresh-token",
            ["scope1"],
            audit_actor=actor,
            request_id="req-actor",
        )
        await session.commit()

    async with async_session_maker() as session:
        log = await session.scalar(
            sa.select(IntegrationAuditLog)
            .where(
                IntegrationAuditLog.integration_type == "google_calendar",
                IntegrationAuditLog.request_id == "req-actor",
            )
            .order_by(IntegrationAuditLog.occurred_at.desc(), IntegrationAuditLog.audit_id.desc())
        )
        assert log is not None
        assert log.actor_type == actor.actor_type.value
        assert log.actor_id == "owner"
        assert log.actor_role == "owner"
        assert log.auth_method == "basic"


@pytest.mark.anyio
async def test_failed_integration_update_has_no_audit(async_session_maker, monkeypatch):
    async def _raise(*_args, **_kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(integration_audit_service, "audit_integration_config_change", _raise)

    async with async_session_maker() as session:
        with pytest.raises(RuntimeError):
            await gcal_service.upsert_google_account(
                session,
                settings.default_org_id,
                "refresh-token",
                ["scope1"],
                audit_actor=config_audit_service.system_actor("tests"),
                request_id="req-fail",
            )
        await session.rollback()

    async with async_session_maker() as session:
        count = await session.scalar(
            sa.select(sa.func.count(IntegrationAuditLog.audit_id)).where(
                IntegrationAuditLog.request_id == "req-fail"
            )
        )
        assert count == 0


@pytest.mark.anyio
async def test_integration_audit_endpoint_filters(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    async with async_session_maker() as session:
        await qbo_service.upsert_account(
            session,
            settings.default_org_id,
            "refresh-secret",
            "realm-999",
            audit_actor=config_audit_service.system_actor("tests"),
            request_id="req-endpoint",
        )
        await session.commit()

    headers = _basic_auth_header("owner", "secret")
    response = client.get(
        "/v1/admin/integrations/audit?limit=1&offset=0&integration_type=quickbooks",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["next_offset"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["integration_type"] == "quickbooks"
