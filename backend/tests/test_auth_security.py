import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.api.routes_auth import _auth_failure_reason_code
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole, Organization, SaaSSession, TokenEvent, User
from app.settings import settings


def _legacy_hash(password: str) -> str:
    salt = "legacy"
    digest = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}${digest}"


@pytest.mark.anyio
async def test_legacy_password_upgrades_and_login(async_session_maker, client):
    async with async_session_maker() as session:
        org = Organization(org_id=uuid.uuid4(), name="Legacy Org")
        user = User(email="legacy@example.com", password_hash=_legacy_hash("secret"))
        session.add_all([org, user])
        await session.flush()
        await saas_service.create_membership(session, org, user, MembershipRole.OWNER)
        await session.commit()

    response = client.post(
        "/v1/auth/login",
        json={"email": "legacy@example.com", "password": "secret", "org_id": str(org.org_id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["refresh_token"]

    async with async_session_maker() as session:
        updated = await session.scalar(sa.select(User).where(User.email == "legacy@example.com"))
        assert updated
        assert updated.password_hash.startswith("argon2id$") or updated.password_hash.startswith("bcrypt$")


@pytest.mark.anyio
async def test_wrong_password_rejected(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Wrong PW Org")
        user = await saas_service.create_user(session, "wrong@example.com", "right")
        await saas_service.create_membership(session, org, user, MembershipRole.ADMIN)
        await session.commit()

    response = client.post(
        "/v1/auth/login",
        json={"email": "wrong@example.com", "password": "nope", "org_id": str(org.org_id)},
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_refresh_rotates_session_and_invalidates_old(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Refresh Org")
        user = await saas_service.create_user(session, "refresh@example.com", "secret")
        membership = await saas_service.create_membership(session, org, user, MembershipRole.ADMIN)
        await session.commit()

    login = client.post("/v1/auth/login", json={"email": "refresh@example.com", "password": "secret", "org_id": str(org.org_id)})
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    refreshed = client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200
    new_refresh = refreshed.json()["refresh_token"]
    assert new_refresh != refresh_token

    second = client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert second.status_code == 401

    async with async_session_maker() as session:
        events = await session.scalars(sa.select(TokenEvent))
        assert events.all()


@pytest.mark.anyio
async def test_revoked_session_rejected(async_session_maker, client):
    original_legacy = settings.legacy_basic_auth_enabled
    settings.legacy_basic_auth_enabled = False
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Revoke Org")
        user = await saas_service.create_user(session, "revoke@example.com", "secret")
        membership = await saas_service.create_membership(session, org, user, MembershipRole.ADMIN)
        token_session, refresh_token = await saas_service.create_session(
            session,
            user,
            membership,
            ttl_minutes=settings.auth_session_ttl_minutes,
            refresh_ttl_minutes=settings.auth_refresh_token_ttl_minutes,
        )
        access_token = saas_service.build_session_access_token(user, membership, token_session.session_id)
        await saas_service.revoke_session(session, token_session.session_id, reason="test")
        await session.commit()

    resp = client.get("/v1/auth/org-context", headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 401
    settings.legacy_basic_auth_enabled = original_legacy


@pytest.mark.anyio
async def test_expired_session_rejected(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Expired Org")
        user = await saas_service.create_user(session, "expired@example.com", "secret")
        membership = await saas_service.create_membership(session, org, user, MembershipRole.ADMIN)
        expired_session = SaaSSession(
            session_id=uuid.uuid4(),
            user_id=user.user_id,
            org_id=org.org_id,
            role=MembershipRole.ADMIN,
            refresh_token_hash="stale",
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            refresh_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        session.add(expired_session)
        await session.commit()
        token = saas_service.build_session_access_token(user, membership, expired_session.session_id)

    resp = client.get("/v1/auth/org-context", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_login_failure_does_not_leak_email_in_response_or_logs(async_session_maker, client, caplog):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "PII Org")
        user = await saas_service.create_user(session, "pii.user@example.com", "secret")
        await saas_service.create_membership(session, org, user, MembershipRole.ADMIN)
        await session.commit()

    caplog.set_level(logging.WARNING, logger="app.api.routes_auth")
    response = client.post(
        "/v1/auth/login",
        json={"email": "pii.user@example.com", "password": "wrong-password", "org_id": str(org.org_id)},
    )

    assert response.status_code == 401
    body = response.text.lower()
    assert "pii.user@example.com" not in body
    assert "invalid credentials" in body

    full_log_text = "\n".join(
        [caplog.text] + [record.getMessage() + " " + str(record.__dict__) for record in caplog.records]
    )
    assert "pii.user@example.com" not in full_log_text

    auth_failure_records = []
    for record in caplog.records:
        if record.getMessage() != "saas_auth_failed":
            continue
        wrapper = getattr(record, "extra", None)
        payload = wrapper.get("extra") if isinstance(wrapper, dict) else None
        if isinstance(payload, dict) and payload.get("flow") == "login":
            auth_failure_records.append(payload)

    assert auth_failure_records
    auth_failure_payload = auth_failure_records[-1]
    assert auth_failure_payload.get("failure_code") == "invalid_credentials"
    assert "failure_reason" not in auth_failure_payload
    assert "wrong-password" not in full_log_text


def test_auth_failure_reason_code_login_sanitizes_unknown_values():
    reason_code = _auth_failure_reason_code(ValueError("User not found: pii.user@example.com"), flow="login")

    assert reason_code == "invalid_credentials"
