from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.break_glass.db_models import BreakGlassSession

TOOL_VERSION = "access-review-report-v2"
ROLE_CHANGE_ACTION_LIKE = "PATCH /v1/admin/iam/users/%/role%"


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2)


def _normalize_org_ids(snapshot: dict[str, Any]) -> list[uuid.UUID]:
    org_ids = [entry.get("org_id") for entry in snapshot.get("orgs", []) if entry.get("org_id")]
    if not org_ids and snapshot.get("org_id"):
        org_ids = [snapshot.get("org_id")]
    return [
        org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id))
        for org_id in org_ids
    ]


def _summarize_anomalies(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for org_entry in sorted(snapshot.get("orgs", []), key=lambda entry: entry.get("org_id") or ""):
        for anomaly in org_entry.get("anomalies", []) or []:
            findings.append(
                {
                    "org_id": org_entry.get("org_id"),
                    "org_name": org_entry.get("org_name"),
                    "rule": anomaly.get("rule"),
                    "severity": anomaly.get("severity"),
                    "email": anomaly.get("email"),
                    "details": anomaly.get("details", {}),
                }
            )
    findings.sort(
        key=lambda entry: (
            entry.get("org_id") or "",
            entry.get("rule") or "",
            entry.get("email") or "",
            json.dumps(entry.get("details", {}), sort_keys=True),
        )
    )
    return findings


async def build_audit_extract_payload(
    session: AsyncSession,
    snapshot: dict[str, Any],
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    as_of_raw = snapshot.get("as_of") or snapshot.get("generated_at")
    if not as_of_raw:
        raise ValueError("Snapshot missing as_of timestamp")
    as_of = _parse_dt(as_of_raw)
    config = snapshot.get("config", {})
    lookback_days = int(config.get("role_change_lookback_days", 0))
    break_glass_lookback_days = int(config.get("break_glass_lookback_days", 0))
    window_start = as_of - timedelta(days=lookback_days)
    break_glass_window_start = as_of - timedelta(days=break_glass_lookback_days)
    org_ids = _normalize_org_ids(snapshot)

    events: list[dict[str, Any]] = []
    break_glass_events: list[dict[str, Any]] = []
    if org_ids:
        stmt = (
            sa.select(AdminAuditLog)
            .where(
                AdminAuditLog.org_id.in_(org_ids),
                AdminAuditLog.created_at >= window_start,
                AdminAuditLog.created_at <= as_of,
                AdminAuditLog.action_type == "WRITE",
                AdminAuditLog.action.like(ROLE_CHANGE_ACTION_LIKE),
            )
            .order_by(AdminAuditLog.org_id, AdminAuditLog.created_at.desc(), AdminAuditLog.audit_id)
        )
        rows = (await session.execute(stmt)).scalars().all()

        events = [
            {
                "audit_id": row.audit_id,
                "org_id": str(row.org_id),
                "admin_id": row.admin_id,
                "actor": row.actor,
                "role": row.role,
                "action": row.action,
                "action_type": row.action_type,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "created_at": _serialize_dt(row.created_at),
            }
            for row in rows
        ]

        break_stmt = (
            sa.select(BreakGlassSession)
            .where(
                BreakGlassSession.org_id.in_(org_ids),
                BreakGlassSession.granted_at >= break_glass_window_start,
                BreakGlassSession.granted_at <= as_of,
            )
            .order_by(BreakGlassSession.org_id, BreakGlassSession.granted_at.desc())
        )
        break_rows = (await session.execute(break_stmt)).scalars().all()
        break_glass_events = [
            {
                "session_id": str(row.session_id),
                "org_id": str(row.org_id),
                "actor_id": row.actor_id,
                "actor": row.actor,
                "reason": row.reason,
                "incident_ref": row.incident_ref,
                "scope": row.scope,
                "status": row.status,
                "granted_at": _serialize_dt(row.granted_at),
                "expires_at": _serialize_dt(row.expires_at),
                "revoked_at": _serialize_dt(row.revoked_at) if row.revoked_at else None,
                "reviewed_at": _serialize_dt(row.reviewed_at) if row.reviewed_at else None,
                "reviewed_by": row.reviewed_by,
                "review_notes": row.review_notes,
            }
            for row in break_rows
        ]

    return {
        "generated_at": _serialize_dt(generated_at),
        "scope": snapshot.get("scope"),
        "org_ids": sorted({str(org_id) for org_id in org_ids}),
        "as_of": _serialize_dt(as_of),
        "window_start": _serialize_dt(window_start),
        "window_end": _serialize_dt(as_of),
        "event_count": len(events),
        "events": events,
        "break_glass_window_start": _serialize_dt(break_glass_window_start),
        "break_glass_event_count": len(break_glass_events),
        "break_glass_events": break_glass_events,
    }


def build_report_markdown(snapshot: dict[str, Any], audit_extract: dict[str, Any]) -> str:
    summary = snapshot.get("summary", {})
    findings = _summarize_anomalies(snapshot)

    lines: list[str] = []
    lines.append("# Quarterly Access Review Evidence Package")
    lines.append("")
    lines.append(f"Generated at: {audit_extract.get('generated_at')}")
    lines.append(f"Snapshot as of: {snapshot.get('as_of')}")
    lines.append(f"Scope: {snapshot.get('scope')}")
    if snapshot.get("org_id"):
        lines.append(f"Org ID: {snapshot.get('org_id')}")
    lines.append(f"Snapshot artifact hash: {snapshot.get('artifact_hash')}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"* Orgs reviewed: {summary.get('org_count')}")
    lines.append(f"* Admin users reviewed: {summary.get('admin_user_count')}")
    lines.append(f"* Anomalies detected: {summary.get('anomaly_count')}")
    lines.append(f"* Role change events (audit extract): {audit_extract.get('event_count')}")
    lines.append(f"* Break-glass events (audit extract): {audit_extract.get('break_glass_event_count')}")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not findings:
        lines.append("No anomalies detected.")
    else:
        lines.append("| Org | Rule | Severity | User | Details |")
        lines.append("| --- | --- | --- | --- | --- |")
        for entry in findings:
            details = json.dumps(entry.get("details", {}), sort_keys=True)
            user_label = entry.get("email") or "(org-level)"
            org_label = entry.get("org_name") or entry.get("org_id") or "-"
            lines.append(
                f"| {org_label} | {entry.get('rule')} | {entry.get('severity')} | {user_label} | {details} |"
            )
    lines.append("")

    lines.append("## Remediation Checklist")
    lines.append("")
    lines.append("- [ ] Review each anomaly and document remediation in the review tracker.")
    lines.append("- [ ] Disable or remove inactive admin accounts beyond the threshold.")
    lines.append("- [ ] Enforce MFA for roles that require it.")
    lines.append("- [ ] Validate owner/admin role assignments against the allowlist.")
    lines.append("- [ ] Confirm break-glass and role change events were authorized and documented.")
    lines.append("")

    lines.append("## Reviewer Checklist")
    lines.append("")
    lines.append("- [ ] Snapshot JSON reviewed and stored in the evidence bundle.")
    lines.append("- [ ] Audit extract matches the role-change lookback window.")
    lines.append("- [ ] Checksums verified against checksums.txt.")
    lines.append("- [ ] Evidence bundle archived per retention policy.")
    lines.append("")

    lines.append("## Evidence Bundle Contents")
    lines.append("")
    lines.append("- report.md")
    lines.append("- snapshot.json")
    lines.append("- audit_extract.json")
    lines.append("- metadata.json")
    lines.append("- checksums.txt (includes per-file hashes + manifest hash)")

    return "\n".join(lines)


def _build_checksums(entries: dict[str, str]) -> tuple[str, str]:
    ordered = [f"{entries[name]}  {name}" for name in sorted(entries.keys())]
    manifest_hash = _sha256_bytes("\n".join(ordered).encode("utf-8"))
    content = "\n".join(ordered)
    content += f"\n# manifest_sha256: {manifest_hash}\n"
    return content, manifest_hash


def write_evidence_bundle(
    bundle_dir: Path,
    *,
    snapshot: dict[str, Any],
    audit_extract: dict[str, Any],
    generated_at: datetime,
    tool_version: str = TOOL_VERSION,
    signed_by: str | None = None,
) -> dict[str, Any]:
    bundle_dir.mkdir(parents=True, exist_ok=True)

    report_md = build_report_markdown(snapshot, audit_extract)
    snapshot_json = _stable_json(snapshot)
    audit_json = _stable_json(audit_extract)

    config = snapshot.get("config", {}) or {}
    metadata = {
        "generated_at": _serialize_dt(generated_at),
        "scope": snapshot.get("scope"),
        "org_id": snapshot.get("org_id"),
        "as_of": snapshot.get("as_of"),
        "tool_version": tool_version,
        "snapshot_artifact_hash": snapshot.get("artifact_hash"),
        "config": {
            "inactive_days": config.get("inactive_days"),
            "break_glass_lookback_days": config.get("break_glass_lookback_days"),
            "role_change_lookback_days": config.get("role_change_lookback_days"),
            "mfa_required": config.get("mfa_required"),
            "mfa_required_roles": config.get("mfa_required_roles"),
        },
    }
    if signed_by:
        metadata["signed_by"] = signed_by

    (bundle_dir / "report.md").write_text(report_md, encoding="utf-8")
    (bundle_dir / "snapshot.json").write_text(snapshot_json, encoding="utf-8")
    (bundle_dir / "audit_extract.json").write_text(audit_json, encoding="utf-8")
    (bundle_dir / "metadata.json").write_text(_stable_json(metadata), encoding="utf-8")

    files = ["report.md", "snapshot.json", "audit_extract.json", "metadata.json"]
    checksums = {name: _sha256_file(bundle_dir / name) for name in files}
    checksums_text, manifest_hash = _build_checksums(checksums)
    (bundle_dir / "checksums.txt").write_text(checksums_text, encoding="utf-8")

    return {
        "bundle_dir": str(bundle_dir),
        "checksums": checksums,
        "manifest_hash": manifest_hash,
    }
