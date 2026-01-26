from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_audit import service as admin_audit_service
from app.domain.leads.db_models import (
    Lead,
    LeadQuote,
    LeadQuoteFollowUp,
    LeadTouchpoint,
    ReferralCredit,
)
from app.infra.metrics import metrics
from app.settings import settings


@dataclass(frozen=True)
class SoftDeletePurgePolicy:
    entity_type: str
    grace_period_days: int | None
    batch_size: int
    cascade_order: tuple[str, ...]
    exclusions: tuple[str, ...]


@dataclass(frozen=True)
class SoftDeletePurgeResult:
    entity_type: str
    grace_period_days: int | None
    cutoff: datetime | None
    deleted: int
    held: int
    status: str


def soft_delete_purge_policies() -> list[SoftDeletePurgePolicy]:
    """Inventory of soft-deleted entity types and their purge policy."""
    return [
        SoftDeletePurgePolicy(
            entity_type="lead",
            grace_period_days=settings.retention_soft_deleted_days,
            batch_size=settings.soft_delete_purge_batch_size,
            cascade_order=(
                "lead_quote_followups",
                "lead_quotes",
                "referral_credits",
                "lead_touchpoints",
                "leads",
            ),
            exclusions=(
                "audit_logs",
                "payments",
                "invoices",
                "bookings",
                "policy_override_audits",
            ),
        )
    ]


def _sanitize_deleted_count(deleted: int | None, fallback: int) -> int:
    if deleted is None or deleted < 0:
        return fallback
    return deleted


async def _fetch_lead_batch_ids(
    session: AsyncSession,
    *,
    cutoff: datetime,
    batch_size: int,
) -> list[str]:
    stmt = (
        sa.select(Lead.lead_id)
        .where(
            Lead.deleted_at.is_not(None),
            Lead.deleted_at <= cutoff,
            Lead.legal_hold.is_(False),
        )
        .order_by(Lead.deleted_at.asc(), Lead.lead_id.asc())
        .limit(batch_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _purge_lead_batch(
    session: AsyncSession,
    lead_ids: Iterable[str],
) -> int:
    lead_ids = list(lead_ids)
    if not lead_ids:
        return 0

    quote_ids_result = await session.execute(
        sa.select(LeadQuote.quote_id).where(LeadQuote.lead_id.in_(lead_ids))
    )
    quote_ids = list(quote_ids_result.scalars().all())

    if quote_ids:
        await session.execute(
            sa.delete(LeadQuoteFollowUp).where(LeadQuoteFollowUp.quote_id.in_(quote_ids))
        )
        await session.execute(sa.delete(LeadQuote).where(LeadQuote.quote_id.in_(quote_ids)))

    await session.execute(
        sa.delete(ReferralCredit).where(
            sa.or_(
                ReferralCredit.referrer_lead_id.in_(lead_ids),
                ReferralCredit.referred_lead_id.in_(lead_ids),
            )
        )
    )
    await session.execute(sa.delete(LeadTouchpoint).where(LeadTouchpoint.lead_id.in_(lead_ids)))
    delete_result = await session.execute(sa.delete(Lead).where(Lead.lead_id.in_(lead_ids)))
    return _sanitize_deleted_count(delete_result.rowcount, len(lead_ids))


async def _purge_leads(
    session: AsyncSession,
    *,
    policy: SoftDeletePurgePolicy,
    now: datetime,
) -> SoftDeletePurgeResult:
    if policy.grace_period_days is None or policy.grace_period_days <= 0:
        return SoftDeletePurgeResult(
            entity_type=policy.entity_type,
            grace_period_days=policy.grace_period_days,
            cutoff=None,
            deleted=0,
            held=0,
            status="disabled",
        )

    cutoff = now - timedelta(days=policy.grace_period_days)
    held_stmt = sa.select(sa.func.count(Lead.lead_id)).where(
        Lead.deleted_at.is_not(None),
        Lead.deleted_at <= cutoff,
        Lead.legal_hold.is_(True),
    )
    async with session.begin():
        held = await session.scalar(held_stmt)
    total_deleted = 0

    while True:
        async with session.begin():
            batch_ids = await _fetch_lead_batch_ids(
                session,
                cutoff=cutoff,
                batch_size=policy.batch_size,
            )
            if not batch_ids:
                break
            total_deleted += await _purge_lead_batch(session, batch_ids)

    return SoftDeletePurgeResult(
        entity_type=policy.entity_type,
        grace_period_days=policy.grace_period_days,
        cutoff=cutoff,
        deleted=total_deleted,
        held=int(held or 0),
        status="success",
    )


async def run_soft_delete_purge(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[SoftDeletePurgeResult]:
    reference_time = now or datetime.now(tz=timezone.utc)
    results: list[SoftDeletePurgeResult] = []
    for policy in soft_delete_purge_policies():
        if policy.entity_type == "lead":
            result = await _purge_leads(session, policy=policy, now=reference_time)
        else:
            result = SoftDeletePurgeResult(
                entity_type=policy.entity_type,
                grace_period_days=policy.grace_period_days,
                cutoff=None,
                deleted=0,
                held=0,
                status="unsupported",
            )

        async with session.begin():
            await admin_audit_service.record_system_action(
                session,
                org_id=settings.default_org_id,
                action="soft_delete_purge",
                resource_type=policy.entity_type,
                resource_id=None,
                context={
                    "category": "soft_delete_purge",
                    "entity_type": policy.entity_type,
                    "deleted": result.deleted,
                    "held": result.held,
                    "grace_period_days": policy.grace_period_days,
                    "cutoff": result.cutoff.isoformat() if result.cutoff else None,
                    "batch_size": policy.batch_size,
                    "cascade_order": policy.cascade_order,
                    "exclusions": policy.exclusions,
                    "status": result.status,
                },
            )

        metrics.record_soft_delete_purge(result.entity_type, result.deleted)
        results.append(result)
    return results
