from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access_review.db_models import AccessReviewRun
from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.break_glass.db_models import BreakGlassSession
from app.domain.iam import permissions as iam_permissions
from app.domain.iam.db_models import IamRole
from app.domain.saas.db_models import Membership, MembershipRole, Organization, SaaSSession, User
from app.settings import settings

ROLE_CHANGE_ACTION_RE = re.compile(r"^PATCH /v1/admin/iam/users/(?P<user_id>[^/]+)/role")


class AccessReviewScope(str, Enum):
    ORG = "org"
    GLOBAL = "global"


@dataclass(frozen=True)
class AccessReviewConfig:
    inactive_days: int = 90
    break_glass_lookback_days: int = 90
    role_change_lookback_days: int = 90
    owner_admin_allowlist: list[str] = field(default_factory=list)
    owner_admin_allowlist_by_org: dict[str, list[str]] = field(default_factory=dict)
    mfa_required: bool | None = None
    mfa_required_roles: list[str] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "AccessReviewConfig":
        if not payload:
            return cls()
        return cls(
            inactive_days=int(payload.get("inactive_days", 90)),
            break_glass_lookback_days=int(payload.get("break_glass_lookback_days", 90)),
            role_change_lookback_days=int(payload.get("role_change_lookback_days", 90)),
            owner_admin_allowlist=list(payload.get("owner_admin_allowlist", []) or []),
            owner_admin_allowlist_by_org=dict(payload.get("owner_admin_allowlist_by_org", {}) or {}),
            mfa_required=payload.get("mfa_required"),
            mfa_required_roles=list(payload.get("mfa_required_roles") or []) or None,
        )


def _normalize_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    return cleaned or None


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_mfa_required(config: AccessReviewConfig) -> tuple[bool, list[str]]:
    mfa_required = settings.admin_mfa_required if config.mfa_required is None else bool(config.mfa_required)
    roles = (
        config.mfa_required_roles
        if config.mfa_required_roles is not None
        else settings.admin_mfa_required_roles
    )
    normalized_roles = [role.strip().lower() for role in roles if role]
    return mfa_required, normalized_roles


def _allowlist_for_org(config: AccessReviewConfig, org_id: uuid.UUID) -> list[str]:
    by_org = config.owner_admin_allowlist_by_org.get(str(org_id), [])
    combined = list(by_org) + list(config.owner_admin_allowlist)
    return [entry.strip().lower() for entry in combined if entry]


def _permissions_for_membership(role_key: str, custom_permissions: list[str] | None) -> list[str]:
    permissions = iam_permissions.effective_permissions(role_key=role_key, custom_permissions=custom_permissions)
    return sorted(permissions)


def _hash_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _resolve_orgs(session: AsyncSession, scope: AccessReviewScope, org_id: uuid.UUID | None) -> list[Organization]:
    if scope == AccessReviewScope.ORG:
        resolved = org_id or settings.default_org_id
        result = await session.execute(sa.select(Organization).where(Organization.org_id == resolved))
        org = result.scalar_one_or_none()
        if not org:
            raise ValueError("Organization not found for access review scope")
        return [org]
    result = await session.execute(sa.select(Organization).order_by(Organization.org_id))
    return list(result.scalars().all())


async def _fetch_last_login_map(session: AsyncSession, org_ids: list[uuid.UUID]) -> dict[tuple[uuid.UUID, uuid.UUID], datetime]:
    if not org_ids:
        return {}
    stmt = (
        sa.select(
            SaaSSession.org_id,
            SaaSSession.user_id,
            sa.func.max(SaaSSession.created_at).label("last_login_at"),
        )
        .where(SaaSSession.org_id.in_(org_ids))
        .group_by(SaaSSession.org_id, SaaSSession.user_id)
    )
    rows = (await session.execute(stmt)).all()
    return {(row[0], row[1]): row[2] for row in rows if row[2] is not None}


