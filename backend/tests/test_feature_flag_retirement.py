from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.domain.feature_flag_audit.db_models import FeatureFlagAuditAction, FeatureFlagAuditLog
from app.domain.feature_flags.db_models import FeatureFlagDefinition, FeatureFlagLifecycleState
from app.jobs import flag_retirement
from app.settings import settings


def _restore_retirement_settings():
    return (
        settings.flag_retire_expired,
        settings.flag_retire_stale_days,
        settings.flag_retire_dry_run,
        settings.flag_retire_recent_evaluation_days,
    )


def _apply_retirement_settings(values) -> None:
    (
        settings.flag_retire_expired,
        settings.flag_retire_stale_days,
        settings.flag_retire_dry_run,
        settings.flag_retire_recent_evaluation_days,
    ) = values


@pytest.mark.anyio
async def test_expired_flags_retired(async_session_maker):
    original = _restore_retirement_settings()
    try:
        settings.flag_retire_expired = True
        settings.flag_retire_stale_days = 0
        settings.flag_retire_dry_run = False
        settings.flag_retire_recent_evaluation_days = 0

        expired_at = datetime.now(tz=timezone.utc) - timedelta(days=2)
        async with async_session_maker() as session:
            session.add(
                FeatureFlagDefinition(
                    key="test.retire.expired",
                    owner="platform",
                    purpose="expired retirement",
                    expires_at=expired_at,
                    lifecycle_state=FeatureFlagLifecycleState.ACTIVE.value,
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            await flag_retirement.run_feature_flag_retirement(session)

        async with async_session_maker() as session:
            record = await session.get(FeatureFlagDefinition, "test.retire.expired")
            assert record is not None
            assert record.lifecycle_state == FeatureFlagLifecycleState.RETIRED.value
            audit = await session.scalar(
                sa.select(FeatureFlagAuditLog).where(
                    FeatureFlagAuditLog.flag_key == "test.retire.expired",
                    FeatureFlagAuditLog.action == FeatureFlagAuditAction.RETIRE.value,
                )
            )
            assert audit is not None
    finally:
        _apply_retirement_settings(original)


@pytest.mark.anyio
async def test_pinned_flags_not_retired(async_session_maker):
    original = _restore_retirement_settings()
    try:
        settings.flag_retire_expired = True
        settings.flag_retire_stale_days = 0
        settings.flag_retire_dry_run = False
        settings.flag_retire_recent_evaluation_days = 0

        expired_at = datetime.now(tz=timezone.utc) - timedelta(days=5)
        async with async_session_maker() as session:
            session.add(
                FeatureFlagDefinition(
                    key="test.retire.pinned",
                    owner="platform",
                    purpose="pinned flag",
                    expires_at=expired_at,
                    lifecycle_state=FeatureFlagLifecycleState.ACTIVE.value,
                    pinned=True,
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            await flag_retirement.run_feature_flag_retirement(session)

        async with async_session_maker() as session:
            record = await session.get(FeatureFlagDefinition, "test.retire.pinned")
            assert record is not None
            assert record.lifecycle_state == FeatureFlagLifecycleState.ACTIVE.value
            audit = await session.scalar(
                sa.select(FeatureFlagAuditLog).where(
                    FeatureFlagAuditLog.flag_key == "test.retire.pinned",
                    FeatureFlagAuditLog.action == FeatureFlagAuditAction.RETIRE.value,
                )
            )
            assert audit is None
    finally:
        _apply_retirement_settings(original)


@pytest.mark.anyio
async def test_stale_flags_retired_when_enabled(async_session_maker):
    original = _restore_retirement_settings()
    try:
        settings.flag_retire_expired = False
        settings.flag_retire_stale_days = 90
        settings.flag_retire_dry_run = False
        settings.flag_retire_recent_evaluation_days = 0

        now = datetime.now(tz=timezone.utc)
        async with async_session_maker() as session:
            session.add(
                FeatureFlagDefinition(
                    key="test.retire.stale",
                    owner="platform",
                    purpose="stale retirement",
                    expires_at=now + timedelta(days=30),
                    lifecycle_state=FeatureFlagLifecycleState.ACTIVE.value,
                    last_evaluated_at=now - timedelta(days=120),
                    evaluate_count=1,
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            await flag_retirement.run_feature_flag_retirement(session)

        async with async_session_maker() as session:
            record = await session.get(FeatureFlagDefinition, "test.retire.stale")
            assert record is not None
            assert record.lifecycle_state == FeatureFlagLifecycleState.RETIRED.value
    finally:
        _apply_retirement_settings(original)


@pytest.mark.anyio
async def test_retirement_dry_run_makes_no_changes(async_session_maker):
    original = _restore_retirement_settings()
    try:
        settings.flag_retire_expired = True
        settings.flag_retire_stale_days = 0
        settings.flag_retire_dry_run = True
        settings.flag_retire_recent_evaluation_days = 0

        expired_at = datetime.now(tz=timezone.utc) - timedelta(days=2)
        async with async_session_maker() as session:
            session.add(
                FeatureFlagDefinition(
                    key="test.retire.dryrun",
                    owner="platform",
                    purpose="dry run",
                    expires_at=expired_at,
                    lifecycle_state=FeatureFlagLifecycleState.ACTIVE.value,
                )
            )
            await session.commit()

        async with async_session_maker() as session:
            await flag_retirement.run_feature_flag_retirement(session)

        async with async_session_maker() as session:
            record = await session.get(FeatureFlagDefinition, "test.retire.dryrun")
            assert record is not None
            assert record.lifecycle_state == FeatureFlagLifecycleState.ACTIVE.value
            audit_count = await session.scalar(
                sa.select(sa.func.count(FeatureFlagAuditLog.audit_id)).where(
                    FeatureFlagAuditLog.flag_key == "test.retire.dryrun",
                    FeatureFlagAuditLog.action == FeatureFlagAuditAction.RETIRE.value,
                )
            )
            assert audit_count == 0
    finally:
        _apply_retirement_settings(original)
