from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.audit_retention.db_models import AuditLegalHold, AuditLogScope, AuditPurgeEvent
from app.domain.config_audit.db_models import ConfigAuditLog
from app.domain.feature_flag_audit.db_models import FeatureFlagAuditLog
from app.domain.integration_audit.db_models import IntegrationAuditLog
from app.infra.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionPolicy:
    admin_days: int
    config_days: int


@dataclass(frozen=True)
class AuditTableConfig:
    name: str
    model: type
    timestamp_column: sa.Column
    scope: AuditLogScope
    retention_days: int


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _build_policy() -> RetentionPolicy:
    return RetentionPolicy(
        admin_days=settings.audit_retention_admin_days,
        config_days=settings.audit_retention_config_days,
    )


def _legal_hold_exists_stmt(
    model: type,
    *,
    timestamp_column: sa.Column,
    scope: AuditLogScope,
) -> sa.sql.Select:
    hold = aliased(AuditLegalHold)
    scope_filter = sa.or_(hold.audit_scope == scope.value, hold.audit_scope == AuditLogScope.ALL.value)
    org_filter = sa.or_(hold.org_id.is_(None), hold.org_id == model.org_id)
    start_filter = sa.or_(hold.applies_from.is_(None), timestamp_column >= hold.applies_from)
    end_filter = sa.or_(hold.applies_to.is_(None), timestamp_column <= hold.applies_to)
    active_filter = hold.released_at.is_(None)
    return sa.select(sa.literal(1)).where(scope_filter, org_filter, start_filter, end_filter, active_filter)


def _audit_tables(policy: RetentionPolicy) -> list[AuditTableConfig]:
    return [
        AuditTableConfig(
            name="admin_audit_logs",
            model=AdminAuditLog,
            timestamp_column=AdminAuditLog.created_at,
            scope=AuditLogScope.ADMIN,
            retention_days=policy.admin_days,
        ),
        AuditTableConfig(
            name="config_audit_logs",
            model=ConfigAuditLog,
            timestamp_column=ConfigAuditLog.occurred_at,
            scope=AuditLogScope.CONFIG,
            retention_days=policy.config_days,
        ),
        AuditTableConfig(
            name="feature_flag_audit_logs",
            model=FeatureFlagAuditLog,
            timestamp_column=FeatureFlagAuditLog.occurred_at,
            scope=AuditLogScope.FEATURE_FLAG,
            retention_days=policy.config_days,
        ),
        AuditTableConfig(
            name="integration_audit_logs",
            model=IntegrationAuditLog,
            timestamp_column=IntegrationAuditLog.occurred_at,
            scope=AuditLogScope.INTEGRATION,
            retention_days=policy.config_days,
        ),
    ]


async def create_legal_hold(
    session: AsyncSession,
    *,
    org_id,
    scope: AuditLogScope,
    applies_from: datetime | None,
    applies_to: datetime | None,
    investigation_id: str | None,
    reason: str | None,
    created_by: str | None,
) -> AuditLegalHold:
    hold = AuditLegalHold(
        org_id=org_id,
        audit_scope=scope.value,
        applies_from=applies_from,
        applies_to=applies_to,
        investigation_id=investigation_id,
        reason=reason,
        created_by=created_by,
        created_at=_utc_now(),
    )
    session.add(hold)
    await session.flush()
    return hold


