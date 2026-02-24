from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity
# db_models imported later or partially to avoid cycle if necessary
# Note: we need to break the cycle. service -> db_models -> service is bad.
# But here service imports db_models.
# And db_models imports infra.db -> infra.models -> break_glass -> service -> admin_audit.service
# Cycle: admin_audit.service -> admin_audit.db_models -> infra.db -> infra.models -> break_glass -> admin_audit.service
# To fix: admin_audit.service should NOT be imported by break_glass at top level if possible, or use TYPE_CHECKING.
# Let's inspect break_glass/service.py
from app.domain.admin_audit.db_models import (
    AdminAuditLog,
    AdminAuditSensitivity,
    AdminAuditActionType,
)
from app.infra.logging import redact_pii
from app.settings import settings


@dataclass(frozen=True)
class AuditListFilters:
    admin_id: str | None = None
    action_type: AdminAuditActionType | None = None
    resource_type: str | None = None
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    limit: int = 50
    offset: int = 0


def _infer_action_type(action: str) -> AdminAuditActionType:
    normalized = action.strip().upper()
    if normalized.startswith("GET ") or normalized.startswith("VIEW_"):
        return AdminAuditActionType.READ
    return AdminAuditActionType.WRITE


_SENSITIVE_AUDIT_KEYS = {
    "name",
    "first_name",
    "last_name",
    "full_name",
    "email",
    "phone",
    "address",
    "notes",
    "note",
    "comment",
    "message",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "signature",
    "sig",
    "authorization",
}


def _sanitize_payload(payload: Any) -> Any:
    if payload is None:
        return None
    if isinstance(payload, (bytes, bytearray)):
        return None
    if isinstance(payload, str):
        return redact_pii(payload)
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            normalized = str(key).lower()
            if normalized in _SENSITIVE_AUDIT_KEYS:
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = _sanitize_payload(value)
        return sanitized
    return payload


def _resolve_admin_id(identity: AdminIdentity, admin_id: str | None) -> str | None:
    return admin_id or getattr(identity, "admin_id", None) or identity.username


def _system_actor_payload() -> dict[str, str]:
    return {
        "actor": "system",
        "role": "system",
        "auth_method": "system",
    }


