from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.domain.feature_flag_audit.db_models import FeatureFlagAuditLog
from app.domain.feature_flags.db_models import FeatureFlagDefinition
from app.domain.feature_flags import service as feature_flag_service
from app.domain.feature_modules import service as feature_service
from app.settings import settings


@pytest.mark.anyio
async def test_feature_flag_evaluation_updates_telemetry(async_session_maker):
    now = datetime.now(tz=timezone.utc) + timedelta(days=1)
    async with async_session_maker() as session:
        session.add(
            FeatureFlagDefinition(
                key="test.eval",
                owner="platform",
                purpose="telemetry",
                expires_at=now,
                lifecycle_state="active",
            )
        )
        await session.commit()

    feature_flag_service.reset_evaluation_cache()
    async with async_session_maker() as session:
        enabled = await feature_service.effective_feature_enabled(
            session, settings.default_org_id, "test.eval"
        )
        await session.commit()
        assert enabled is True

    async with async_session_maker() as session:
        record = await session.get(FeatureFlagDefinition, "test.eval")
        assert record is not None
        assert record.last_evaluated_at is not None
        assert record.evaluate_count == 1


@pytest.mark.anyio
async def test_feature_flag_evaluation_throttles_updates(async_session_maker):
    now = datetime.now(tz=timezone.utc)
    async with async_session_maker() as session:
        session.add(
            FeatureFlagDefinition(
                key="test.throttle",
                owner="platform",
                purpose="throttle",
                expires_at=now + timedelta(days=7),
                lifecycle_state="active",
            )
        )
        await session.commit()

    feature_flag_service.reset_evaluation_cache()
    async with async_session_maker() as session:
        await feature_flag_service.record_feature_flag_evaluation(
            session,
            "test.throttle",
            now=now,
            throttle_minutes=30,
        )
        await feature_flag_service.record_feature_flag_evaluation(
            session,
            "test.throttle",
            now=now + timedelta(minutes=10),
            throttle_minutes=30,
        )
        await feature_flag_service.record_feature_flag_evaluation(
            session,
            "test.throttle",
            now=now + timedelta(minutes=31),
            throttle_minutes=30,
        )
        await session.commit()

    async with async_session_maker() as session:
        record = await session.get(FeatureFlagDefinition, "test.throttle")
        assert record is not None
        assert record.evaluate_count == 2
        assert record.last_evaluated_at == now + timedelta(minutes=31)


@pytest.mark.anyio
async def test_stale_feature_flag_never_evaluated(async_session_maker):
    now = datetime.now(tz=timezone.utc)
    async with async_session_maker() as session:
        session.add_all(
            [
                FeatureFlagDefinition(
                    key="test.never",
                    owner="platform",
                    purpose="never",
                    expires_at=now + timedelta(days=30),
                    lifecycle_state="active",
                    last_evaluated_at=None,
                    evaluate_count=0,
                ),
                FeatureFlagDefinition(
                    key="test.recent",
                    owner="platform",
                    purpose="recent",
                    expires_at=now + timedelta(days=30),
                    lifecycle_state="active",
                    last_evaluated_at=now - timedelta(days=1),
                    evaluate_count=5,
                ),
            ]
        )
        await session.commit()

    async with async_session_maker() as session:
        records, total, _cutoff = await feature_flag_service.list_stale_feature_flag_definitions(
            session,
            include_never=True,
            inactive_days=None,
            now=now,
        )
        keys = {record.key for record in records}
        assert total == 1
        assert keys == {"test.never"}


@pytest.mark.anyio
async def test_stale_feature_flag_inactive_days(async_session_maker):
    now = datetime.now(tz=timezone.utc)
    async with async_session_maker() as session:
        session.add_all(
            [
                FeatureFlagDefinition(
                    key="test.inactive",
                    owner="platform",
                    purpose="inactive",
                    expires_at=now + timedelta(days=30),
                    lifecycle_state="active",
                    last_evaluated_at=now - timedelta(days=45),
                    evaluate_count=3,
                ),
                FeatureFlagDefinition(
                    key="test.active",
                    owner="platform",
                    purpose="active",
                    expires_at=now + timedelta(days=30),
                    lifecycle_state="active",
                    last_evaluated_at=now - timedelta(days=5),
                    evaluate_count=3,
                ),
            ]
        )
        await session.commit()

    async with async_session_maker() as session:
        records, total, _cutoff = await feature_flag_service.list_stale_feature_flag_definitions(
            session,
            include_never=False,
            inactive_days=30,
            now=now,
        )
        keys = {record.key for record in records}
        assert total == 1
        assert keys == {"test.inactive"}


@pytest.mark.anyio
async def test_feature_flag_evaluation_does_not_write_audit_logs(async_session_maker):
    now = datetime.now(tz=timezone.utc) + timedelta(days=1)
    async with async_session_maker() as session:
        session.add(
            FeatureFlagDefinition(
                key="test.privacy",
                owner="platform",
                purpose="privacy",
                expires_at=now,
                lifecycle_state="active",
            )
        )
        await session.commit()

    feature_flag_service.reset_evaluation_cache()
    async with async_session_maker() as session:
        await feature_service.effective_feature_enabled(
            session, settings.default_org_id, "test.privacy"
        )
        await session.commit()

    async with async_session_maker() as session:
        count = await session.scalar(sa.select(sa.func.count(FeatureFlagAuditLog.audit_id)))
        assert count == 0
