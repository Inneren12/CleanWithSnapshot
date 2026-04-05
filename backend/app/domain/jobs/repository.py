from __future__ import annotations
from datetime import datetime, timezone
from typing import Sequence
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.jobs.db_models import Job, JobStatus

class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, job_type: str, payload_json: str, *, dedupe_key: str | None = None, created_by: str | None = None, max_attempts: int = 3) -> Job:
        if dedupe_key is not None:
            existing = await self._find_active_by_dedupe(dedupe_key)
            if existing is not None:
                return existing

        job = Job(job_type=job_type, payload_json=payload_json, dedupe_key=dedupe_key, created_by=created_by, max_attempts=max_attempts)
        self._session.add(job)
        await self._session.flush()
        await self._session.refresh(job)
        return job

    async def claim_next(self, job_type: str | None = None) -> Job | None:
        stmt = select(Job).where(Job.status == JobStatus.QUEUED).order_by(Job.created_at.asc()).limit(1)
        if job_type is not None:
            stmt = stmt.where(Job.job_type == job_type)

        dialect = self._session.bind.dialect.name if self._session.bind else ""
        if dialect == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        result = await self._session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is not None:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            job.attempt_count += 1
            await self._session.flush()

        return job

    async def mark_success(self, job_id: int, result_json: str | None = None) -> None:
        await self._session.execute(update(Job).where(Job.id == job_id).values(status=JobStatus.SUCCESS, result_json=result_json, finished_at=datetime.now(timezone.utc)))

    async def mark_failed(self, job_id: int, error_code: str, error_message: str) -> None:
        await self._session.execute(update(Job).where(Job.id == job_id).values(status=JobStatus.FAILED, error_code=error_code, error_message=error_message, finished_at=datetime.now(timezone.utc)))

    async def list_jobs(self, job_type: str | None = None, status: JobStatus | None = None, limit: int = 50) -> Sequence[Job]:
        stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
        if job_type is not None:
            stmt = stmt.where(Job.job_type == job_type)
        if status is not None:
            stmt = stmt.where(Job.status == status)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_job(self, job_id: int) -> Job | None:
        return await self._session.get(Job, job_id)

    async def requeue_stale_running(self, stale_threshold_minutes: int = 10) -> int:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_threshold_minutes)
        result = await self._session.execute(update(Job).where(Job.status == JobStatus.RUNNING, Job.started_at < cutoff, Job.attempt_count < Job.max_attempts).values(status=JobStatus.QUEUED))
        return result.rowcount

    async def _find_active_by_dedupe(self, dedupe_key: str) -> Job | None:
        stmt = select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
