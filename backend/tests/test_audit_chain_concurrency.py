import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.admin_audit.service import _calculate_entry_hash, record_system_action, verify_chain


@pytest.mark.anyio
async def test_concurrent_audit_inserts_chain_integrity(async_session_maker):
    async with async_session_maker() as session:
        bind = session.bind
        if not bind or bind.dialect.name != "postgresql":
            pytest.skip("Skipping concurrency test when PostgreSQL advisory locks are unavailable")

    org_id = uuid.uuid4()

    async def worker(idx: int):
        async with async_session_maker() as session:
            await record_system_action(
                session=session,
                org_id=org_id,
                action=f"concurrent_action_{idx}",
                resource_type="test_resource",
                resource_id=f"res_{idx}",
                context={"idx": idx},
            )
            await session.commit()

    await asyncio.gather(*[worker(i) for i in range(20)])

    async with async_session_maker() as session:
        stmt = sa.select(AdminAuditLog).where(AdminAuditLog.org_id == org_id).order_by(
            AdminAuditLog.created_at.desc(),
            AdminAuditLog.audit_id.desc(),
        )
        result = await session.execute(stmt)
        logs = result.scalars().all()

        assert len(logs) == 20

        chronological_logs = list(logs)[::-1]
        previous_hash = None

        for i, log in enumerate(chronological_logs):
            if i > 0:
                assert log.prev_hash == previous_hash, (
                    f"Chain broken at index {i}. Log prev_hash {log.prev_hash} != {previous_hash}"
                )

            calculated = _calculate_entry_hash(log, log.prev_hash)
            assert log.hash == calculated, f"Hash mismatch at index {i}"
            previous_hash = log.hash

        is_valid = await verify_chain(session, org_id)
        assert is_valid, "verify_chain returned False"


@pytest.mark.anyio
async def test_advisory_lock_called_on_postgres():
    session = AsyncMock(spec=AsyncSession)
    session.bind = MagicMock()
    session.bind.dialect.name = "postgresql"
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=None)

    await record_system_action(
        session=session,
        org_id=uuid.uuid4(),
        action="test_action",
        resource_type="test",
        resource_id="123",
    )

    found_lock_call = False
    for call in session.execute.call_args_list:
        args, _ = call
        if args and isinstance(args[0], sa.sql.elements.TextClause) and "pg_advisory_xact_lock" in str(args[0]):
            found_lock_call = True
            break

    assert found_lock_call, "pg_advisory_xact_lock was not called on Postgres dialect"


@pytest.mark.anyio
async def test_advisory_lock_not_called_on_sqlite():
    session = AsyncMock(spec=AsyncSession)
    session.bind = MagicMock()
    session.bind.dialect.name = "sqlite"
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=None)

    await record_system_action(
        session=session,
        org_id=uuid.uuid4(),
        action="test_action",
        resource_type="test",
        resource_id="123",
    )

    found_lock_call = False
    for call in session.execute.call_args_list:
        args, _ = call
        if args and isinstance(args[0], sa.sql.elements.TextClause) and "pg_advisory_xact_lock" in str(args[0]):
            found_lock_call = True
            break

    assert not found_lock_call, "pg_advisory_xact_lock should not be called on SQLite dialect"


@pytest.mark.anyio
async def test_advisory_lock_not_called_when_bind_missing():
    session = AsyncMock(spec=AsyncSession)
    session.bind = None
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=None)

    await record_system_action(
        session=session,
        org_id=uuid.uuid4(),
        action="test_action",
        resource_type="test",
        resource_id="123",
    )

    found_lock_call = False
    for call in session.execute.call_args_list:
        args, _ = call
        if args and isinstance(args[0], sa.sql.elements.TextClause) and "pg_advisory_xact_lock" in str(args[0]):
            found_lock_call = True
            break

    assert not found_lock_call, "pg_advisory_xact_lock should not be called when bind is missing"