async def _is_postgres(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bind is not None and bind.dialect.name == "postgresql"


async def _enable_purge_mode(session: AsyncSession) -> None:
    if not await _is_postgres(session):
        return
    await session.execute(sa.text("SET LOCAL app.audit_purge = 'on'"))


async def _count_on_hold(
    session: AsyncSession,
    table: AuditTableConfig,
    cutoff: datetime,
) -> int:
    hold_exists = sa.exists(_legal_hold_exists_stmt(table.model, timestamp_column=table.timestamp_column, scope=table.scope))
    stmt = sa.select(sa.func.count(table.model.audit_id)).where(table.timestamp_column <= cutoff, hold_exists)
    return int(await session.scalar(stmt) or 0)


async def _count_eligible(
    session: AsyncSession,
    table: AuditTableConfig,
    cutoff: datetime,
) -> int:
    hold_exists = sa.exists(_legal_hold_exists_stmt(table.model, timestamp_column=table.timestamp_column, scope=table.scope))
    stmt = sa.select(sa.func.count(table.model.audit_id)).where(table.timestamp_column <= cutoff, ~hold_exists)
    return int(await session.scalar(stmt) or 0)


async def _fetch_batch_ids(
    session: AsyncSession,
    table: AuditTableConfig,
    cutoff: datetime,
    batch_size: int,
) -> list[str]:
    hold_exists = sa.exists(_legal_hold_exists_stmt(table.model, timestamp_column=table.timestamp_column, scope=table.scope))
    stmt = (
        sa.select(table.model.audit_id)
        .where(table.timestamp_column <= cutoff, ~hold_exists)
        .order_by(table.timestamp_column.asc(), table.model.audit_id.asc())
        .limit(batch_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _purge_table(
    session: AsyncSession,
    table: AuditTableConfig,
    *,
    cutoff: datetime,
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int, int]:
    on_hold = await _count_on_hold(session, table, cutoff)
    eligible = await _count_eligible(session, table, cutoff)
    if dry_run or eligible == 0:
        return 0, on_hold, eligible

    purged = 0
    while True:
        batch_ids = await _fetch_batch_ids(session, table, cutoff, batch_size)
        if not batch_ids:
            break
        await _enable_purge_mode(session)
        await session.execute(sa.delete(table.model).where(table.model.audit_id.in_(batch_ids)))
        await session.commit()
        purged += len(batch_ids)
    return purged, on_hold, eligible


async def run_audit_retention(
    session: AsyncSession,
    *,
    dry_run: bool | None = None,
    batch_size: int | None = None,
) -> dict[str, int]:
    resolved_dry_run = settings.audit_retention_dry_run if dry_run is None else dry_run
    resolved_batch_size = batch_size or settings.audit_retention_batch_size
    policy = _build_policy()
    now = _utc_now()

    total_purged = 0
    total_on_hold = 0
    total_eligible = 0
    table_results: dict[str, dict[str, int]] = {}

    for table in _audit_tables(policy):
        cutoff = now - timedelta(days=table.retention_days)
        purged, on_hold, eligible = await _purge_table(
            session,
            table,
            cutoff=cutoff,
            batch_size=resolved_batch_size,
            dry_run=resolved_dry_run,
        )
        table_results[table.name] = {
            "purged": purged,
            "on_hold": on_hold,
            "eligible": eligible,
            "retention_days": table.retention_days,
        }
        total_purged += purged
        total_on_hold += on_hold
        total_eligible += eligible

    if total_purged:
        metrics.record_audit_purge(total_purged)
    if total_on_hold:
        metrics.record_audit_legal_hold(total_on_hold)

    purge_event = AuditPurgeEvent(
        actor_type="system",
        actor_id="audit-retention-job",
        dry_run=resolved_dry_run,
        policy_snapshot={
            "admin_retention_days": policy.admin_days,
            "config_retention_days": policy.config_days,
        },
        purge_summary={
            "tables": table_results,
            "total_purged": total_purged,
            "total_on_hold": total_on_hold,
            "total_eligible": total_eligible,
        },
        started_at=now,
        completed_at=_utc_now(),
    )
    session.add(purge_event)
    await session.commit()

    logger.info(
        "audit_retention_complete",
        extra={
            "extra": {
                "dry_run": resolved_dry_run,
                "purged": total_purged,
                "on_hold": total_on_hold,
                "eligible": total_eligible,
            }
        },
    )

    return {
        "purged": total_purged,
        "on_hold": total_on_hold,
        "eligible": total_eligible,
        "dry_run": int(resolved_dry_run),
    }
