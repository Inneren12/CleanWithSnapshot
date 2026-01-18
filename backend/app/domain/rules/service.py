from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.rules import actions as rules_actions
from app.domain.rules import engine as rules_engine
from app.domain.rules.db_models import Rule, RuleRun
from app.infra.communication import NoopCommunicationAdapter, TwilioCommunicationAdapter
from app.infra.email import EmailAdapter, NoopEmailAdapter

EmailAdapterLike = EmailAdapter | NoopEmailAdapter
CommunicationAdapterLike = TwilioCommunicationAdapter | NoopCommunicationAdapter


def _normalize_conditions(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    return value


def _normalize_actions(value: list[Any] | None) -> list[Any]:
    if value is None:
        return []
    return value


def _resolve_trigger(trigger_type: str | None, payload: dict[str, Any]) -> str | None:
    if trigger_type:
        return trigger_type
    payload_trigger = payload.get("trigger_type")
    if isinstance(payload_trigger, str) and payload_trigger:
        return payload_trigger
    return None


def _evaluate_rule(*, rule: Rule, payload: dict[str, Any], trigger_type: str | None) -> bool:
    if not rule.enabled:
        return False
    resolved_trigger = _resolve_trigger(trigger_type, payload)
    if resolved_trigger and rule.trigger_type != resolved_trigger:
        return False
    return rules_engine.evaluate_conditions(payload, rule.conditions_json or {})


async def list_rules(session: AsyncSession, org_id: uuid.UUID) -> list[Rule]:
    stmt = sa.select(Rule).where(Rule.org_id == org_id).order_by(Rule.created_at.desc())
    return list(await session.scalars(stmt))


async def get_rule(session: AsyncSession, org_id: uuid.UUID, rule_id: uuid.UUID) -> Rule | None:
    stmt = sa.select(Rule).where(Rule.org_id == org_id, Rule.rule_id == rule_id)
    return await session.scalar(stmt)


async def create_rule(session: AsyncSession, org_id: uuid.UUID, data: dict[str, Any]) -> Rule:
    rule = Rule(
        rule_id=uuid.uuid4(),
        org_id=org_id,
        name=data["name"],
        enabled=data.get("enabled", False),
        dry_run=data.get("dry_run", True),
        trigger_type=data["trigger_type"],
        conditions_json=_normalize_conditions(data.get("conditions_json")),
        actions_json=_normalize_actions(data.get("actions_json")),
        escalation_policy_json=data.get("escalation_policy") or {},
        escalation_cooldown_minutes=data.get("escalation_cooldown_minutes", 60),
    )
    session.add(rule)
    await session.flush()
    return rule


async def update_rule(session: AsyncSession, rule: Rule, data: dict[str, Any]) -> Rule:
    if "name" in data:
        rule.name = data["name"]
    if "enabled" in data:
        rule.enabled = bool(data["enabled"])
    if "dry_run" in data:
        rule.dry_run = bool(data["dry_run"])
    if "trigger_type" in data:
        rule.trigger_type = data["trigger_type"]
    if "conditions_json" in data:
        rule.conditions_json = _normalize_conditions(data.get("conditions_json"))
    if "actions_json" in data:
        rule.actions_json = _normalize_actions(data.get("actions_json"))
    if "escalation_policy" in data:
        rule.escalation_policy_json = data.get("escalation_policy") or {}
    if "escalation_cooldown_minutes" in data:
        rule.escalation_cooldown_minutes = data.get("escalation_cooldown_minutes") or 0
    await session.flush()
    return rule


async def delete_rule(session: AsyncSession, rule: Rule) -> None:
    await session.delete(rule)


async def list_rule_runs(
    session: AsyncSession, org_id: uuid.UUID, rule_id: uuid.UUID
) -> list[RuleRun]:
    stmt = (
        sa.select(RuleRun)
        .where(RuleRun.org_id == org_id, RuleRun.rule_id == rule_id)
        .order_by(RuleRun.occurred_at.desc())
    )
    return list(await session.scalars(stmt))


async def list_enabled_rules(
    session: AsyncSession, org_id: uuid.UUID, trigger_type: str
) -> list[Rule]:
    stmt = (
        sa.select(Rule)
        .where(
            Rule.org_id == org_id,
            Rule.enabled.is_(True),
            Rule.trigger_type == trigger_type,
        )
        .order_by(Rule.created_at.desc())
    )
    return list(await session.scalars(stmt))


async def get_existing_run(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    idempotency_key: str,
) -> RuleRun | None:
    stmt = sa.select(RuleRun).where(
        RuleRun.org_id == org_id,
        RuleRun.rule_id == rule_id,
        RuleRun.idempotency_key == idempotency_key,
    )
    return await session.scalar(stmt)


async def evaluate_rules_for_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    trigger_type: str,
    payload: dict[str, Any],
    occurred_at: datetime | None,
    entity_type: str | None,
    entity_id: str | None,
    idempotency_key: str | None,
    execute_actions: bool = False,
    email_adapter: EmailAdapterLike | None = None,
    communication_adapter: CommunicationAdapterLike | None = None,
) -> list[RuleRun]:
    rules = await list_enabled_rules(session, org_id, trigger_type)
    runs: list[RuleRun] = []
    for rule in rules:
        if idempotency_key:
            existing = await get_existing_run(
                session,
                org_id=org_id,
                rule_id=rule.rule_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                runs.append(existing)
                continue
        run = await evaluate_rule(
            session,
            org_id=org_id,
            rule=rule,
            payload=payload,
            trigger_type=trigger_type,
            occurred_at=occurred_at,
            entity_type=entity_type,
            entity_id=entity_id,
            idempotency_key=idempotency_key,
            execute_actions=execute_actions,
            email_adapter=email_adapter,
            communication_adapter=communication_adapter,
        )
        runs.append(run)
    return runs


async def evaluate_rule(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    rule: Rule,
    payload: dict[str, Any],
    trigger_type: str | None,
    occurred_at: datetime | None,
    entity_type: str | None,
    entity_id: str | None,
    idempotency_key: str | None,
    execute_actions: bool = False,
    email_adapter: EmailAdapterLike | None = None,
    communication_adapter: CommunicationAdapterLike | None = None,
) -> RuleRun:
    matched = _evaluate_rule(rule=rule, payload=payload, trigger_type=trigger_type)
    intended_actions = list(rule.actions_json or []) if matched else []
    actions = [] if rule.dry_run or not matched else list(rule.actions_json or [])
    run = RuleRun(
        run_id=uuid.uuid4(),
        org_id=org_id,
        rule_id=rule.rule_id,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        entity_type=entity_type,
        entity_id=entity_id,
        matched=matched,
        actions_json=actions,
        idempotency_key=idempotency_key,
    )
    session.add(run)
    await session.flush()
    if execute_actions and matched and intended_actions:
        await rules_actions.execute_rule_actions(
            session,
            org_id=org_id,
            rule=rule,
            run=run,
            actions=intended_actions,
            payload=payload,
            dry_run=rule.dry_run,
            email_adapter=email_adapter,
            communication_adapter=communication_adapter,
        )
    return run
