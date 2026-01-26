from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_audit import service as admin_audit_service
from app.domain.reason_logs.db_models import ReasonLog
from app.infra.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LogScopeDefinition:
    includes: tuple[str, ...]
    excludes: tuple[str, ...]


APPLICATION_LOG_SCOPE = LogScopeDefinition(
    includes=(
        "request logs",
        "error logs",
        "operational logs",
    ),
    excludes=(
        "audit logs",
        "security logs requiring extended retention",
    ),
)


@dataclass(frozen=True)
class LogRetentionResult:
    retention_days: int | None
    deleted: int
    cutoff: datetime | None
    status: str
    batch_size: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_deleted_count(deleted: int | None, fallback: int) -> int:
    if deleted is None or deleted < 0:
        return fallback
    return deleted


async def _fetch_batch_ids(
    session: AsyncSession,
    cutoff: datetime,
    batch_size: int,
) -> list[str]:
    stmt = (
        sa.select(ReasonLog.reason_id)
        .where(ReasonLog.created_at <= cutoff)
        .order_by(ReasonLog.created_at.asc(), ReasonLog.reason_id.asc())
        .limit(batch_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _delete_batch(
    session: AsyncSession,
    batch_ids: list[str],
    *,
    max_attempts: int,
    retry_delay_seconds: float,
) -> int:
    attempt = 0
    while True:
        attempt += 1
        try:
            delete_stmt = sa.delete(ReasonLog).where(ReasonLog.reason_id.in_(batch_ids))
            delete_result = await session.execute(delete_stmt)
            await session.commit()
            return _sanitize_deleted_count(delete_result.rowcount, len(batch_ids))
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            if attempt >= max_attempts:
                logger.warning(
                    "log_retention_batch_failed",
                    extra={
                        "extra": {
                            "attempt": attempt,
                            "batch_size": len(batch_ids),
                            "error": type(exc).__name__,
                        }
                    },
                )
                raise
            delay = retry_delay_seconds * (2 ** (attempt - 1))
            logger.info(
                "log_retention_batch_retry",
                extra={
                    "extra": {
                        "attempt": attempt,
                        "batch_size": len(batch_ids),
                        "delay_seconds": delay,
                    }
                },
            )
            await asyncio.sleep(delay)


async def purge_application_logs(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    retention_days: int | None = None,
    batch_size: int | None = None,
    max_retries: int | None = None,
    retry_delay_seconds: float | None = None,
) -> LogRetentionResult:
    resolved_retention_days = (
        settings.retention_application_log_days
        if retention_days is None
        else retention_days
    )
    resolved_batch_size = batch_size or settings.retention_batch_size
    resolved_max_retries = max_retries or settings.log_retention_batch_retries
    resolved_retry_delay = (
        retry_delay_seconds
        if retry_delay_seconds is not None
        else settings.log_retention_batch_retry_delay_seconds
    )
    reference_time = now or _utc_now()
    cutoff = (
        reference_time - timedelta(days=resolved_retention_days)
        if resolved_retention_days and resolved_retention_days > 0
        else None
    )

    if resolved_retention_days is None or resolved_retention_days <= 0:
        async with session.begin():
            await admin_audit_service.record_system_action(
                session,
                org_id=settings.default_org_id,
                action="log_retention_skipped",
                resource_type="logs",
                resource_id=None,
                context={
                    "category": "logs",
                    "count": 0,
                    "retention_days": resolved_retention_days,
                    "cutoff": cutoff.isoformat() if cutoff else None,
                    "batch_size": resolved_batch_size,
                    "status": "disabled",
                    "scope": {
                        "includes": APPLICATION_LOG_SCOPE.includes,
                        "excludes": APPLICATION_LOG_SCOPE.excludes,
                    },
                },
            )
        return LogRetentionResult(
            retention_days=resolved_retention_days,
            deleted=0,
            cutoff=cutoff,
            status="disabled",
            batch_size=resolved_batch_size,
        )

    total_deleted = 0
    while True:
        batch_ids = await _fetch_batch_ids(session, cutoff, resolved_batch_size)
        if not batch_ids:
            break
        total_deleted += await _delete_batch(
            session,
            batch_ids,
            max_attempts=resolved_max_retries,
            retry_delay_seconds=resolved_retry_delay,
        )

    async with session.begin():
        await admin_audit_service.record_system_action(
            session,
            org_id=settings.default_org_id,
            action="log_retention_purge",
            resource_type="logs",
            resource_id=None,
            context={
                "category": "logs",
                "count": total_deleted,
                "deleted": total_deleted,
                "retention_days": resolved_retention_days,
                "cutoff": cutoff.isoformat(),
                "batch_size": resolved_batch_size,
                "status": "success",
                "scope": {
                    "includes": APPLICATION_LOG_SCOPE.includes,
                    "excludes": APPLICATION_LOG_SCOPE.excludes,
                },
            },
        )

    metrics.record_logs_purged(total_deleted)

    return LogRetentionResult(
        retention_days=resolved_retention_days,
        deleted=total_deleted,
        cutoff=cutoff,
        status="success",
        batch_size=resolved_batch_size,
    )