async def _fetch_break_glass_usage(
    session: AsyncSession, org_ids: list[uuid.UUID], cutoff: datetime
) -> tuple[set[tuple[uuid.UUID, str]], dict[uuid.UUID, list[datetime]]]:
    if not org_ids:
        return set(), {}
    stmt = sa.select(BreakGlassSession.org_id, BreakGlassSession.actor, BreakGlassSession.created_at).where(
        BreakGlassSession.org_id.in_(org_ids),
        BreakGlassSession.created_at >= cutoff,
    )
    rows = (await session.execute(stmt)).all()
    actor_map: set[tuple[uuid.UUID, str]] = set()
    org_map: dict[uuid.UUID, list[datetime]] = {}
    for org_id, actor, created_at in rows:
        normalized_actor = _normalize_identifier(actor)
        if normalized_actor:
            actor_map.add((org_id, normalized_actor))
        org_map.setdefault(org_id, []).append(created_at)
    return actor_map, org_map


async def _fetch_role_change_events(
    session: AsyncSession, org_ids: list[uuid.UUID], cutoff: datetime
) -> dict[tuple[uuid.UUID, uuid.UUID], list[datetime]]:
    if not org_ids:
        return {}
    stmt = (
        sa.select(AdminAuditLog.org_id, AdminAuditLog.action, AdminAuditLog.created_at)
        .where(
            AdminAuditLog.org_id.in_(org_ids),
            AdminAuditLog.created_at >= cutoff,
            AdminAuditLog.action_type == "WRITE",
            AdminAuditLog.action.like("PATCH /v1/admin/iam/users/%/role%"),
        )
        .order_by(AdminAuditLog.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    events: dict[tuple[uuid.UUID, uuid.UUID], list[datetime]] = {}
    for org_id, action, created_at in rows:
        if not action:
            continue
        match = ROLE_CHANGE_ACTION_RE.match(str(action))
        if not match:
            continue
        user_id_raw = match.group("user_id")
        try:
            user_id = uuid.UUID(user_id_raw)
        except (TypeError, ValueError):
            continue
        events.setdefault((org_id, user_id), []).append(created_at)
    return events


def _build_admin_user_entry(
    *,
    membership: Membership,
    user: User,
    role_key: str,
    custom_permissions: list[str] | None,
    mfa_required: bool,
    mfa_required_roles: list[str],
    last_login_at: datetime | None,
    break_glass_recent: bool,
    role_changed_recent: bool,
) -> dict[str, Any]:
    permissions = _permissions_for_membership(role_key, custom_permissions)
    role_value = membership.role.value
    is_mfa_required = mfa_required and role_value.lower() in mfa_required_roles
    status = "active" if membership.is_active and user.is_active else "inactive"
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "status": status,
        "membership_active": membership.is_active,
        "user_active": user.is_active,
        "role": role_value,
        "role_key": role_key,
        "custom_role_id": str(membership.custom_role_id) if membership.custom_role_id else None,
        "permissions": permissions,
        "mfa_enabled": bool(user.totp_enabled),
        "mfa_required": is_mfa_required,
        "last_login_at": _serialize_dt(last_login_at),
        "break_glass_recent": break_glass_recent,
        "role_changed_recent": role_changed_recent,
    }


def _add_anomaly(anomalies: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    anomalies.append(payload)


def _build_inactive_anomaly(
    *,
    org_id: uuid.UUID,
    user_entry: dict[str, Any],
    last_login_at: datetime | None,
    cutoff: datetime,
    inactive_days: int,
) -> dict[str, Any]:
    return {
        "rule": "inactive_admin_account",
        "severity": "medium",
        "org_id": str(org_id),
        "user_id": user_entry["user_id"],
        "email": user_entry["email"],
        "details": {
            "inactive_days_threshold": inactive_days,
            "last_login_at": _serialize_dt(last_login_at),
            "inactive_cutoff": _serialize_dt(cutoff),
        },
    }


def _build_mfa_anomaly(*, org_id: uuid.UUID, user_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule": "mfa_required_not_enabled",
        "severity": "high",
        "org_id": str(org_id),
        "user_id": user_entry["user_id"],
        "email": user_entry["email"],
        "details": {"role": user_entry["role"]},
    }


def _build_owner_admin_anomaly(*, org_id: uuid.UUID, user_entry: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "rule": "owner_admin_role_unexpected",
        "severity": "high",
        "org_id": str(org_id),
        "user_id": user_entry["user_id"],
        "email": user_entry["email"],
        "details": {"role": user_entry["role"], "reason": reason},
    }


def _build_role_change_anomaly(*, org_id: uuid.UUID, user_entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule": "recent_role_change",
        "severity": "medium",
        "org_id": str(org_id),
        "user_id": user_entry["user_id"],
        "email": user_entry["email"],
        "details": {"role": user_entry["role"]},
    }


def _build_break_glass_anomaly(*, org_id: uuid.UUID, last_used: datetime | None, count: int) -> dict[str, Any]:
    return {
        "rule": "break_glass_recent_use",
        "severity": "high",
        "org_id": str(org_id),
        "user_id": None,
        "email": None,
        "details": {
            "break_glass_sessions_recent": count,
            "last_used_at": _serialize_dt(last_used),
        },
    }


async def build_access_review_snapshot(
    session: AsyncSession,
    *,
    scope: AccessReviewScope,
    org_id: uuid.UUID | None,
    as_of: datetime,
    config: AccessReviewConfig | None = None,
    generated_by: str | None = None,
) -> dict[str, Any]:
    resolved_config = config or AccessReviewConfig()
    orgs = await _resolve_orgs(session, scope, org_id)
    org_ids = [org.org_id for org in orgs]
    mfa_required, mfa_required_roles = _resolve_mfa_required(resolved_config)
    inactive_cutoff = as_of - timedelta(days=resolved_config.inactive_days)
    break_glass_cutoff = as_of - timedelta(days=resolved_config.break_glass_lookback_days)
    role_change_cutoff = as_of - timedelta(days=resolved_config.role_change_lookback_days)

    last_login_map = await _fetch_last_login_map(session, org_ids)
    break_glass_actor_map, break_glass_org_map = await _fetch_break_glass_usage(
        session, org_ids, break_glass_cutoff
    )
    role_change_map = await _fetch_role_change_events(session, org_ids, role_change_cutoff)

    stmt = (
        sa.select(Membership, User, IamRole)
        .join(User, User.user_id == Membership.user_id)
        .outerjoin(IamRole, IamRole.role_id == Membership.custom_role_id)
        .where(
            Membership.org_id.in_(org_ids),
            Membership.role != MembershipRole.WORKER,
        )
    )
    rows = (await session.execute(stmt)).all()

    org_data: dict[uuid.UUID, dict[str, Any]] = {
        org.org_id: {
            "org_id": str(org.org_id),
            "org_name": org.name,
            "admin_users": [],
            "anomalies": [],
        }
        for org in orgs
    }

    for membership, user, role_record in rows:
        role_key = role_record.role_key if role_record else membership.role.value
        custom_permissions = role_record.permissions if role_record else None
        last_login = last_login_map.get((membership.org_id, user.user_id))
        actor_key = _normalize_identifier(user.email)
        break_glass_recent = False
        if actor_key and (membership.org_id, actor_key) in break_glass_actor_map:
            break_glass_recent = True
        role_changed_recent = (membership.org_id, user.user_id) in role_change_map

        user_entry = _build_admin_user_entry(
            membership=membership,
            user=user,
            role_key=role_key,
            custom_permissions=custom_permissions,
            mfa_required=mfa_required,
            mfa_required_roles=mfa_required_roles,
            last_login_at=last_login,
            break_glass_recent=break_glass_recent,
            role_changed_recent=role_changed_recent,
        )

        org_entry = org_data[membership.org_id]
        org_entry["admin_users"].append(user_entry)

    for org_id_value, org_entry in org_data.items():
        allowlist = _allowlist_for_org(resolved_config, org_id_value)
        allowlist_set = {entry.strip().lower() for entry in allowlist if entry}
        allowlist_configured = bool(allowlist_set)
        admin_users = org_entry["admin_users"]
        anomalies: list[dict[str, Any]] = []

        for user_entry in admin_users:
            last_login = None
            if user_entry["last_login_at"]:
                last_login = datetime.fromisoformat(user_entry["last_login_at"].replace("Z", "+00:00"))
            if last_login is None or last_login < inactive_cutoff:
                _add_anomaly(
                    anomalies,
                    _build_inactive_anomaly(
                        org_id=org_id_value,
                        user_entry=user_entry,
                        last_login_at=last_login,
                        cutoff=inactive_cutoff,
                        inactive_days=resolved_config.inactive_days,
                    ),
                )

            if user_entry["mfa_required"] and not user_entry["mfa_enabled"]:
                _add_anomaly(anomalies, _build_mfa_anomaly(org_id=org_id_value, user_entry=user_entry))

            if user_entry["role"] in {"owner", "admin"}:
                identifier = _normalize_identifier(user_entry["email"])
                user_id = _normalize_identifier(user_entry["user_id"])
                in_allowlist = identifier in allowlist_set or user_id in allowlist_set
                if not in_allowlist:
                    reason = "owner/admin allowlist not configured" if not allowlist_configured else "not in allowlist"
                    _add_anomaly(
                        anomalies,
                        _build_owner_admin_anomaly(
                            org_id=org_id_value, user_entry=user_entry, reason=reason
                        ),
                    )

            if user_entry["role_changed_recent"]:
                _add_anomaly(anomalies, _build_role_change_anomaly(org_id=org_id_value, user_entry=user_entry))

        break_glass_events = break_glass_org_map.get(org_id_value, [])
        if break_glass_events:
            last_used = max(break_glass_events)
            _add_anomaly(
                anomalies,
                _build_break_glass_anomaly(
                    org_id=org_id_value,
                    last_used=last_used,
                    count=len(break_glass_events),
                ),
            )

        admin_users.sort(key=lambda entry: (entry["email"].lower(), entry["user_id"]))
        anomalies.sort(key=lambda entry: (entry["rule"], entry.get("email") or "", entry.get("user_id") or ""))
        org_entry["anomalies"] = anomalies

    org_list = [org_data[org.org_id] for org in orgs]
    org_list.sort(key=lambda entry: entry["org_id"])

    org_id_payload = str(orgs[0].org_id) if scope == AccessReviewScope.ORG else None
    base_payload = {
        "schema_version": "v1",
        "scope": scope.value,
        "org_id": org_id_payload,
        "generated_at": _serialize_dt(as_of),
        "as_of": _serialize_dt(as_of),
        "generated_by": generated_by,
        "config": {
            "inactive_days": resolved_config.inactive_days,
            "break_glass_lookback_days": resolved_config.break_glass_lookback_days,
            "role_change_lookback_days": resolved_config.role_change_lookback_days,
            "mfa_required": mfa_required,
            "mfa_required_roles": mfa_required_roles,
            "owner_admin_allowlist": sorted({entry.strip().lower() for entry in resolved_config.owner_admin_allowlist}),
            "owner_admin_allowlist_by_org": {
                key: sorted({item.strip().lower() for item in value})
                for key, value in resolved_config.owner_admin_allowlist_by_org.items()
            },
        },
        "orgs": org_list,
    }

    summary = {
        "org_count": len(org_list),
        "admin_user_count": sum(len(org_entry["admin_users"]) for org_entry in org_list),
        "anomaly_count": sum(len(org_entry["anomalies"]) for org_entry in org_list),
    }
    base_payload["summary"] = summary
    artifact_hash = _hash_payload(base_payload)
    base_payload["artifact_hash"] = artifact_hash

    return base_payload


def render_json(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True)


def _render_permissions(permissions: Iterable[str]) -> str:
    return ", ".join(sorted(permissions)) if permissions else "-"


def render_markdown(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Quarterly Access Review Snapshot")
    lines.append("")
    lines.append(f"Generated at: {snapshot.get('generated_at')}")
    lines.append(f"Scope: {snapshot.get('scope')}")
    if snapshot.get("org_id"):
        lines.append(f"Org ID: {snapshot.get('org_id')}")
    lines.append(f"Artifact hash: {snapshot.get('artifact_hash')}")
    lines.append("")

    config = snapshot.get("config", {})
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"* Inactive threshold: {config.get('inactive_days')} days")
    lines.append(f"* Break-glass lookback: {config.get('break_glass_lookback_days')} days")
    lines.append(f"* Role change lookback: {config.get('role_change_lookback_days')} days")
    lines.append(f"* MFA required: {config.get('mfa_required')}")
    lines.append(f"* MFA roles: {', '.join(config.get('mfa_required_roles', [])) or 'none'}")
    lines.append("")

    summary = snapshot.get("summary", {})
    lines.append("## Summary")
    lines.append("")
    lines.append(f"* Orgs reviewed: {summary.get('org_count')}")
    lines.append(f"* Admin users reviewed: {summary.get('admin_user_count')}")
    lines.append(f"* Anomalies detected: {summary.get('anomaly_count')}")
    lines.append("")

    for org_entry in snapshot.get("orgs", []):
        lines.append(f"## Organization {org_entry.get('org_name')} ({org_entry.get('org_id')})")
        lines.append("")
        lines.append("### Admin Users")
        lines.append("")
        lines.append(
            "| Email | Status | Role | Role Key | MFA | Last Login | Break-glass | Role Change | Permissions |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
        )
        for user_entry in org_entry.get("admin_users", []):
            mfa_status = "enabled" if user_entry.get("mfa_enabled") else "disabled"
            if user_entry.get("mfa_required"):
                mfa_status = f"required ({mfa_status})"
            lines.append(
                "| {email} | {status} | {role} | {role_key} | {mfa} | {last_login} | {break_glass} | {role_change} | {permissions} |".format(
                    email=user_entry.get("email"),
                    status=user_entry.get("status"),
                    role=user_entry.get("role"),
                    role_key=user_entry.get("role_key"),
                    mfa=mfa_status,
                    last_login=user_entry.get("last_login_at") or "-",
                    break_glass="yes" if user_entry.get("break_glass_recent") else "no",
                    role_change="yes" if user_entry.get("role_changed_recent") else "no",
                    permissions=_render_permissions(user_entry.get("permissions", [])),
                )
            )
        lines.append("")

        lines.append("### Anomalies")
        lines.append("")
        anomalies = org_entry.get("anomalies", [])
        if not anomalies:
            lines.append("No anomalies detected.")
            lines.append("")
            continue
        lines.append("| Rule | Severity | User | Details |")
        lines.append("| --- | --- | --- | --- |")
        for anomaly in anomalies:
            user_label = anomaly.get("email") or "(org-level)"
            details = json.dumps(anomaly.get("details", {}), sort_keys=True)
            lines.append(
                f"| {anomaly.get('rule')} | {anomaly.get('severity')} | {user_label} | {details} |"
            )
        lines.append("")

    return "\n".join(lines)


async def store_access_review_run(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    scope: AccessReviewScope,
    generated_by: str,
    artifact_hash: str,
) -> AccessReviewRun:
    run = AccessReviewRun(
        org_id=org_id,
        scope=scope.value,
        generated_by=generated_by,
        artifact_hash=artifact_hash,
    )
    session.add(run)
    await session.commit()
    return run
