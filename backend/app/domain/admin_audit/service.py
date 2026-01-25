from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity
from app.domain.admin_audit.db_models import (
    AdminAuditActionType,
    AdminAuditLog,
    AdminAuditSensitivity,
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
    sanitized_context = None
    if resolved_action_type == AdminAuditActionType.WRITE:
        sanitized_before = _sanitize_payload(before)
        sanitized_after = _sanitize_payload(after)
    else:
        sanitized_context = _sanitize_payload(context) if context else None

    log = AdminAuditLog(
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
    )
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
