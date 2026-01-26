from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_audit import service as admin_audit_service
from app.domain.analytics.db_models import EventLog
from app.domain.leads.db_models import Lead
from app.domain.reason_logs.db_models import ReasonLog
from app.infra.metrics import metrics
from app.settings import settings


class RetentionCategory(str, Enum):
    APPLICATION_LOGS = "application_logs"
    ANALYTICS_EVENTS = "analytics_events"
    SOFT_DELETED_ENTITIES = "soft_deleted_entities"
    AUDIT_LOGS = "audit_logs"


@dataclass(frozen=True)
class RetentionPolicy:
    category: RetentionCategory
    retention_days: int | None
    batch_size: int


@dataclass(frozen=True)
class RetentionResult:
    category: RetentionCategory
    retention_days: int | None
    deleted: int
    cutoff: datetime | None
    status: str


@dataclass(frozen=True)
class RetentionTarget:
    model: Any
    id_column: Any
    timestamp_column: Any
    filters: tuple[Any, ...] = ()


_RETENTION_TARGETS: dict[RetentionCategory, RetentionTarget] = {
    RetentionCategory.APPLICATION_LOGS: RetentionTarget(
        model=ReasonLog,
        id_column=ReasonLog.reason_id,
        timestamp_column=ReasonLog.created_at,
    ),
    RetentionCategory.ANALYTICS_EVENTS: RetentionTarget(
        model=EventLog,
        id_column=EventLog.event_id,
        timestamp_column=EventLog.occurred_at,
    ),
    RetentionCategory.SOFT_DELETED_ENTITIES: RetentionTarget(
        model=Lead,
        id_column=Lead.lead_id,
        timestamp_column=Lead.deleted_at,
        filters=(Lead.deleted_at.is_not(None),),
    ),
}


def _retention_policy(category: RetentionCategory) -> RetentionPolicy:
    retention_days: int | None
    if category == RetentionCategory.APPLICATION_LOGS:
        retention_days = settings.retention_application_log_days
    elif category == RetentionCategory.ANALYTICS_EVENTS:
        retention_days = settings.retention_analytics_event_days
    elif category == RetentionCategory.SOFT_DELETED_ENTITIES:
        retention_days = settings.retention_soft_deleted_days
    elif category == RetentionCategory.AUDIT_LOGS:
        retention_days = settings.retention_audit_log_days
    else:
        retention_days = None
    return RetentionPolicy(
        category=category,
        retention_days=retention_days,
        batch_size=settings.retention_batch_size,
    )


def retention_policies() -> list[RetentionPolicy]:
    return [_retention_policy(category) for category in RetentionCategory]


def _sanitize_deleted_count(deleted: int | None, fallback: int) -> int:
    if deleted is None or deleted < 0:
        return fallback
    return deleted


def _chunked(iterable: Iterable[Any], size: int) -> Iterable[list[Any]]:
    chunk: list[Any] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


async def _delete_in_batches(
    session: AsyncSession,
    target: RetentionTarget,
    *,
    cutoff: datetime,
    batch_size: int,
) -> int:
    total_deleted = 0
    while True:
        stmt = (
            sa.select(target.id_column)
            .where(target.timestamp_column <= cutoff, *target.filters)
            .order_by(target.timestamp_column.asc(), target.id_column.asc())
            .limit(batch_size)
        )
        result = await session.execute(stmt)
        batch_ids = list(result.scalars().all())
        if not batch_ids:
            break
        for batch in _chunked(batch_ids, batch_size):
            delete_stmt = sa.delete(target.model).where(target.id_column.in_(batch))
            delete_result = await session.execute(delete_stmt)
            total_deleted += _sanitize_deleted_count(delete_result.rowcount, len(batch))
    return total_deleted


async def enforce_retention(
    session: AsyncSession,
    *,
    category: RetentionCategory,
    now: datetime | None = None,
) -> RetentionResult:
    policy = _retention_policy(category)
    reference_time = now or datetime.now(timezone.utc)
    cutoff = (
        reference_time - timedelta(days=policy.retention_days)
        if policy.retention_days and policy.retention_days > 0
        else None
    )

    if policy.retention_days is None or policy.retention_days <= 0:
        async with session.begin():
            await admin_audit_service.record_system_action(
                session,
                org_id=settings.default_org_id,
                action="data_retention_skipped",
                resource_type=category.value,
                resource_id=None,
                context={
                    "category": category.value,
                    "retention_days": policy.retention_days,
                    "cutoff": cutoff.isoformat() if cutoff else None,
                    "deleted": 0,
                    "status": "disabled",
                },
            )
        return RetentionResult(
            category=category,
            retention_days=policy.retention_days,
            deleted=0,
            cutoff=cutoff,
            status="disabled",
        )

    if category == RetentionCategory.AUDIT_LOGS:
        async with session.begin():
            await admin_audit_service.record_system_action(
                session,
                org_id=settings.default_org_id,
                action="data_retention_policy_reference",
                resource_type="audit_logs",
                resource_id=None,
                context={
                    "category": category.value,
                    "retention_days": policy.retention_days,
                    "cutoff": cutoff.isoformat() if cutoff else None,
                    "deleted": 0,
                    "status": "reference_only",
                },
            )
        return RetentionResult(
            category=category,
            retention_days=policy.retention_days,
            deleted=0,
            cutoff=cutoff,
            status="reference_only",
        )

    target = _RETENTION_TARGETS.get(category)
    if target is None:
        return RetentionResult(
            category=category,
            retention_days=policy.retention_days,
            deleted=0,
            cutoff=cutoff,
            status="unsupported",
        )

    async with session.begin():
        deleted = await _delete_in_batches(
            session,
            target,
            cutoff=cutoff,
            batch_size=policy.batch_size,
        )
        await admin_audit_service.record_system_action(
            session,
            org_id=settings.default_org_id,
            action="data_retention_enforced",
            resource_type=category.value,
            resource_id=None,
            context={
                "category": category.value,
                "retention_days": policy.retention_days,
                "cutoff": cutoff.isoformat(),
                "deleted": deleted,
                "batch_size": policy.batch_size,
                "status": "success",
            },
        )

    metrics.record_retention_deletion(category.value, deleted)

    return RetentionResult(
        category=category,
        retention_days=policy.retention_days,
        deleted=deleted,
        cutoff=cutoff,
        status="success",
    )
