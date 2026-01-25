from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity
from app.domain.config_audit.db_models import (
    ConfigAuditAction,
    ConfigAuditActor,
    ConfigAuditLog,
    ConfigActorType,
    ConfigScope,
)

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


def admin_actor(identity: AdminIdentity, *, auth_method: str) -> ConfigAuditActor:
    return ConfigAuditActor(
        actor_type=ConfigActorType.ADMIN,
        actor_id=identity.username,
        actor_role=getattr(identity.role, "value", str(identity.role)),
        auth_method=auth_method,
    )


def system_actor(source: str) -> ConfigAuditActor:
    return ConfigAuditActor(
        actor_type=ConfigActorType.SYSTEM,
        actor_id=None,
        actor_role=None,
        auth_method=None,
        actor_source=source,
    )


def automation_actor(source: str) -> ConfigAuditActor:
    return ConfigAuditActor(
        actor_type=ConfigActorType.AUTOMATION,
        actor_id=None,
        actor_role=None,
        auth_method=None,
        actor_source=source,
    )


def _is_sensitive_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = key.lower()
    if normalized in SENSITIVE_KEYS:
        return True
    return normalized.endswith(SENSITIVE_SUFFIXES)


def _sanitize_value(value: Any, key: str | None = None) -> Any:
    if key and _is_sensitive_key(key):
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


async def record_config_change(
    session: AsyncSession,
    *,
    actor: ConfigAuditActor,
    org_id,
    config_scope: ConfigScope,
    config_key: str,
    action: ConfigAuditAction,
    before_value: Any,
    after_value: Any,
    request_id: str | None,
) -> ConfigAuditLog:
    if not config_key:
        raise ValueError("config_key is required")
    log = ConfigAuditLog(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        actor_role=actor.actor_role,
        auth_method=actor.auth_method,
        actor_source=actor.actor_source,
        org_id=org_id,
        config_scope=config_scope.value,
        config_key=config_key,
        action=action.value,
        before_value=_normalize_payload(before_value),
        after_value=_normalize_payload(after_value),
        request_id=request_id,
    )
    session.add(log)
    await session.flush()
    return log


async def list_config_audit_logs(
    session: AsyncSession,
    *,
    org_id,
    config_scope: ConfigScope | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ConfigAuditLog]:
    stmt = select(ConfigAuditLog).order_by(
        ConfigAuditLog.occurred_at.desc(),
        ConfigAuditLog.audit_id.desc(),
    )
    if org_id is not None:
        stmt = stmt.where(ConfigAuditLog.org_id == org_id)
    if config_scope is not None:
        stmt = stmt.where(ConfigAuditLog.config_scope == config_scope.value)
    if from_ts is not None:
        stmt = stmt.where(ConfigAuditLog.occurred_at >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(ConfigAuditLog.occurred_at <= to_ts)
    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())
