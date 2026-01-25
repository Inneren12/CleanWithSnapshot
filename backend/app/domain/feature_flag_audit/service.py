from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.config_audit.db_models import ConfigAuditActor, ConfigActorType
from app.domain.feature_flag_audit.db_models import FeatureFlagAuditAction, FeatureFlagAuditLog

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
TARGETING_REDACT_KEYS = {
    "user",
    "users",
    "user_id",
    "user_ids",
    "email",
    "emails",
    "phone",
    "phones",
}


def _is_sensitive_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = key.lower()
    if normalized in SENSITIVE_KEYS:
        return True
    return normalized.endswith(SENSITIVE_SUFFIXES)


def _requires_targeting_redaction(key: str | None) -> bool:
    if not key:
        return False
    return key.lower() in TARGETING_REDACT_KEYS


def _sanitize_value(value: Any, key: str | None = None) -> Any:
    if _is_sensitive_key(key) or _requires_targeting_redaction(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {item_key: _sanitize_value(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _normalize_payload(payload: Any) -> Any:
    if payload is None:
        return None
    encoded = jsonable_encoder(payload)
    return _sanitize_value(encoded)


def _rollout_percentage(enabled: bool | None) -> int:
    if enabled:
        return 100
    return 0


def build_rollout_context(
    *,
    enabled: bool | None,
    targeting_rules: list[dict] | None,
    reason: str | None = None,
) -> dict[str, Any]:
    context = {
        "enabled": bool(enabled),
        "percentage": _rollout_percentage(enabled),
        "targeting_rules": _sanitize_value(targeting_rules or [], "targeting_rules"),
    }
    if reason:
        context["reason"] = reason
    return context


async def audit_feature_flag_change(
    session: AsyncSession,
    *,
    actor: ConfigAuditActor,
    org_id,
    flag_key: str,
    action: FeatureFlagAuditAction,
    before_state: Any,
    after_state: Any,
    rollout_context: dict | None,
    request_id: str | None,
) -> FeatureFlagAuditLog:
    if not flag_key:
        raise ValueError("flag_key is required")
    log = FeatureFlagAuditLog(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        actor_role=actor.actor_role,
        auth_method=actor.auth_method,
        actor_source=actor.actor_source,
        org_id=org_id,
        flag_key=flag_key,
        action=action.value,
        before_state=_normalize_payload(before_state),
        after_state=_normalize_payload(after_state),
        rollout_context=_normalize_payload(rollout_context),
        request_id=request_id,
    )
    session.add(log)
    await session.flush()
    return log


async def list_feature_flag_audit_logs(
    session: AsyncSession,
    *,
    org_id,
    flag_key: str | None = None,
    actor_type: ConfigActorType | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[FeatureFlagAuditLog]:
    stmt = select(FeatureFlagAuditLog).order_by(
        FeatureFlagAuditLog.occurred_at.desc(),
        FeatureFlagAuditLog.audit_id.desc(),
    )
    if org_id is not None:
        stmt = stmt.where(FeatureFlagAuditLog.org_id == org_id)
    if flag_key:
        stmt = stmt.where(FeatureFlagAuditLog.flag_key == flag_key)
    if actor_type is not None:
        stmt = stmt.where(FeatureFlagAuditLog.actor_type == actor_type.value)
    if from_ts is not None:
        stmt = stmt.where(FeatureFlagAuditLog.occurred_at >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(FeatureFlagAuditLog.occurred_at <= to_ts)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())
