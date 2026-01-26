from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.reason_logs.db_models import ReasonLog
from app.jobs import log_retention
from app.settings import settings


@pytest.mark.anyio
async def test_log_retention_deletes_old_logs(async_session_maker):
    original_app_days = settings.retention_application_log_days
    settings.retention_application_log_days = 10
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add(
                ReasonLog(
                    reason_id="log-old",
                    order_id="booking-old",
                    kind="system",
                    code="retention",
                    created_at=now - timedelta(days=12),
                )
            )
            session.add(
                ReasonLog(
                    reason_id="log-new",
                    order_id="booking-new",
                    kind="system",
                    code="retention",
                    created_at=now - timedelta(days=2),
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            result = await log_retention.run_log_retention_daily(session)
            assert result["deleted"] == 1

        async with async_session_maker() as session:
            remaining_logs = await session.scalar(sa.select(sa.func.count(ReasonLog.reason_id)))
            assert remaining_logs == 1
    finally:
        settings.retention_application_log_days = original_app_days


@pytest.mark.anyio
async def test_log_retention_preserves_recent_logs(async_session_maker):
    original_app_days = settings.retention_application_log_days
    settings.retention_application_log_days = 10
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add(
                ReasonLog(
                    reason_id="log-recent",
                    order_id="booking-recent",
                    kind="system",
                    code="retention",
                    created_at=now - timedelta(days=2),
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            result = await log_retention.run_log_retention_daily(session)
            assert result["deleted"] == 0

        async with async_session_maker() as session:
            remaining_logs = await session.scalar(sa.select(sa.func.count(ReasonLog.reason_id)))
            assert remaining_logs == 1
    finally:
        settings.retention_application_log_days = original_app_days


@pytest.mark.anyio
async def test_log_retention_does_not_delete_audit_logs(async_session_maker):
    original_app_days = settings.retention_application_log_days
    settings.retention_application_log_days = 1
    try:
        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add(
                AdminAuditLog(
                    audit_id="audit-sentinel",
                    org_id=settings.default_org_id,
                    admin_id="admin-1",
                    action="audit-sentinel",
                    action_type="WRITE",
                    sensitivity_level="normal",
                    actor="tester",
                    role="system",
                    auth_method="system",
                    resource_type="test",
                    resource_id="test",
                    context={"note": "do not delete"},
                    before=None,
                    after=None,
                    created_at=now - timedelta(days=365),
                )
            )
            session.add(
                ReasonLog(
                    reason_id="log-audit-check",
                    order_id="booking-audit",
                    kind="system",
                    code="retention",
                    created_at=now - timedelta(days=5),
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            await log_retention.run_log_retention_daily(session)

        async with async_session_maker() as session:
            remaining_audit = await session.scalar(
                sa.select(sa.func.count(AdminAuditLog.audit_id)).where(
                    AdminAuditLog.action == "audit-sentinel"
                )
            )
            assert remaining_audit == 1
    finally:
        settings.retention_application_log_days = original_app_days
