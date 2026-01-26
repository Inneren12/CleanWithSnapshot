import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.access_review import reporting as access_review_reporting
from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole, Organization


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _parse_checksums(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        digest, name = line.split(maxsplit=1)
        entries[name.strip()] = digest
    return entries


def _extract_manifest_hash(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# manifest_sha256:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("manifest hash missing")


def _build_snapshot() -> dict:
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    return {
        "schema_version": "v1",
        "scope": "org",
        "org_id": org_id,
        "generated_at": "2024-03-31T23:59:59Z",
        "as_of": "2024-03-31T23:59:59Z",
        "generated_by": "reviewer@example.com",
        "config": {
            "inactive_days": 90,
            "break_glass_lookback_days": 90,
            "role_change_lookback_days": 90,
            "mfa_required": True,
            "mfa_required_roles": ["owner", "admin"],
        },
        "summary": {"org_count": 1, "admin_user_count": 1, "anomaly_count": 1},
        "orgs": [
            {
                "org_id": org_id,
                "org_name": "Evidence Org",
                "admin_users": [
                    {
                        "user_id": user_id,
                        "email": "admin@example.com",
                        "status": "active",
                        "membership_active": True,
                        "user_active": True,
                        "role": "admin",
                        "role_key": "admin",
                        "custom_role_id": None,
                        "permissions": ["core.view"],
                        "mfa_enabled": True,
                        "mfa_required": True,
                        "last_login_at": "2024-03-30T10:00:00Z",
                        "break_glass_recent": False,
                        "role_changed_recent": False,
                    }
                ],
                "anomalies": [
                    {
                        "rule": "mfa_required_not_enabled",
                        "severity": "high",
                        "org_id": org_id,
                        "user_id": user_id,
                        "email": "admin@example.com",
                        "details": {"mfa_enabled": False},
                    }
                ],
            }
        ],
        "artifact_hash": "snapshot-hash",
    }


def _build_audit_extract(snapshot: dict) -> dict:
    return {
        "generated_at": snapshot["generated_at"],
        "scope": snapshot["scope"],
        "org_ids": [snapshot["org_id"]],
        "as_of": snapshot["as_of"],
        "window_start": "2024-01-01T00:00:00Z",
        "window_end": snapshot["as_of"],
        "event_count": 0,
        "events": [],
    }


def test_access_review_report_bundle_deterministic(tmp_path):
    snapshot = _build_snapshot()
    audit_extract = _build_audit_extract(snapshot)
    generated_at = datetime(2024, 3, 31, 23, 59, 59, tzinfo=timezone.utc)

    bundle_one = tmp_path / "bundle_one"
    bundle_two = tmp_path / "bundle_two"

    access_review_reporting.write_evidence_bundle(
        bundle_one,
        snapshot=snapshot,
        audit_extract=audit_extract,
        generated_at=generated_at,
    )
    access_review_reporting.write_evidence_bundle(
        bundle_two,
        snapshot=snapshot,
        audit_extract=audit_extract,
        generated_at=generated_at,
    )

    report_one = (bundle_one / "report.md").read_text(encoding="utf-8")
    report_two = (bundle_two / "report.md").read_text(encoding="utf-8")
    assert report_one == report_two
    assert "mfa_required_not_enabled" in report_one

    checksums_text = (bundle_one / "checksums.txt").read_text(encoding="utf-8")
    checksums = _parse_checksums(checksums_text)
    for filename, digest in checksums.items():
        file_bytes = (bundle_one / filename).read_bytes()
        assert _sha256_bytes(file_bytes) == digest

    manifest_hash = _extract_manifest_hash(checksums_text)
    ordered = "\n".join(f"{checksums[name]}  {name}" for name in sorted(checksums.keys()))
    assert _sha256_bytes(ordered.encode("utf-8")) == manifest_hash

    assert "password_hash" not in report_one
    assert "totp_secret_base32" not in report_one


@pytest.mark.anyio
async def test_access_review_report_audit_extract_minimal(async_session_maker):
    fixed_now = datetime(2024, 4, 1, 12, 0, tzinfo=timezone.utc)

    async with async_session_maker() as session:
        org = Organization(org_id=uuid.uuid4(), name="Audit Org")
        session.add(org)
        admin = await saas_service.create_user(session, "auditor@example.com", "SecretPass123!")
        await saas_service.create_membership(session, org, admin, MembershipRole.OWNER)

        session.add(
            AdminAuditLog(
                audit_id=str(uuid.uuid4()),
                org_id=org.org_id,
                admin_id=str(admin.user_id),
                action=f"PATCH /v1/admin/iam/users/{admin.user_id}/role",
                action_type="WRITE",
                sensitivity_level="normal",
                actor=admin.email,
                role="owner",
                auth_method="token",
                resource_type=None,
                resource_id=None,
                context={"secret": "should-not-appear"},
                before={"role": "admin"},
                after={"role": "owner"},
                created_at=fixed_now - timedelta(days=5),
            )
        )
        session.add(
            AdminAuditLog(
                audit_id=str(uuid.uuid4()),
                org_id=org.org_id,
                admin_id=str(admin.user_id),
                action=f"PATCH /v1/admin/iam/users/{admin.user_id}/role",
                action_type="WRITE",
                sensitivity_level="normal",
                actor=admin.email,
                role="owner",
                auth_method="token",
                resource_type=None,
                resource_id=None,
                context=None,
                before=None,
                after=None,
                created_at=fixed_now - timedelta(days=120),
            )
        )
        await session.commit()

        snapshot = {
            "scope": "org",
            "org_id": str(org.org_id),
            "as_of": fixed_now.isoformat().replace("+00:00", "Z"),
            "generated_at": fixed_now.isoformat().replace("+00:00", "Z"),
            "config": {"role_change_lookback_days": 90},
            "orgs": [{"org_id": str(org.org_id)}],
        }

        audit_extract = await access_review_reporting.build_audit_extract_payload(
            session,
            snapshot,
            generated_at=fixed_now,
        )

    assert audit_extract["event_count"] == 1
    event = audit_extract["events"][0]
    assert "context" not in json.dumps(event)
    assert event["action_type"] == "WRITE"
    assert event["org_id"] == str(org.org_id)
