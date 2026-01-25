from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.config_audit.db_models import ConfigAuditActor
from app.domain.integration_audit.db_models import (
    IntegrationAuditAction,
    IntegrationAuditContext,
    IntegrationAuditLog,
    IntegrationScope,
)

REDACTED_PLACEHOLDER = "***REDACTED***"

SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "auth_token",
    "authorization",
    "client_secret",
    "encrypted_refresh_token",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "secret_key",
    "token",
    "webhook_secret",
}
SENSITIVE_SUFFIXES = ("_token", "_secret", "_password", "_key")

INTEGRATION_SECRET_FIELDS: dict[str, set[str]] = {
    "google_calendar": {"encrypted_refresh_token"},
    "quickbooks": {"encrypted_refresh_token"},
    "stripe": {"secret_key", "webhook_secret", "api_key"},
    "twilio": {"auth_token"},
    "sendgrid": {"api_key"},
    "maps": {"api_key"},
}


def _is_sensitive_key(key: str | None, *, secret_fields: Iterable[str]) -> bool:
    if not key:
        return False
    normalized = key.lower()
    if normalized in (name.lower() for name in secret_fields):
        return True
    if normalized in SENSITIVE_KEYS:
        return True
    return normalized.endswith(SENSITIVE_SUFFIXES)


def _fingerprint(value: Any) -> str:
    if isinstance(value, (dict, list)):
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    else:
        payload = str(value)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _record_redaction(
    redaction_map: dict[str, dict[str, Any]],
    path: str,
    phase: str,
    value: Any,
    fingerprint: str | None,
) -> None:
    entry = redaction_map.setdefault(path, {"redacted": True, "before": None, "after": None})
    entry[phase] = {
        "present": value is not None,
        "fingerprint": fingerprint,
    }


def _sanitize_payload(
    payload: Any,
    *,
    secret_fields: Iterable[str],
    redaction_map: dict[str, dict[str, Any]],
    phase: str,
    path: str = "",
) -> Any:
    if payload is None:
        return None
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            next_path = f"{path}.{key}" if path else key
            if _is_sensitive_key(key, secret_fields=secret_fields):
                fingerprint = _fingerprint(value) if value is not None else None
                _record_redaction(redaction_map, next_path, phase, value, fingerprint)
                sanitized[key] = REDACTED_PLACEHOLDER if value is not None else None
                sanitized[f"{key}_present"] = value is not None
                sanitized[f"{key}_fingerprint"] = fingerprint if value is not None else None
                continue
            sanitized[key] = _sanitize_payload(
                value,
                secret_fields=secret_fields,
                redaction_map=redaction_map,
                phase=phase,
                path=next_path,
            )
        return sanitized
    if isinstance(payload, list):
        return [
            _sanitize_payload(
                item,
                secret_fields=secret_fields,
                redaction_map=redaction_map,
                phase=phase,
                path=path,
            )
            for item in payload
        ]
    return payload


def _normalize_payload(payload: Any) -> Any:
    if payload is None:
        return None
    return jsonable_encoder(payload)


def _secrets_changed(
    before_state: dict | None,
    after_state: dict | None,
    secret_fields: Iterable[str],
) -> bool:
    if not before_state or not after_state:
        return False
    for key in secret_fields:
        if before_state.get(key) != after_state.get(key):
            return True
    return False


def resolve_action(
    *,
    before_state: dict | None,
    after_state: dict | None,
    secret_fields: Iterable[str],
    explicit_action: IntegrationAuditAction | None = None,
) -> IntegrationAuditAction:
    if explicit_action is not None:
        return explicit_action
    if before_state is None and after_state is None:
        raise ValueError("before_state or after_state required")
    if after_state is None:
        return IntegrationAuditAction.DELETE
    if before_state is None:
        return IntegrationAuditAction.CREATE

    before_connected = bool(before_state.get("connected"))
    after_connected = bool(after_state.get("connected"))
    if not before_connected and after_connected:
        return IntegrationAuditAction.ENABLE
    if before_connected and not after_connected:
        return IntegrationAuditAction.DISABLE
    if _secrets_changed(before_state, after_state, secret_fields):
        return IntegrationAuditAction.ROTATE_SECRET
    return IntegrationAuditAction.UPDATE


async def audit_integration_config_change(
    session: AsyncSession,
    *,
    actor: ConfigAuditActor,
    org_id,
    context: IntegrationAuditContext,
    before_state: Any,
    after_state: Any,
    request_id: str | None,
    action: IntegrationAuditAction | None = None,
) -> IntegrationAuditLog:
    if not context.integration_type:
        raise ValueError("integration_type is required")
    secret_fields = INTEGRATION_SECRET_FIELDS.get(context.integration_type, set())
    normalized_before = _normalize_payload(before_state)
    normalized_after = _normalize_payload(after_state)
    resolved_action = resolve_action(
        before_state=normalized_before if isinstance(normalized_before, dict) else None,
        after_state=normalized_after if isinstance(normalized_after, dict) else None,
        secret_fields=secret_fields,
        explicit_action=action,
    )

    redaction_map: dict[str, dict[str, Any]] = {}
    sanitized_before = _sanitize_payload(
        normalized_before,
        secret_fields=secret_fields,
        redaction_map=redaction_map,
        phase="before",
    )
    sanitized_after = _sanitize_payload(
        normalized_after,
        secret_fields=secret_fields,
        redaction_map=redaction_map,
        phase="after",
    )

    log = IntegrationAuditLog(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        actor_role=actor.actor_role,
        auth_method=actor.auth_method,
        actor_source=actor.actor_source,
        org_id=org_id,
        integration_type=context.integration_type,
        integration_scope=context.integration_scope.value,
        action=resolved_action.value,
        before_state=sanitized_before,
        after_state=sanitized_after,
        redaction_map=redaction_map or None,
        request_id=request_id,
    )
    session.add(log)
    await session.flush()
    return log


async def list_integration_audit_logs(
    session: AsyncSession,
    *,
    org_id,
    integration_type: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[IntegrationAuditLog]:
    stmt = select(IntegrationAuditLog).order_by(
        IntegrationAuditLog.occurred_at.desc(),
        IntegrationAuditLog.audit_id.desc(),
    )
    if org_id is not None:
        stmt = stmt.where(IntegrationAuditLog.org_id == org_id)
    if integration_type:
        stmt = stmt.where(IntegrationAuditLog.integration_type == integration_type)
    if from_ts is not None:
        stmt = stmt.where(IntegrationAuditLog.occurred_at >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(IntegrationAuditLog.occurred_at <= to_ts)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())
