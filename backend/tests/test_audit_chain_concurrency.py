import asyncio
import uuid
import pytest
import sqlalchemy as sa
from datetime import timezone
from unittest.mock import MagicMock, AsyncMock, patch
from app.domain.admin_audit.service import record_system_action, _calculate_entry_hash, verify_chain, _acquire_org_lock
from app.domain.admin_audit.db_models import AdminAuditLog
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.anyio
async def test_concurrent_audit_inserts_chain_integrity(async_session_maker):
    # Check dialect and skip if sqlite
    async with async_session_maker() as session:
        if session.bind.dialect.name == "sqlite":
            pytest.skip("Skipping concurrency test on SQLite as it lacks advisory locks")

    org_id = uuid.uuid4()

    # Define a worker function
    async def worker(idx: int):
        async with async_session_maker() as session:
            await record_system_action(
                session=session,
                org_id=org_id,
                action=f"concurrent_action_{idx}",
                resource_type="test_resource",
                resource_id=f"res_{idx}",
                context={"idx": idx}
            )
            await session.commit()

    # Run concurrent workers
    tasks = [worker(i) for i in range(20)]
    await asyncio.gather(*tasks)

    # Verify chain
    async with async_session_maker() as session:
        # Fetch all logs for org
        stmt = sa.select(AdminAuditLog).where(
            AdminAuditLog.org_id == org_id
        ).order_by(
            AdminAuditLog.created_at.desc(),
            AdminAuditLog.audit_id.desc()
        )
        result = await session.execute(stmt)
        logs = result.scalars().all()

        assert len(logs) == 20

        # Verify chain locally in test
        # Reverse to get chronological order (oldest first)
        chronological_logs = list(logs)[::-1]

        previous_hash = None

        for i, log in enumerate(chronological_logs):
            # Fix for SQLite tests where datetime might be returned as naive
            if log.created_at and log.created_at.tzinfo is None:
                log.created_at = log.created_at.replace(tzinfo=timezone.utc)

            # 1. Check prev_hash matches previous log's hash
            if i > 0:
                 assert log.prev_hash == previous_hash, f"Chain broken at index {i}. Log prev_hash {log.prev_hash} != {previous_hash}"

            # 2. Check internal hash integrity
            calculated = _calculate_entry_hash(log, log.prev_hash)
            assert log.hash == calculated, f"Hash mismatch at index {i}"

            previous_hash = log.hash

        # 4. Verify using the service function
        is_valid = await verify_chain(session, org_id)
        assert is_valid, "verify_chain returned False"


@pytest.mark.anyio
async def test_advisory_lock_called_on_postgres():
    # Mock session
    session = AsyncMock(spec=AsyncSession)
    session.bind = MagicMock()
    session.bind.dialect.name = "postgresql"
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=None) # _get_last_hash returns None

    org_id = uuid.uuid4()

    await record_system_action(
        session=session,
        org_id=org_id,
        action="test_action",
        resource_type="test",
        resource_id="123"
    )

    # Check if lock was acquired
    # We expect call to execute with specific text
    # Verify _acquire_org_lock logic

    # Inspect calls
    found_lock_call = False
    for call in session.execute.call_args_list:
        args, _ = call
        if len(args) > 0 and isinstance(args[0], sa.sql.elements.TextClause):
            if "pg_advisory_xact_lock" in str(args[0]):
                found_lock_call = True
                break

    assert found_lock_call, "pg_advisory_xact_lock was not called on Postgres dialect"


@pytest.mark.anyio
async def test_advisory_lock_skipped_on_sqlite():
    # Mock session
    session = AsyncMock(spec=AsyncSession)
    session.bind = MagicMock()
    session.bind.dialect.name = "sqlite"
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=None)

    org_id = uuid.uuid4()

    await record_system_action(
        session=session,
        org_id=org_id,
        action="test_action",
        resource_type="test",
        resource_id="123"
    )

    # Check if lock was NOT acquired
    found_lock_call = False
    for call in session.execute.call_args_list:
        args, _ = call
        if len(args) > 0 and isinstance(args[0], sa.sql.elements.TextClause):
            if "pg_advisory_xact_lock" in str(args[0]):
                found_lock_call = True
                break

    assert not found_lock_call, "pg_advisory_xact_lock should not be called on SQLite dialect"
