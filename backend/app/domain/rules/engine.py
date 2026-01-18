from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

SUPPORTED_TRIGGERS = {
    "worker_no_show",
    "payment_failed",
    "negative_review",
    "low_inventory",
    "high_value_lead",
}


@dataclass(frozen=True)
class TriggerEvent:
    payload: dict[str, Any]
    occurred_at: datetime | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    idempotency_key: str | None = None


class TriggerAdapter:
    trigger_type: str

    def normalize(self, event_payload: dict[str, Any]) -> TriggerEvent:
        raise NotImplementedError


class BaseTriggerAdapter(TriggerAdapter):
    trigger_type: str

    def normalize(self, event_payload: dict[str, Any]) -> TriggerEvent:
        return TriggerEvent(
            payload=event_payload,
            occurred_at=_coerce_datetime(event_payload.get("occurred_at")),
            entity_type=_coerce_str(event_payload.get("entity_type")),
            entity_id=_coerce_str(event_payload.get("entity_id")),
            idempotency_key=_coerce_str(event_payload.get("idempotency_key")),
        )


class WorkerNoShowAdapter(BaseTriggerAdapter):
    trigger_type = "worker_no_show"


class PaymentFailedAdapter(BaseTriggerAdapter):
    trigger_type = "payment_failed"


class NegativeReviewAdapter(BaseTriggerAdapter):
    trigger_type = "negative_review"


class LowInventoryAdapter(BaseTriggerAdapter):
    trigger_type = "low_inventory"


class HighValueLeadAdapter(BaseTriggerAdapter):
    trigger_type = "high_value_lead"


_TRIGGER_ADAPTERS: dict[str, TriggerAdapter] = {
    adapter.trigger_type: adapter
    for adapter in (
        WorkerNoShowAdapter(),
        PaymentFailedAdapter(),
        NegativeReviewAdapter(),
        LowInventoryAdapter(),
        HighValueLeadAdapter(),
    )
}


def get_trigger_adapter(trigger_type: str) -> TriggerAdapter:
    adapter = _TRIGGER_ADAPTERS.get(trigger_type)
    if adapter is None:
        logger.warning("rules_unknown_trigger", extra={"extra": {"trigger_type": trigger_type}})
        return BaseTriggerAdapter()
    return adapter


def evaluate_conditions(payload: Mapping[str, Any], conditions: Mapping[str, Any] | None) -> bool:
    if not conditions:
        return True

    if _has_compound_conditions(conditions):
        all_conditions = conditions.get("all", [])
        any_conditions = conditions.get("any", [])
        not_conditions = conditions.get("not")

        if all_conditions and not _evaluate_condition_group(payload, all_conditions, all):
            return False
        if any_conditions and not _evaluate_condition_group(payload, any_conditions, any):
            return False
        if not_conditions is not None:
            return not _evaluate_condition(payload, not_conditions)
        return True

    for key, expected in conditions.items():
        if payload.get(key) != expected:
            return False
    return True


def _has_compound_conditions(conditions: Mapping[str, Any]) -> bool:
    return any(key in conditions for key in ("all", "any", "not"))


def _evaluate_condition_group(
    payload: Mapping[str, Any],
    conditions: Sequence[Any],
    aggregator,
) -> bool:
    if not isinstance(conditions, Sequence):
        return False
    evaluations = (_evaluate_condition(payload, condition) for condition in conditions)
    return aggregator(evaluations)


def _evaluate_condition(payload: Mapping[str, Any], condition: Any) -> bool:
    if isinstance(condition, Mapping) and "field" in condition:
        field = condition.get("field")
        if not isinstance(field, str) or not field:
            return False
        op = condition.get("op", "equals")
        expected = condition.get("value")
        actual = _get_payload_value(payload, field)
        return _apply_operator(actual, expected, op)

    if isinstance(condition, Mapping) and _has_compound_conditions(condition):
        return evaluate_conditions(payload, condition)

    return False


def _get_payload_value(payload: Mapping[str, Any], field: str) -> Any:
    current: Any = payload
    for part in field.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return None
    return current


def _apply_operator(actual: Any, expected: Any, op: Any) -> bool:
    if not isinstance(op, str):
        return False
    normalized = op.lower()
    if normalized in {"equals", "eq", "="}:
        return actual == expected
    if normalized == "contains":
        return _contains(actual, expected)
    if normalized in {"lt", "<"}:
        return _compare_numbers(actual, expected, "lt")
    if normalized in {"gt", ">"}:
        return _compare_numbers(actual, expected, "gt")
    if normalized in {"lte", "<="}:
        return _compare_numbers(actual, expected, "lte")
    if normalized in {"gte", ">="}:
        return _compare_numbers(actual, expected, "gte")
    if normalized == "in":
        return _in_set(actual, expected)
    return False


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return expected in actual
    if isinstance(actual, (list, tuple, set)):
        return expected in actual
    return False


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


def _in_set(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    return False


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
