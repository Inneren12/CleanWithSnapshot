from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.domain.leads.db_models import Lead
from app.domain.leads_scoring import schemas


@dataclass(frozen=True)
class LeadScoreReason:
    rule_key: str
    label: str
    points: int


@dataclass(frozen=True)
class LeadScoreResult:
    score: int
    reasons: list[LeadScoreReason]


def score_lead(lead: Lead, rules: list[schemas.LeadScoringRuleDefinition]) -> LeadScoreResult:
    payload = _build_payload(lead)
    total = 0
    reasons: list[LeadScoreReason] = []
    for rule in rules:
        if _matches_rule(payload, rule):
            total += rule.points
            reasons.append(
                LeadScoreReason(rule_key=rule.key, label=rule.label, points=rule.points)
            )
    return LeadScoreResult(score=total, reasons=reasons)


def _build_payload(lead: Lead) -> dict[str, Any]:
    return {
        "lead_id": lead.lead_id,
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "postal_code": lead.postal_code,
        "address": lead.address,
        "status": lead.status,
        "utm_source": lead.utm_source,
        "utm_medium": lead.utm_medium,
        "utm_campaign": lead.utm_campaign,
        "utm_term": lead.utm_term,
        "utm_content": lead.utm_content,
        "source": lead.source,
        "campaign": lead.campaign,
        "keyword": lead.keyword,
        "landing_page": lead.landing_page,
        "referrer": lead.referrer,
        "structured_inputs": lead.structured_inputs or {},
        "estimate_snapshot": lead.estimate_snapshot or {},
    }


def _matches_rule(payload: Mapping[str, Any], rule: schemas.LeadScoringRuleDefinition) -> bool:
    if not rule.conditions:
        return True
    for condition in rule.conditions:
        if not _evaluate_condition(payload, condition):
            return False
    return True


def _evaluate_condition(payload: Mapping[str, Any], condition: schemas.LeadScoringCondition) -> bool:
    actual = _get_payload_value(payload, condition.field)
    op = condition.op.lower()
    expected = condition.value

    if op in {"equals", "eq", "="}:
        return actual == expected
    if op == "contains":
        return _contains(actual, expected)
    if op == "in":
        return _in_set(actual, expected)
    if op == "exists":
        return _exists(actual)
    if op in {"lt", "<"}:
        return _compare_numbers(actual, expected, "lt")
    if op in {"gt", ">"}:
        return _compare_numbers(actual, expected, "gt")
    if op in {"lte", "<="}:
        return _compare_numbers(actual, expected, "lte")
    if op in {"gte", ">="}:
        return _compare_numbers(actual, expected, "gte")
    return False


def _get_payload_value(payload: Mapping[str, Any], field: str) -> Any:
    current: Any = payload
    for part in field.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return None
    return current


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return expected in actual
    if isinstance(actual, (list, tuple, set)):
        return expected in actual
    return False


def _in_set(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    return False


def _exists(actual: Any) -> bool:
    if actual is None:
        return False
    if isinstance(actual, (list, tuple, dict, set)):
        return len(actual) > 0
    if isinstance(actual, str):
        return actual.strip() != ""
    return True


def _compare_numbers(actual: Any, expected: Any, op: str) -> bool:
    if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
        return False
    if op == "lt":
        return actual < expected
    if op == "gt":
        return actual > expected
    if op == "lte":
        return actual <= expected
    if op == "gte":
        return actual >= expected
    return False
