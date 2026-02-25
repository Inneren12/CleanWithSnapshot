import uuid

import pytest
import sqlalchemy as sa

from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole, Organization, User
from app.settings import settings


@pytest.mark.anyio
async def test_enroll_and_verify_enables_totp(async_session_maker, client):
    settings.admin_mfa_required = True
    async with async_session_maker() as session:
        org = Organization(org_id=uuid.uuid4(), name="MFA Org")
        user = await saas_service.create_user(session, "mfa@example.com", "SecretPass123!")
        await saas_service.create_membership(session, org, user, MembershipRole.OWNER)
        await session.commit()

    login = client.post(
        "/v1/auth/login",
        json={"email": "mfa@example.com", "password": "SecretPass123!", "org_id": str(org.org_id)},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    enroll = client.post("/v1/auth/2fa/enroll", headers={"Authorization": f"Bearer {token}"})
    assert enroll.status_code == 200
    payload = enroll.json()
    assert isinstance(payload["backup_codes"], list)
    assert payload["backup_codes"]
    secret = payload["secret"]
    code = saas_service.generate_totp_code(secret)

    verify = client.post(
        "/v1/auth/2fa/verify",
        json={"code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert verify.status_code == 200

    async with async_session_maker() as session:
        db_user = await session.scalar(sa.select(User).where(User.email == "mfa@example.com"))
        assert db_user
        assert db_user.totp_enabled is True
        assert db_user.totp_secret_base32 == secret


@pytest.mark.anyio
async def test_admin_login_requires_mfa_code_and_allows_admin_routes(async_session_maker, client):
    settings.admin_mfa_required = True
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Admin MFA Org")
        user = await saas_service.create_user(session, "admin-mfa@example.com", "SecretPass123!")
        await saas_service.create_membership(session, org, user, MembershipRole.ADMIN)
        await session.commit()

    login = client.post(
        "/v1/auth/login",
        json={"email": "admin-mfa@example.com", "password": "SecretPass123!", "org_id": str(org.org_id)},
    )
    token = login.json()["access_token"]
    enroll = client.post("/v1/auth/2fa/enroll", headers={"Authorization": f"Bearer {token}"})
    secret = enroll.json()["secret"]
    code = saas_service.generate_totp_code(secret)
    verify = client.post(
        "/v1/auth/2fa/verify",
        json={"code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert verify.status_code == 200

    missing_code = client.post(
        "/v1/auth/login",
        json={"email": "admin-mfa@example.com", "password": "SecretPass123!", "org_id": str(org.org_id)},
    )
    assert missing_code.status_code == 401
    assert missing_code.json()["type"] == "mfa_required"

    correct_code = client.post(
        "/v1/auth/login",
        json={
            "email": "admin-mfa@example.com",
            "password": "SecretPass123!",
            "org_id": str(org.org_id),
            "mfa_code": saas_service.generate_totp_code(secret),
        },
    )
    assert correct_code.status_code == 200
    access_token = correct_code.json()["access_token"]
    assert correct_code.json()["mfa_verified"] is True

    iam_resp = client.get("/v1/iam/users", headers={"Authorization": f"Bearer {access_token}"})
    assert iam_resp.status_code == 200


@pytest.mark.anyio
async def test_wrong_mfa_code_rejected(async_session_maker, client):
    settings.admin_mfa_required = True
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Wrong MFA Org")
        user = await saas_service.create_user(session, "wrong-mfa@example.com", "SecretPass123!")
        await saas_service.create_membership(session, org, user, MembershipRole.OWNER)
        await session.commit()

    token = client.post(
        "/v1/auth/login",
        json={"email": "wrong-mfa@example.com", "password": "SecretPass123!", "org_id": str(org.org_id)},
    ).json()["access_token"]

    enroll = client.post("/v1/auth/2fa/enroll", headers={"Authorization": f"Bearer {token}"})
    secret = enroll.json()["secret"]
    client.post(
        "/v1/auth/2fa/verify",
        json={"code": saas_service.generate_totp_code(secret)},
        headers={"Authorization": f"Bearer {token}"},
    )

    wrong_login = client.post(
        "/v1/auth/login",
        json={
            "email": "wrong-mfa@example.com",
            "password": "SecretPass123!",
            "org_id": str(org.org_id),
            "mfa_code": "123456",
        },
    )
    assert wrong_login.status_code == 401
    assert wrong_login.json()["type"] == "mfa_required"


@pytest.mark.anyio
async def test_non_admin_roles_not_blocked(async_session_maker, client):
    settings.admin_mfa_required = True
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Viewer Org")
        user = await saas_service.create_user(session, "viewer@example.com", "SecretPass123!")
        membership = await saas_service.create_membership(session, org, user, MembershipRole.VIEWER)
        user.totp_secret_base32 = saas_service.generate_totp_secret()
        user.totp_enabled = True
        session.add_all([user, membership])
        await session.commit()

    login = client.post(
        "/v1/auth/login",
        json={"email": "viewer@example.com", "password": "SecretPass123!", "org_id": str(org.org_id)},
    )
    assert login.status_code == 200
    assert login.json()["mfa_verified"] is False


@pytest.mark.anyio
async def test_admin_routes_reject_sessions_without_mfa(async_session_maker, client):
    settings.admin_mfa_required = True
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "MFA Gate Org")
        user = await saas_service.create_user(session, "mfa-gate@example.com", "SecretPass123!")
        membership = await saas_service.create_membership(session, org, user, MembershipRole.ADMIN)
        user.totp_secret_base32 = saas_service.generate_totp_secret()
        user.totp_enabled = True
        session.add_all([user, membership])
        session_token, _ = await saas_service.create_session(
            session,
            user,
            membership,
            ttl_minutes=settings.auth_session_ttl_minutes,
            refresh_ttl_minutes=settings.auth_refresh_token_ttl_minutes,
            mfa_verified=False,
        )
        mfa_session, _ = await saas_service.create_session(
            session,
            user,
            membership,
            ttl_minutes=settings.auth_session_ttl_minutes,
            refresh_ttl_minutes=settings.auth_refresh_token_ttl_minutes,
            mfa_verified=True,
        )
        await session.commit()

    access_token_without_mfa = saas_service.build_session_access_token(
        user, membership, session_token.session_id, mfa_verified=False
    )
    access_token_with_mfa = saas_service.build_session_access_token(
        user, membership, mfa_session.session_id, mfa_verified=True
    )

    iam_resp = client.get(
        "/v1/iam/users", headers={"Authorization": f"Bearer {access_token_without_mfa}"}
    )
    assert iam_resp.status_code == 401
    assert iam_resp.headers["content-type"].startswith("application/problem+json")
    assert iam_resp.json()["type"] == "mfa_required"

    admin_resp = client.get(
        "/v1/admin/profile", headers={"Authorization": f"Bearer {access_token_without_mfa}"}
    )
    assert admin_resp.status_code == 401
    assert admin_resp.headers["content-type"].startswith("application/problem+json")
    assert admin_resp.json()["type"] == "mfa_required"

    success_resp = client.get(
        "/v1/iam/users", headers={"Authorization": f"Bearer {access_token_with_mfa}"}
    )
    assert success_resp.status_code == 200


@pytest.mark.anyio
async def test_regenerate_backup_codes_requires_totp_enabled(async_session_maker, client):
    settings.admin_mfa_required = True
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "No TOTP Org")
        user = await saas_service.create_user(session, "no-totp@example.com", "SecretPass123!")
        await saas_service.create_membership(session, org, user, MembershipRole.OWNER)
        await session.commit()

    token = client.post(
        "/v1/auth/login",
        json={"email": "no-totp@example.com", "password": "SecretPass123!", "org_id": str(org.org_id)},
    ).json()["access_token"]

    response = client.post(
        "/v1/auth/2fa/backup-codes/regenerate",
        json={"code": "123456"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "MFA not enrolled"


@pytest.mark.anyio
async def test_regenerate_backup_codes_rejects_invalid_code(async_session_maker, client):
    settings.admin_mfa_required = True
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Invalid Code Org")
        user = await saas_service.create_user(session, "invalid-code@example.com", "SecretPass123!")
        await saas_service.create_membership(session, org, user, MembershipRole.ADMIN)
        await session.commit()

    token = client.post(
        "/v1/auth/login",
        json={"email": "invalid-code@example.com", "password": "SecretPass123!", "org_id": str(org.org_id)},
    ).json()["access_token"]

    enroll = client.post("/v1/auth/2fa/enroll", headers={"Authorization": f"Bearer {token}"})
    assert enroll.status_code == 200
    secret = enroll.json()["secret"]

    verify = client.post(
        "/v1/auth/2fa/verify",
        json={"code": saas_service.generate_totp_code(secret)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert verify.status_code == 200

    refreshed_token = client.post(
        "/v1/auth/login",
        json={
            "email": "invalid-code@example.com",
            "password": "SecretPass123!",
            "org_id": str(org.org_id),
            "mfa_code": saas_service.generate_totp_code(secret),
        },
    ).json()["access_token"]

    response = client.post(
        "/v1/auth/2fa/backup-codes/regenerate",
        json={"code": "123456"},
        headers={"Authorization": f"Bearer {refreshed_token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid MFA code"


@pytest.mark.anyio
async def test_regenerate_backup_codes_forbidden_for_non_admin(async_session_maker, client):
    settings.admin_mfa_required = True
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Viewer Regen Org")
        user = await saas_service.create_user(session, "viewer-regen@example.com", "SecretPass123!")
        await saas_service.create_membership(session, org, user, MembershipRole.VIEWER)
        await session.commit()

    token = client.post(
        "/v1/auth/login",
        json={"email": "viewer-regen@example.com", "password": "SecretPass123!", "org_id": str(org.org_id)},
    ).json()["access_token"]

    response = client.post(
        "/v1/auth/2fa/backup-codes/regenerate",
        json={"code": "123456"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_regenerate_backup_codes_rotates_codes(async_session_maker, client):
    settings.admin_mfa_required = True
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Regen Success Org")
        user = await saas_service.create_user(session, "regen-success@example.com", "SecretPass123!")
        await saas_service.create_membership(session, org, user, MembershipRole.OWNER)
        await session.commit()

    token = client.post(
        "/v1/auth/login",
        json={"email": "regen-success@example.com", "password": "SecretPass123!", "org_id": str(org.org_id)},
    ).json()["access_token"]

    enroll = client.post("/v1/auth/2fa/enroll", headers={"Authorization": f"Bearer {token}"})
    assert enroll.status_code == 200
    payload = enroll.json()
    original_backup_codes = payload["backup_codes"]
    secret = payload["secret"]

    verify = client.post(
        "/v1/auth/2fa/verify",
        json={"code": saas_service.generate_totp_code(secret)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert verify.status_code == 200

    refreshed_token = client.post(
        "/v1/auth/login",
        json={
            "email": "regen-success@example.com",
            "password": "SecretPass123!",
            "org_id": str(org.org_id),
            "mfa_code": saas_service.generate_totp_code(secret),
        },
    ).json()["access_token"]

    regenerate = client.post(
        "/v1/auth/2fa/backup-codes/regenerate",
        json={"code": original_backup_codes[0]},
        headers={"Authorization": f"Bearer {refreshed_token}"},
    )
    assert regenerate.status_code == 200
    new_codes = regenerate.json()["backup_codes"]
    assert new_codes

    post_regen_token = client.post(
        "/v1/auth/login",
        json={
            "email": "regen-success@example.com",
            "password": "SecretPass123!",
            "org_id": str(org.org_id),
            "mfa_code": saas_service.generate_totp_code(secret),
        },
    ).json()["access_token"]

    old_code_after_regen = client.post(
        "/v1/auth/2fa/verify",
        json={"code": original_backup_codes[1]},
        headers={"Authorization": f"Bearer {post_regen_token}"},
    )
    assert old_code_after_regen.status_code == 401
    assert old_code_after_regen.json()["detail"] == "Invalid MFA code"



def test_basic_auth_mfa_header_required_outside_testing(unauthenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "legacy_basic_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_basic_username", "admin")
    monkeypatch.setattr(settings, "admin_basic_password", "admin123")

    missing_header = unauthenticated_client.get("/v1/admin/profile", auth=("admin", "admin123"))
    assert missing_header.status_code == 401
    assert missing_header.headers.get("X-Admin-Auth-Fail-Reason") == "mfa_required"

    with_header = unauthenticated_client.get(
        "/v1/admin/profile",
        auth=("admin", "admin123"),
        headers={"X-Auth-MFA": "true"},
    )
    assert with_header.status_code == 200

    monkeypatch.setattr(settings, "testing", True)
    bypass = unauthenticated_client.get("/v1/admin/profile", auth=("admin", "admin123"))
    assert bypass.status_code == 200
