"""Tests for JobRepository — persistent job orchestration.

Uses SQLite in-memory for unit tests. PostgreSQL integration tests
for SKIP LOCKED semantics are marked @pytest.mark.integration.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs.db_models import Job, JobStatus
from app.domain.jobs.repository import JobRepository
from app.domain.jobs.schemas import (
    CatalogSyncPayload,
    CubeFetchPayload,
    parse_payload,
    UnknownJobTypeError,
    IncompatiblePayloadError,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ---- Enqueue + Claim cycle ----

async def test_enqueue_creates_job(db_session: AsyncSession) -> None:
    """Enqueue creates a job in QUEUED status."""
    repo = JobRepository(db_session)
    payload = CatalogSyncPayload()
    job = await repo.enqueue(
        "catalog_sync",
        payload.model_dump_json(),
    )
    await db_session.commit()

    assert job.id is not None
    assert job.status == JobStatus.QUEUED
    assert job.attempt_count == 0
    assert job.job_type == "catalog_sync"


async def test_claim_next_returns_job_and_marks_running(
    db_session: AsyncSession,
) -> None:
    """claim_next returns oldest queued job and sets status to RUNNING."""
    repo = JobRepository(db_session)
    payload = CatalogSyncPayload()
    await repo.enqueue("catalog_sync", payload.model_dump_json())
    await db_session.commit()

    claimed = await repo.claim_next()
    assert claimed is not None
    assert claimed.status == JobStatus.RUNNING
    assert claimed.started_at is not None
    assert claimed.attempt_count == 1


async def test_claim_next_returns_none_when_empty(
    db_session: AsyncSession,
) -> None:
    """claim_next returns None when no queued jobs exist."""
    repo = JobRepository(db_session)
    result = await repo.claim_next()
    assert result is None


# ---- Dedupe ----

async def test_dedupe_key_prevents_duplicate(
    db_session: AsyncSession,
) -> None:
    """Enqueue with same dedupe_key returns existing job."""
    repo = JobRepository(db_session)
    payload = CatalogSyncPayload()
    json_str = payload.model_dump_json()

    job1 = await repo.enqueue(
        "catalog_sync", json_str, dedupe_key="sync:2025-04-04"
    )
    await db_session.commit()

    job2 = await repo.enqueue(
        "catalog_sync", json_str, dedupe_key="sync:2025-04-04"
    )
    assert job2.id == job1.id  # same job returned


async def test_dedupe_allows_after_completion(
    db_session: AsyncSession,
) -> None:
    """Completed job with same dedupe_key allows new enqueue."""
    repo = JobRepository(db_session)
    payload = CatalogSyncPayload()
    json_str = payload.model_dump_json()

    job1 = await repo.enqueue(
        "catalog_sync", json_str, dedupe_key="sync:2025-04-04"
    )
    await repo.mark_success(job1.id)
    await db_session.commit()

    job2 = await repo.enqueue(
        "catalog_sync", json_str, dedupe_key="sync:2025-04-04"
    )
    await db_session.commit()

    assert job2.id != job1.id  # new job created


# ---- Status transitions ----

async def test_mark_success_persists_result(
    db_session: AsyncSession,
) -> None:
    """mark_success sets status=SUCCESS and saves result."""
    repo = JobRepository(db_session)
    job = await repo.enqueue(
        "catalog_sync", CatalogSyncPayload().model_dump_json()
    )
    await db_session.commit()

    await repo.mark_success(job.id, result_json='{"total": 7000}')
    await db_session.commit()

    fetched = await repo.get_job(job.id)
    assert fetched is not None
    assert fetched.status == JobStatus.SUCCESS
    assert fetched.result_json == '{"total": 7000}'
    assert fetched.finished_at is not None


async def test_mark_failed_persists_error(
    db_session: AsyncSession,
) -> None:
    """mark_failed sets status=FAILED with error details."""
    repo = JobRepository(db_session)
    job = await repo.enqueue(
        "cube_fetch",
        CubeFetchPayload(product_id="14-10-0127").model_dump_json(),
    )
    await db_session.commit()

    await repo.mark_failed(
        job.id,
        error_code="DATA_CONTRACT_VIOLATION",
        error_message="Missing column: SCALAR_ID",
    )
    await db_session.commit()

    fetched = await repo.get_job(job.id)
    assert fetched is not None
    assert fetched.status == JobStatus.FAILED
    assert fetched.error_code == "DATA_CONTRACT_VIOLATION"


# ---- Payload parsing ----

async def test_parse_payload_valid(db_session: AsyncSession) -> None:
    """parse_payload returns typed model for known job_type."""
    payload = CubeFetchPayload(product_id="14-10-0127")
    parsed = parse_payload("cube_fetch", payload.model_dump_json())
    assert isinstance(parsed, CubeFetchPayload)
    assert parsed.product_id == "14-10-0127"


async def test_parse_payload_unknown_type(db_session: AsyncSession) -> None:
    """parse_payload raises UnknownJobTypeError for unregistered type."""
    with pytest.raises(UnknownJobTypeError):
        parse_payload("nonexistent_type", '{"schema_version": 1}')


async def test_parse_payload_incompatible_version(
    db_session: AsyncSession,
) -> None:
    """parse_payload raises IncompatiblePayloadError for wrong version."""
    with pytest.raises(IncompatiblePayloadError):
        parse_payload(
            "catalog_sync",
            '{"schema_version": 999}',
        )


# ---- Zombie reaper ----

async def test_requeue_stale_running_jobs(
    db_session: AsyncSession,
) -> None:
    """Stale running jobs are requeued; fresh running jobs are untouched."""
    from datetime import timedelta

    repo = JobRepository(db_session)

    # Create a "stale" running job (started 20 min ago)
    stale_job = await repo.enqueue(
        "catalog_sync", CatalogSyncPayload().model_dump_json()
    )
    stale_job.status = JobStatus.RUNNING
    stale_job.started_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    stale_job.attempt_count = 1
    await db_session.flush()

    # Create a "fresh" running job (started 2 min ago)
    fresh_job = await repo.enqueue(
        "cube_fetch",
        CubeFetchPayload(product_id="test").model_dump_json(),
        dedupe_key="fresh-test",
    )
    fresh_job.status = JobStatus.RUNNING
    fresh_job.started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    fresh_job.attempt_count = 1
    await db_session.flush()
    await db_session.commit()

    # Run reaper with 10-minute threshold
    requeued_count = await repo.requeue_stale_running(
        stale_threshold_minutes=10
    )
    await db_session.commit()

    # Stale job requeued
    await db_session.refresh(stale_job)
    assert stale_job.status == JobStatus.QUEUED

    # Fresh job untouched
    await db_session.refresh(fresh_job)
    assert fresh_job.status == JobStatus.RUNNING

    assert requeued_count == 1


# ---- List / filter ----

async def test_list_jobs_with_filters(
    db_session: AsyncSession,
) -> None:
    """list_jobs filters by type and status correctly."""
    repo = JobRepository(db_session)
    await repo.enqueue(
        "catalog_sync", CatalogSyncPayload().model_dump_json(), dedupe_key="1"
    )
    await repo.enqueue(
        "cube_fetch",
        CubeFetchPayload(product_id="x").model_dump_json(), dedupe_key="2"
    )
    await db_session.commit()

    all_jobs = await repo.list_jobs()
    assert len(all_jobs) == 2

    syncs = await repo.list_jobs(job_type="catalog_sync")
    assert len(syncs) == 1

    running = await repo.list_jobs(status=JobStatus.RUNNING)
    assert len(running) == 0
