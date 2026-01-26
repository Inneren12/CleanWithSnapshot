from __future__ import annotations

import hashlib
import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity
from app.domain.admin_audit import service as admin_audit_service
from app.domain.admin_audit.db_models import (
    AdminAuditActionType,
    AdminAuditLog,
    AdminAuditSensitivity,
)

DATA_EXPORT_REQUESTED = "DATA_EXPORT_REQUESTED"
DATA_EXPORT_COMPLETED = "DATA_EXPORT_COMPLETED"
DATA_EXPORT_FAILED = "DATA_EXPORT_FAILED"
DATA_EXPORT_DOWNLOADED = "DATA_EXPORT_DOWNLOADED"
DATA_EXPORT_DOWNLOAD_DENIED = "DATA_EXPORT_DOWNLOAD_DENIED"

DATA_EXPORT_AUDIT_EVENTS = {
    DATA_EXPORT_REQUESTED,
    DATA_EXPORT_COMPLETED,
    DATA_EXPORT_FAILED,
    DATA_EXPORT_DOWNLOADED,
    DATA_EXPORT_DOWNLOAD_DENIED,
}

_ACTION_TYPE_MAP = {
    DATA_EXPORT_REQUESTED: AdminAuditActionType.WRITE,
    DATA_EXPORT_COMPLETED: AdminAuditActionType.WRITE,
    DATA_EXPORT_FAILED: AdminAuditActionType.WRITE,
    DATA_EXPORT_DOWNLOADED: AdminAuditActionType.READ,
    DATA_EXPORT_DOWNLOAD_DENIED: AdminAuditActionType.READ,
}


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_subject_id(subject_id: str, subject_type: str | None) -> str:
    if subject_type == "email":
        return _hash_identifier(subject_id.lower())
    return subject_id


def _clean_context(context: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in context.items() if value is not None}


async def audit_data_export_event(
    session: AsyncSession,
    *,
    event: str,
    org_id: uuid.UUID,
    export_id: uuid.UUID | str,
    subject_id: str,
    actor_type: Literal["subject", "admin", "system"],
    actor_id: str | None,
    request_id: str | None,
    subject_type: str | None = None,
    status: str | None = None,
    size_bytes: int | None = None,
    error_code: str | None = None,
    reason_code: str | None = None,
    on_behalf_of: dict[str, str] | None = None,
    admin_identity: AdminIdentity | None = None,
) -> AdminAuditLog | None:
    if event not in DATA_EXPORT_AUDIT_EVENTS:
        raise ValueError(f"Unsupported data export audit event: {event}")

    normalized_subject_id = _normalize_subject_id(subject_id, subject_type)
    normalized_on_behalf_of: dict[str, str] | None = None
    if on_behalf_of:
        normalized_on_behalf_of = dict(on_behalf_of)
        ob_subject_id = normalized_on_behalf_of.get("subject_id")
        ob_subject_type = normalized_on_behalf_of.get("subject_type", subject_type)
        if ob_subject_id and ob_subject_type:
            normalized_on_behalf_of["subject_id"] = _normalize_subject_id(
                ob_subject_id, ob_subject_type
            )
    if actor_type == "subject":
        actor_id = actor_id or normalized_subject_id
    elif actor_type == "admin" and admin_identity and actor_id is None:
        actor_id = getattr(admin_identity, "admin_id", None) or admin_identity.username

    context = _clean_context(
        {
            "request_id": request_id,
            "export_id": str(export_id),
            "subject_id": normalized_subject_id,
            "subject_type": subject_type,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "status": status,
            "size_bytes": size_bytes,
            "error_code": error_code,
            "reason_code": reason_code,
            "on_behalf_of": normalized_on_behalf_of,
        }
    )

    action_type = _ACTION_TYPE_MAP[event]
    sensitivity = AdminAuditSensitivity.CRITICAL

    if actor_type == "admin" and admin_identity:
        return await admin_audit_service.audit_admin_action(
            session,
            identity=admin_identity,
            org_id=org_id,
            action=event,
            action_type=action_type,
            sensitivity_level=sensitivity,
            resource_type="data_export",
            resource_id=str(export_id),
            context=context,
        )

    return await admin_audit_service.record_system_action(
        session,
        org_id=org_id,
        action=event,
        resource_type="data_export",
        resource_id=str(export_id),
        context=context,
        action_type=action_type,
        sensitivity_level=sensitivity,
    )
