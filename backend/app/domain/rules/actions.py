from __future__ import annotations

import logging
from typing import Any, Mapping
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications_center import db_models as notifications_db_models
from app.domain.rules.db_models import Rule, RuleRun
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
