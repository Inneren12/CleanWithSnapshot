import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.access_review import service as access_review
from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.break_glass.db_models import BreakGlassSession
from app.domain.iam.db_models import IamRole
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole, Organization, SaaSSession
from app.settings import settings


@pytest.mark.anyio
async def test_access_review_snapshot_deterministic(async_session_maker):
    settings.admin_mfa_required = True
    settings.admin_mfa_required_roles = ["owner", "admin"]
    fixed_now = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
    config = access_review.AccessReviewConfig(
        inactive_days=90,
        break_glass_lookback_days=90,
        role_change_lookback_days=90,
        owner_admin_allowlist=["owner@example.com"],
    )

    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Deterministic Org")
        owner = await saas_service.create_user(session, "owner@example.com", "SecretPass123!")
        await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)

        custom_role = IamRole(
            org_id=org.org_id,
            role_key="custom-admin",
            name="Custom Admin",
            description="Custom role",
            permissions=["core.view", "users.manage"],
        )
        session.add(custom_role)
        await session.flush()

        admin = await saas_service.create_user(session, "admin@example.com", "SecretPass123!")
        membership = await saas_service.create_membership(session, org, admin, MembershipRole.ADMIN)
        membership.custom_role_id = custom_role.role_id

        session.add(
            SaaSSession(
                session_id=uuid.uuid4(),
                user_id=admin.user_id,
                org_id=org.org_id,
                role=MembershipRole.ADMIN,
                refresh_token_hash="hash",
                created_at=fixed_now - timedelta(days=1),
                expires_at=fixed_now + timedelta(days=1),
                refresh_expires_at=fixed_now + timedelta(days=2),
                mfa_verified=True,
            )
        )

        await session.commit()

        snapshot_one = await access_review.build_access_review_snapshot(
            session,
            scope=access_review.AccessReviewScope.ORG,
            org_id=org.org_id,
            as_of=fixed_now,
            config=config,
            generated_by="tester",
        )
        snapshot_two = await access_review.build_access_review_snapshot(
            session,
            scope=access_review.AccessReviewScope.ORG,
            org_id=org.org_id,
            as_of=fixed_now,
            config=config,
            generated_by="tester",
        )

    assert snapshot_one == snapshot_two


@pytest.mark.anyio
async def test_access_review_anomalies_and_no_sensitive_data(async_session_maker):
    settings.admin_mfa_required = True
    settings.admin_mfa_required_roles = ["owner", "admin"]
    fixed_now = datetime(2024, 2, 1, 12, 0, tzinfo=timezone.utc)
    config = access_review.AccessReviewConfig(
        inactive_days=30,
        break_glass_lookback_days=90,
        role_change_lookback_days=90,
    )

    async with async_session_maker() as session:
        org = Organization(org_id=uuid.uuid4(), name="Anomaly Org")
        session.add(org)
        user = await saas_service.create_user(session, "anomaly-owner@example.com", "SecretPass123!")
        membership = await saas_service.create_membership(session, org, user, MembershipRole.OWNER)

        session.add(
            SaaSSession(
                session_id=uuid.uuid4(),
                user_id=user.user_id,
                org_id=org.org_id,
                role=MembershipRole.OWNER,
                refresh_token_hash="hash",
                created_at=fixed_now - timedelta(days=60),
                expires_at=fixed_now + timedelta(days=1),
                refresh_expires_at=fixed_now + timedelta(days=2),
                mfa_verified=False,
            )
        )

        session.add(
            BreakGlassSession(
                session_id=uuid.uuid4(),
                org_id=org.org_id,
                actor=user.email,
                reason="incident",
                token_hash="hash",
                expires_at=fixed_now + timedelta(days=1),
                created_at=fixed_now - timedelta(days=10),
            )
        )

        session.add(
            AdminAuditLog(
                audit_id=str(uuid.uuid4()),
                org_id=org.org_id,
                admin_id=str(user.user_id),
                action=f"PATCH /v1/admin/iam/users/{user.user_id}/role",
                action_type="WRITE",
                sensitivity_level="normal",
                actor=user.email,
                role="owner",
                auth_method="token",
                resource_type=None,
                resource_id=None,
                context=None,
                before=None,
                after=None,
                created_at=fixed_now - timedelta(days=5),
            )
        )

        await session.commit()

        snapshot = await access_review.build_access_review_snapshot(
            session,
            scope=access_review.AccessReviewScope.ORG,
            org_id=org.org_id,
            as_of=fixed_now,
            config=config,
            generated_by="tester",
        )

    anomalies = snapshot["orgs"][0]["anomalies"]
    rules = {entry["rule"] for entry in anomalies}
    assert "inactive_admin_account" in rules
    assert "mfa_required_not_enabled" in rules
    assert "owner_admin_role_unexpected" in rules
    assert "break_glass_recent_use" in rules
    assert "recent_role_change" in rules

    snapshot_json = access_review.render_json(snapshot)
    assert "password_hash" not in snapshot_json
    assert "totp_secret_base32" not in snapshot_json
    assert "refresh_token_hash" not in snapshot_json
    assert "token_hash" not in snapshot_json
