import asyncio

import sqlalchemy as sa

from app.domain.rules import engine as rules_engine
from app.domain.rules import service as rules_service
from app.domain.rules.db_models import RuleRun
from app.settings import settings


def test_rules_engine_deterministic_conditions():
    payload = {
        "status": "open",
        "severity": 5,
        "summary": "low inventory warning",
        "tags": ["inventory", "ops"],
        "nested": {"score": 9},
    }

    conditions = {
        "all": [
            {"field": "status", "op": "equals", "value": "open"},
            {"field": "summary", "op": "contains", "value": "inventory"},
            {"field": "severity", "op": ">=", "value": 5},
            {"field": "status", "op": "in", "value": ["open", "closed"]},
            {"field": "nested.score", "op": "gt", "value": 8},
        ]
    }

    assert rules_engine.evaluate_conditions(payload, conditions) is True

    any_conditions = {
        "any": [
            {"field": "severity", "op": "<", "value": 3},
            {"field": "status", "op": "equals", "value": "open"},
        ]
    }
    assert rules_engine.evaluate_conditions(payload, any_conditions) is True

    not_conditions = {"not": {"field": "status", "op": "equals", "value": "closed"}}
    assert rules_engine.evaluate_conditions(payload, not_conditions) is True

    legacy_conditions = {"status": "open", "severity": 5}
    assert rules_engine.evaluate_conditions(payload, legacy_conditions) is True


def test_rule_runs_idempotent(async_session_maker):
    async def _run() -> None:
        async with async_session_maker() as session:
            rule = await rules_service.create_rule(
                session,
                settings.default_org_id,
                {
                    "name": "Idempotent Rule",
                    "enabled": True,
                    "dry_run": True,
                    "trigger_type": "payment_failed",
                    "conditions_json": {"status": "failed"},
                    "actions_json": [{"type": "notify"}],
                },
            )
            await session.commit()

        async with async_session_maker() as session:
            runs_first = await rules_service.evaluate_rules_for_trigger(
                session,
                org_id=settings.default_org_id,
                trigger_type="payment_failed",
                payload={"status": "failed"},
                occurred_at=None,
                entity_type="invoice",
                entity_id="inv_123",
                idempotency_key="evt_123",
            )
            runs_second = await rules_service.evaluate_rules_for_trigger(
                session,
                org_id=settings.default_org_id,
                trigger_type="payment_failed",
                payload={"status": "failed"},
                occurred_at=None,
                entity_type="invoice",
                entity_id="inv_123",
                idempotency_key="evt_123",
            )
            await session.commit()

            assert len(runs_first) == 1
            assert len(runs_second) == 1
            assert runs_first[0].run_id == runs_second[0].run_id

            result = await session.execute(
                sa.select(RuleRun).where(
                    RuleRun.rule_id == rule.rule_id,
                    RuleRun.idempotency_key == "evt_123",
                )
            )
            assert len(result.scalars().all()) == 1

    asyncio.run(_run())
