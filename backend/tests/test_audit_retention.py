from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.audit_retention import service as audit_retention_service
from app.domain.audit_retention.db_models import AuditLegalHold, AuditLogScope
from app.domain.config_audit.db_models import ConfigAuditLog
from app.settings import settings


def _admin_log(created_at: datetime) -> AdminAuditLog:
    return AdminAuditLog(
        org_id=settings.default_org_id,
        admin_id="system",
        action="audit_retention_test",
        action_type="WRITE",
        sensitivity_level="normal",
        actor="system",
        role="system",
        auth_method="automation",
        resource_type="audit_retention",
        resource_id="test",
        context=None,
        before=None,
        after=None,
        created_at=created_at,
    )


def _config_log(occurred_at: datetime) -> ConfigAuditLog:
    return ConfigAuditLog(
        actor_type="system",
        actor_id=None,
        actor_role=None,
        auth_method=None,
        actor_source="tests",
        org_id=settings.default_org_id,
        config_scope="org_settings",
        config_key="org_settings",
        action="update",
        before_value={"timezone": "UTC"},
        after_value={"timezone": "UTC"},
        request_id="req-audit-retention",
        occurred_at=occurred_at,
    )


@pytest.mark.anyio
async def test_records_younger_than_retention_not_deleted(async_session_maker):
    original_admin_retention = settings.audit_retention_admin_days
    settings.audit_retention_admin_days = 30
    try:
        async with async_session_maker() as session:
            session.add(_admin_log(datetime.now(tz=timezone.utc) - timedelta(days=5)))
            await session.commit()

        async with async_session_maker() as session:
            await audit_retention_service.run_audit_retention(session, dry_run=False, batch_size=10)

        async with async_session_maker() as session:
            count = await session.scalar(sa.select(sa.func.count(AdminAuditLog.audit_id)))
            assert count == 1
    finally:
        settings.audit_retention_admin_days = original_admin_retention


@pytest.mark.anyio
async def test_records_older_than_retention_deleted(async_session_maker):
    original_admin_retention = settings.audit_retention_admin_days
    settings.audit_retention_admin_days = 1
    try:
        async with async_session_maker() as session:
            session.add(_admin_log(datetime.now(tz=timezone.utc) - timedelta(days=10)))
            await session.commit()

        async with async_session_maker() as session:
            result = await audit_retention_service.run_audit_retention(session, dry_run=False, batch_size=10)
            assert result["purged"] == 1

        async with async_session_maker() as session:
            count = await session.scalar(sa.select(sa.func.count(AdminAuditLog.audit_id)))
            assert count == 0
    finally:
        settings.audit_retention_admin_days = original_admin_retention


@pytest.mark.anyio
async def test_legal_hold_prevents_deletion(async_session_maker):
    original_admin_retention = settings.audit_retention_admin_days
    settings.audit_retention_admin_days = 1
    try:
        occurred_at = datetime.now(tz=timezone.utc) - timedelta(days=10)
        async with async_session_maker() as session:
            session.add(_admin_log(occurred_at))
            session.add(
                AuditLegalHold(
                    org_id=settings.default_org_id,
                    audit_scope=AuditLogScope.ADMIN.value,
                    applies_from=occurred_at - timedelta(days=1),
                    applies_to=occurred_at + timedelta(days=1),
                    investigation_id="hold-123",
                    reason="legal hold for investigation",
                    created_by="compliance",
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            result = await audit_retention_service.run_audit_retention(session, dry_run=False, batch_size=10)
            assert result["purged"] == 0
            assert result["on_hold"] == 1

        async with async_session_maker() as session:
            count = await session.scalar(sa.select(sa.func.count(AdminAuditLog.audit_id)))
            assert count == 1
    finally:
        settings.audit_retention_admin_days = original_admin_retention


@pytest.mark.anyio
async def test_job_idempotency(async_session_maker):
    original_admin_retention = settings.audit_retention_admin_days
    settings.audit_retention_admin_days = 1
    try:
        async with async_session_maker() as session:
            session.add(_admin_log(datetime.now(tz=timezone.utc) - timedelta(days=10)))
            await session.commit()

        async with async_session_maker() as session:
            first = await audit_retention_service.run_audit_retention(session, dry_run=False, batch_size=10)
            assert first["purged"] == 1

        async with async_session_maker() as session:
            second = await audit_retention_service.run_audit_retention(session, dry_run=False, batch_size=10)
            assert second["purged"] == 0

        async with async_session_maker() as session:
            count = await session.scalar(sa.select(sa.func.count(AdminAuditLog.audit_id)))
            assert count == 0
    finally:
        settings.audit_retention_admin_days = original_admin_retention


@pytest.mark.anyio
async def test_config_audit_retention_applies(async_session_maker):
    original_config_retention = settings.audit_retention_config_days
    settings.audit_retention_config_days = 1
    try:
        async with async_session_maker() as session:
            session.add(_config_log(datetime.now(tz=timezone.utc) - timedelta(days=10)))
            await session.commit()

        async with async_session_maker() as session:
            await audit_retention_service.run_audit_retention(session, dry_run=False, batch_size=10)

        async with async_session_maker() as session:
            count = await session.scalar(sa.select(sa.func.count(ConfigAuditLog.audit_id)))
            assert count == 0
    finally:
        settings.audit_retention_config_days = original_config_retention


@pytest.mark.anyio
async def test_admin_audit_immutability_preserved(async_session_maker):
    async with async_session_maker() as session:
        log = _admin_log(datetime.now(tz=timezone.utc))
        session.add(log)
        await session.commit()
        await session.refresh(log)

        with pytest.raises(ValueError):
            log.action = "tamper"
            await session.flush()
