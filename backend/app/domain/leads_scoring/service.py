from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.leads.db_models import Lead
from app.domain.leads_scoring import engine, schemas
from app.domain.leads_scoring.db_models import LeadScoreSnapshot, LeadScoringRule


async def list_rules(session: AsyncSession, org_id: uuid.UUID) -> list[LeadScoringRule]:
    result = await session.execute(
        sa.select(LeadScoringRule)
        .where(LeadScoringRule.org_id == org_id)
        .order_by(LeadScoringRule.version.desc())
    )
    return list(result.scalars().all())


async def get_active_rules(session: AsyncSession, org_id: uuid.UUID) -> LeadScoringRule | None:
    result = await session.execute(
        sa.select(LeadScoringRule)
        .where(LeadScoringRule.org_id == org_id, LeadScoringRule.enabled.is_(True))
        .order_by(LeadScoringRule.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_rules_version(
    session: AsyncSession,
    org_id: uuid.UUID,
    payload: schemas.LeadScoringRulesUpdateRequest,
) -> LeadScoringRule:
    version = await _next_version(session, org_id)
    if payload.enabled:
        await session.execute(
            sa.update(LeadScoringRule)
            .where(LeadScoringRule.org_id == org_id, LeadScoringRule.enabled.is_(True))
            .values(enabled=False)
        )

    model = LeadScoringRule(
        org_id=org_id,
        version=version,
        enabled=payload.enabled,
        rules_json=[rule.model_dump() for rule in payload.rules],
    )
    session.add(model)
    await session.flush()
    return model


async def get_lead(session: AsyncSession, org_id: uuid.UUID, lead_id: str) -> Lead | None:
    result = await session.execute(
        sa.select(Lead).where(Lead.org_id == org_id, Lead.lead_id == lead_id)
    )
    return result.scalar_one_or_none()


async def get_snapshot(
    session: AsyncSession,
    org_id: uuid.UUID,
    lead_id: str,
) -> LeadScoreSnapshot | None:
    result = await session.execute(
        sa.select(LeadScoreSnapshot).where(
            LeadScoreSnapshot.org_id == org_id,
            LeadScoreSnapshot.lead_id == lead_id,
        )
    )
    return result.scalar_one_or_none()


async def recompute_score(
    session: AsyncSession,
    org_id: uuid.UUID,
    lead: Lead,
    rules: LeadScoringRule,
) -> LeadScoreSnapshot:
    rule_definitions = [
        schemas.LeadScoringRuleDefinition.model_validate(rule)
        for rule in (rules.rules_json or [])
    ]
    result = engine.score_lead(lead, rule_definitions)
    now = datetime.now(tz=timezone.utc)
    reasons_payload = [
        {
            "rule_key": reason.rule_key,
            "label": reason.label,
            "points": reason.points,
        }
        for reason in result.reasons
    ]

    snapshot = await get_snapshot(session, org_id, lead.lead_id)
    if snapshot is None:
        snapshot = LeadScoreSnapshot(
            org_id=org_id,
            lead_id=lead.lead_id,
            score=result.score,
            reasons_json=reasons_payload,
            computed_at=now,
            rules_version=rules.version,
        )
        session.add(snapshot)
    else:
        snapshot.score = result.score
        snapshot.reasons_json = reasons_payload
        snapshot.computed_at = now
        snapshot.rules_version = rules.version
        await session.flush()
    return snapshot


async def _next_version(session: AsyncSession, org_id: uuid.UUID) -> int:
    result = await session.execute(
        sa.select(sa.func.max(LeadScoringRule.version)).where(LeadScoringRule.org_id == org_id)
    )
    max_version = result.scalar_one_or_none()
    return (max_version or 0) + 1