def _calculate_entry_hash(entry: AdminAuditLog, prev_hash: str | None) -> str:
    payload = {
        "audit_id": str(entry.audit_id),
        "org_id": str(entry.org_id),
        "action": entry.action,
        "actor": entry.actor,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "prev_hash": prev_hash,
        "before": entry.before,
        "after": entry.after,
        "context": entry.context,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _get_last_hash(session: AsyncSession) -> str | None:
    stmt = select(AdminAuditLog.hash).order_by(
        AdminAuditLog.created_at.desc(), AdminAuditLog.audit_id.desc()
    ).limit(1)
    return await session.scalar(stmt)


async def audit_admin_action(
    session: AsyncSession,
    *,
    identity: AdminIdentity,
    org_id: uuid.UUID | None = None,
    action: str,
    action_type: AdminAuditActionType | None = None,
    sensitivity_level: AdminAuditSensitivity | None = None,
    resource_type: str | None,
    resource_id: str | None,
    before: Any = None,
    after: Any = None,
    context: dict | None = None,
    admin_id: str | None = None,
    auth_method: str | None = None,
) -> AdminAuditLog | None:
    resolved_action_type = action_type or _infer_action_type(action)
    resolved_sensitivity = sensitivity_level or AdminAuditSensitivity.NORMAL
    if resolved_action_type == AdminAuditActionType.READ and resolved_sensitivity == AdminAuditSensitivity.NORMAL:
        return None

    resolved_org_id = org_id or identity.org_id or settings.default_org_id
    resolved_admin_id = _resolve_admin_id(identity, admin_id)
    resolved_auth_method = auth_method or getattr(identity, "auth_method", None)

    sanitized_before = None
    sanitized_after = None
    sanitized_context = _sanitize_payload(context) if context else None
    if resolved_action_type == AdminAuditActionType.WRITE:
        sanitized_before = _sanitize_payload(before)
        sanitized_after = _sanitize_payload(after)

    log = AdminAuditLog(
        audit_id=str(uuid.uuid4()),
        org_id=resolved_org_id,
        admin_id=resolved_admin_id,
        action=action,
        action_type=resolved_action_type.value,
        sensitivity_level=resolved_sensitivity.value,
        actor=identity.username,
        role=getattr(identity.role, "value", identity.role),
        auth_method=resolved_auth_method,
        resource_type=resource_type,
        resource_id=resource_id,
        context=sanitized_context,
        before=sanitized_before,
        after=sanitized_after,
        created_at=datetime.now(timezone.utc),  # Explicit timestamp for hash consistency
    )

    # Calculate hash chain
    prev_hash = await _get_last_hash(session)
    log.prev_hash = prev_hash
    log.hash = _calculate_entry_hash(log, prev_hash)

    session.add(log)
    return log


async def record_action(
    session: AsyncSession,
    *,
    identity: AdminIdentity,
    org_id: uuid.UUID | None = None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    before: Any,
    after: Any,
    action_type: AdminAuditActionType | None = None,
    sensitivity_level: AdminAuditSensitivity | None = None,
    context: dict | None = None,
    admin_id: str | None = None,
    auth_method: str | None = None,
) -> AdminAuditLog | None:
    return await audit_admin_action(
        session,
        identity=identity,
        org_id=org_id,
        action=action,
        action_type=action_type,
        sensitivity_level=sensitivity_level,
        resource_type=resource_type,
        resource_id=resource_id,
        before=before,
        after=after,
        context=context,
        admin_id=admin_id,
        auth_method=auth_method,
    )


async def record_system_action(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    before: Any = None,
    after: Any = None,
    context: dict | None = None,
    action_type: AdminAuditActionType | None = None,
    sensitivity_level: AdminAuditSensitivity | None = None,
) -> AdminAuditLog:
    payload = _system_actor_payload()
    resolved_action_type = action_type or AdminAuditActionType.WRITE
    resolved_sensitivity = sensitivity_level or AdminAuditSensitivity.NORMAL
    log = AdminAuditLog(
        audit_id=str(uuid.uuid4()),
        org_id=org_id,
        admin_id=None,
        action=action,
        action_type=resolved_action_type.value,
        sensitivity_level=resolved_sensitivity.value,
        actor=payload["actor"],
        role=payload["role"],
        auth_method=payload["auth_method"],
        resource_type=resource_type,
        resource_id=resource_id,
        context=_sanitize_payload(context) if context else None,
        before=_sanitize_payload(before),
        after=_sanitize_payload(after),
        created_at=datetime.now(timezone.utc),
    )

    # Calculate hash chain
    prev_hash = await _get_last_hash(session)
    log.prev_hash = prev_hash
    log.hash = _calculate_entry_hash(log, prev_hash)

    session.add(log)
    return log


async def list_admin_audit_logs(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    filters: AuditListFilters,
) -> list[AdminAuditLog]:
    stmt = select(AdminAuditLog).order_by(
        AdminAuditLog.created_at.desc(),
        AdminAuditLog.audit_id.desc(),
    )
    if org_id is not None:
        stmt = stmt.where(AdminAuditLog.org_id == org_id)
    if filters.admin_id:
        stmt = stmt.where(AdminAuditLog.admin_id == filters.admin_id)
    if filters.action_type:
        stmt = stmt.where(AdminAuditLog.action_type == filters.action_type.value)
    if filters.resource_type:
        stmt = stmt.where(AdminAuditLog.resource_type == filters.resource_type)
    if filters.from_ts is not None:
        stmt = stmt.where(AdminAuditLog.created_at >= filters.from_ts)
    if filters.to_ts is not None:
        stmt = stmt.where(AdminAuditLog.created_at <= filters.to_ts)
    stmt = stmt.limit(filters.limit).offset(filters.offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())
