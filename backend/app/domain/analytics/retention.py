from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_audit import service as admin_audit_service
from app.domain.analytics.db_models import EventLog
from app.infra.metrics import metrics
from app.settings import settings


@dataclass(frozen=True)
class AnalyticsDataClassification:
    raw_events: tuple[str, ...]
    aggregated_metrics: tuple[str, ...]
    description: str


ANALYTICS_CLASSIFICATION = AnalyticsDataClassification(
    raw_events=("event_logs",),
    aggregated_metrics=(
        "conversion_funnel_counts",
        "geo_heatmap_counts",
        "marketing_lead_source_rollups",
        "nps_distributions",
        "competitor_benchmarks",
    ),
    description="Raw analytics events are user-level, timestamped logs. Aggregated metrics are de-identified rollups.",
)


@dataclass(frozen=True)
class AnalyticsRetentionResult:
    deleted: int
    retention_days: int | None
    cutoff: datetime | None
    status: str


def _sanitize_deleted_count(deleted: int | None, fallback: int) -> int:
    if deleted is None or deleted < 0:
        return fallback
    return deleted


def _transaction(session: AsyncSession):
    return session.begin_nested() if session.in_transaction() else session.begin()


async def _delete_event_batch(
    session: AsyncSession,
    *,
    cutoff: datetime,
    batch_size: int,
) -> int:
    stmt = (
        sa.select(EventLog.event_id)
        .where(EventLog.occurred_at <= cutoff)
        .order_by(EventLog.occurred_at.asc(), EventLog.event_id.asc())
        .limit(batch_size)
    )
    result = await session.execute(stmt)
    batch_ids = list(result.scalars().all())
    if not batch_ids:
        return 0
    delete_stmt = sa.delete(EventLog).where(EventLog.event_id.in_(batch_ids))
    delete_result = await session.execute(delete_stmt)
    return _sanitize_deleted_count(delete_result.rowcount, len(batch_ids))


async def purge_raw_events(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int | None = None,
) -> AnalyticsRetentionResult:
    retention_days = settings.retention_analytics_event_days
    effective_batch_size = batch_size or settings.retention_batch_size
    reference_time = now or datetime.now(timezone.utc)
    cutoff = (
        reference_time - timedelta(days=retention_days)
        if retention_days and retention_days > 0
        else None
    )

    if retention_days is None or retention_days <= 0:
        async with _transaction(session):
            await admin_audit_service.record_system_action(
                session,
                org_id=settings.default_org_id,
                action="analytics_retention_skipped",
                resource_type="analytics",
                resource_id=None,
                context={
                    "category": "analytics",
                    "classification": {
                        "raw_events": ANALYTICS_CLASSIFICATION.raw_events,
                        "aggregated_metrics": ANALYTICS_CLASSIFICATION.aggregated_metrics,
                    },
                    "retention_days": retention_days,
                    "cutoff": cutoff.isoformat() if cutoff else None,
                    "deleted": 0,
                    "batch_size": effective_batch_size,
                    "status": "disabled",
                },
            )
        return AnalyticsRetentionResult(
            deleted=0,
            retention_days=retention_days,
            cutoff=cutoff,
            status="disabled",
        )

    total_deleted = 0
    async with _transaction(session):
        while True:
            deleted = await _delete_event_batch(
                session,
                cutoff=cutoff,
                batch_size=effective_batch_size,
            )
            if deleted == 0:
                break
            total_deleted += deleted

        await admin_audit_service.record_system_action(
            session,
            org_id=settings.default_org_id,
            action="analytics_retention_enforced",
            resource_type="analytics",
            resource_id=None,
            context={
                "category": "analytics",
                "classification": {
                    "raw_events": ANALYTICS_CLASSIFICATION.raw_events,
                    "aggregated_metrics": ANALYTICS_CLASSIFICATION.aggregated_metrics,
                },
                "retention_days": retention_days,
                "cutoff": cutoff.isoformat(),
                "deleted": total_deleted,
                "batch_size": effective_batch_size,
                "status": "success",
            },
        )

    metrics.record_analytics_events_purged(total_deleted)

    return AnalyticsRetentionResult(
        deleted=total_deleted,
        retention_days=retention_days,
        cutoff=cutoff,
        status="success",
    )
