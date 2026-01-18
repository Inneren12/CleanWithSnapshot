from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications_center import db_models as notifications_db_models
from app.domain.rules.db_models import Rule, RuleEscalation, RuleRun
from app.infra.communication import NoopCommunicationAdapter, TwilioCommunicationAdapter
from app.infra.email import EmailAdapter, NoopEmailAdapter
from app.settings import settings

logger = logging.getLogger(__name__)


EmailAdapterLike = EmailAdapter | NoopEmailAdapter
CommunicationAdapterLike = TwilioCommunicationAdapter | NoopCommunicationAdapter


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _coerce_headers(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    headers: dict[str, str] = {}
    for key, raw in value.items():
        name = _coerce_str(key)
        header_value = _coerce_str(raw)
        if name and header_value:
            headers[name] = header_value
    return headers or None


def _normalize_priority(value: str | None) -> str:
    if not value:
        return "NORMAL"
    normalized = value.strip().upper()
    return normalized or "NORMAL"


def _log_action(action_type: str, status: str, extra: dict[str, Any]) -> None:
    logger.info(
        "rules_action_%s" % status,
        extra={"extra": {"action_type": action_type, **extra}},
    )


async def execute_rule_actions(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    rule: Rule,
    run: RuleRun,
    actions: list[Any],
    payload: dict[str, Any],
    dry_run: bool,
    email_adapter: EmailAdapterLike | None = None,
    communication_adapter: CommunicationAdapterLike | None = None,
) -> None:
    if not actions:
        return

    for action in actions:
        if not isinstance(action, Mapping):
            _log_action("unknown", "skipped", {"reason": "invalid_action", "action": action})
            continue

        action_type = _coerce_str(action.get("type"))
        if not action_type:
            _log_action("unknown", "skipped", {"reason": "missing_type", "action": action})
            continue

        if dry_run:
            _log_action(action_type, "intent", {"rule_id": str(rule.rule_id), "run_id": str(run.run_id)})
            continue

        if action_type == "create_notification_event":
            await _handle_notification_event(session, org_id, rule, run, action, payload)
            continue

        if action_type == "send_email":
            await _handle_send_email(rule, run, action, email_adapter)
            continue

        if action_type == "send_sms":
            await _handle_send_sms(rule, run, action, communication_adapter)
            continue

        if action_type == "escalate":
            await _handle_escalation(
                session,
                org_id,
                rule,
                run,
                action,
                email_adapter,
                communication_adapter,
            )
            continue

        if action_type == "send_call":
            _log_action(
                action_type,
                "skipped",
                {
                    "reason": "not_implemented",
                    "rule_id": str(rule.rule_id),
                    "run_id": str(run.run_id),
                },
            )
            continue

        _log_action(
            action_type,
            "skipped",
            {"reason": "unsupported_action", "rule_id": str(rule.rule_id), "run_id": str(run.run_id)},
        )


async def _handle_escalation(
    session: AsyncSession,
    org_id: uuid.UUID,
    rule: Rule,
    run: RuleRun,
    action: Mapping[str, Any],
    email_adapter: EmailAdapterLike | None,
    communication_adapter: CommunicationAdapterLike | None,
) -> None:
    policy = rule.escalation_policy_json or {}
    if not isinstance(policy, Mapping):
        _log_action(
            "escalate",
            "skipped",
            {"reason": "invalid_policy", "rule_id": str(rule.rule_id), "run_id": str(run.run_id)},
        )
        return

    cooldown_minutes = getattr(rule, "escalation_cooldown_minutes", 0) or 0
    entity_type = _coerce_str(action.get("entity_type")) or run.entity_type
    entity_id = _coerce_str(action.get("entity_id")) or run.entity_id
    if cooldown_minutes > 0 and await _cooldown_active(
        session,
        org_id=org_id,
        rule_id=rule.rule_id,
        entity_type=entity_type,
        entity_id=entity_id,
        cooldown_minutes=cooldown_minutes,
    ):
        _log_action(
            "escalate",
            "skipped",
            {
                "reason": "cooldown_active",
                "rule_id": str(rule.rule_id),
                "run_id": str(run.run_id),
                "cooldown_minutes": cooldown_minutes,
            },
        )
        return

    levels_attempted: list[str] = []

    level1_email = policy.get("level1_email")
    if isinstance(level1_email, Mapping):
        await _handle_send_email(
            rule,
            run,
            {
                "to": level1_email.get("to"),
                "subject": level1_email.get("subject"),
                "body": level1_email.get("body"),
                "headers": level1_email.get("headers"),
            },
            email_adapter,
        )
        levels_attempted.append("level1_email")

    level2_sms = policy.get("level2_sms")
    if isinstance(level2_sms, Mapping):
        await _handle_send_sms(
            rule,
            run,
            {
                "to_number": level2_sms.get("to_number"),
                "body": level2_sms.get("body"),
            },
            communication_adapter,
        )
        levels_attempted.append("level2_sms")

    level3_call = policy.get("level3_call")
    if isinstance(level3_call, Mapping):
        _log_action(
            "send_call",
            "skipped",
            {
                "reason": "not_implemented",
                "rule_id": str(rule.rule_id),
                "run_id": str(run.run_id),
                "to_number": _coerce_str(level3_call.get("to_number")),
            },
        )
        levels_attempted.append("level3_call")

    if not levels_attempted:
        _log_action(
            "escalate",
            "skipped",
            {"reason": "missing_levels", "rule_id": str(rule.rule_id), "run_id": str(run.run_id)},
        )
        return

    escalation = RuleEscalation(
        escalation_id=uuid.uuid4(),
        org_id=org_id,
        rule_id=rule.rule_id,
        entity_type=entity_type,
        entity_id=entity_id,
        levels_json=levels_attempted,
    )
    session.add(escalation)
    await session.flush()
    _log_action(
        "escalate",
        "completed",
        {
            "rule_id": str(rule.rule_id),
            "run_id": str(run.run_id),
            "levels": levels_attempted,
        },
    )


async def _cooldown_active(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    entity_type: str | None,
    entity_id: str | None,
    cooldown_minutes: int,
) -> bool:
    conditions = [RuleEscalation.org_id == org_id, RuleEscalation.rule_id == rule_id]
    if entity_type is None:
        conditions.append(RuleEscalation.entity_type.is_(None))
    else:
        conditions.append(RuleEscalation.entity_type == entity_type)
    if entity_id is None:
        conditions.append(RuleEscalation.entity_id.is_(None))
    else:
        conditions.append(RuleEscalation.entity_id == entity_id)
    stmt = (
        sa.select(RuleEscalation.occurred_at)
        .where(*conditions)
        .order_by(RuleEscalation.occurred_at.desc())
        .limit(1)
    )
    last_occurred = await session.scalar(stmt)
    if not last_occurred:
        return False
    if last_occurred.tzinfo is None:
        last_occurred = last_occurred.replace(tzinfo=timezone.utc)
    threshold = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
    return last_occurred >= threshold


async def _handle_notification_event(
    session: AsyncSession,
    org_id: uuid.UUID,
    rule: Rule,
    run: RuleRun,
    action: Mapping[str, Any],
    payload: dict[str, Any],
) -> None:
    title = _coerce_str(action.get("title"))
    body = _coerce_str(action.get("body"))
    if not title or not body:
        _log_action(
            "create_notification_event",
            "skipped",
            {
                "reason": "missing_title_or_body",
                "rule_id": str(rule.rule_id),
                "run_id": str(run.run_id),
            },
        )
        return

    priority = _normalize_priority(_coerce_str(action.get("priority")))
    event_type = _coerce_str(action.get("event_type")) or rule.trigger_type
    entity_type = _coerce_str(action.get("entity_type")) or run.entity_type
    entity_id = _coerce_str(action.get("entity_id")) or run.entity_id
    action_href = _coerce_str(action.get("action_href"))
    action_kind = _coerce_str(action.get("action_kind"))

    event = notifications_db_models.NotificationEvent(
        org_id=org_id,
        priority=priority,
        type=event_type,
        title=title,
        body=body,
        entity_type=entity_type,
        entity_id=entity_id,
        action_href=action_href,
        action_kind=action_kind,
    )
    session.add(event)
    await session.flush()
    _log_action(
        "create_notification_event",
        "completed",
        {
            "rule_id": str(rule.rule_id),
            "run_id": str(run.run_id),
            "event_id": str(event.id),
            "payload_keys": list(payload.keys()),
        },
    )


async def _handle_send_email(
    rule: Rule,
    run: RuleRun,
    action: Mapping[str, Any],
    email_adapter: EmailAdapterLike | None,
) -> None:
    if settings.email_mode == "off":
        _log_action(
            "send_email",
            "skipped",
            {
                "reason": "email_disabled",
                "rule_id": str(rule.rule_id),
                "run_id": str(run.run_id),
            },
        )
        return

    if email_adapter is None:
        _log_action(
            "send_email",
            "skipped",
            {
                "reason": "missing_adapter",
                "rule_id": str(rule.rule_id),
                "run_id": str(run.run_id),
            },
        )
        return

    recipient = _coerce_str(action.get("to")) or _coerce_str(action.get("recipient"))
    subject = _coerce_str(action.get("subject"))
    body = _coerce_str(action.get("body"))
    if not recipient or not subject or not body:
        _log_action(
            "send_email",
            "skipped",
            {
                "reason": "missing_fields",
                "rule_id": str(rule.rule_id),
                "run_id": str(run.run_id),
            },
        )
        return

    headers = _coerce_headers(action.get("headers"))
    delivered = await email_adapter.send_email(recipient=recipient, subject=subject, body=body, headers=headers)
    _log_action(
        "send_email",
        "completed" if delivered else "skipped",
        {
            "rule_id": str(rule.rule_id),
            "run_id": str(run.run_id),
            "recipient": recipient,
        },
    )


async def _handle_send_sms(
    rule: Rule,
    run: RuleRun,
    action: Mapping[str, Any],
    communication_adapter: CommunicationAdapterLike | None,
) -> None:
    if settings.sms_mode != "twilio":
        _log_action(
            "send_sms",
            "skipped",
            {
                "reason": "sms_disabled",
                "rule_id": str(rule.rule_id),
                "run_id": str(run.run_id),
            },
        )
        return

    if communication_adapter is None:
        _log_action(
            "send_sms",
            "skipped",
            {
                "reason": "missing_adapter",
                "rule_id": str(rule.rule_id),
                "run_id": str(run.run_id),
            },
        )
        return

    to_number = _coerce_str(action.get("to")) or _coerce_str(action.get("to_number"))
    body = _coerce_str(action.get("body"))
    if not to_number or not body:
        _log_action(
            "send_sms",
            "skipped",
            {
                "reason": "missing_fields",
                "rule_id": str(rule.rule_id),
                "run_id": str(run.run_id),
            },
        )
        return

    result = await communication_adapter.send_sms(to_number=to_number, body=body)
    _log_action(
        "send_sms",
        "completed" if result.status == "sent" else "skipped",
        {
            "rule_id": str(rule.rule_id),
            "run_id": str(run.run_id),
            "to_number": to_number,
            "status": result.status,
            "error_code": result.error_code,
        },
    )
