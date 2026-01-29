"""Tests for canonical admin proxy header contract."""

import hmac
import time

import pytest

from app.settings import settings


def _enable_proxy_auth(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = "test-proxy-auth-secret-at-least-32-chars"
    monkeypatch.setattr(settings, "admin_proxy_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_proxy_auth_required", True)
    monkeypatch.setattr(settings, "admin_proxy_auth_secret", secret)
    monkeypatch.setattr(settings, "legacy_basic_auth_enabled", False)
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_ips", ["testclient"])
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", [])
    monkeypatch.setattr(settings, "admin_proxy_auth_e2e_enabled", True)
    monkeypatch.setattr(settings, "admin_proxy_auth_e2e_secret", "e2e-secret")
    monkeypatch.setattr(settings, "admin_proxy_auth_e2e_ttl_seconds", 300)
    return secret


def _e2e_signature(user: str, email: str, roles: str, timestamp: str, mfa: str) -> str:
    payload = "\n".join([user, email, roles, timestamp, mfa]).encode("utf-8")
    return hmac.new(settings.admin_proxy_auth_e2e_secret.encode("utf-8"), payload, "sha256").hexdigest()


def test_proxy_headers_allow_access(unauthenticated_client, monkeypatch):
    secret = _enable_proxy_auth(monkeypatch)

    response = unauthenticated_client.get(
        "/v1/admin/profile",
        headers={
            "X-Admin-User": "admin",
            "X-Admin-Email": "admin@example.com",
            "X-Admin-Roles": "admin",
            "X-Proxy-Auth-Secret": secret,
            "X-Auth-MFA": "true",
        },
    )

    assert response.status_code == 200


def test_e2e_signature_headers_allow_access(unauthenticated_client, monkeypatch):
    secret = _enable_proxy_auth(monkeypatch)
    timestamp = str(int(time.time()))
    signature = _e2e_signature("e2e-user", "e2e@example.com", "admin", timestamp, "true")

    response = unauthenticated_client.get(
        "/v1/admin/profile",
        headers={
            "X-Proxy-Auth-Secret": secret,
            "X-Auth-MFA": "true",
            "X-E2E-Admin-User": "e2e-user",
            "X-E2E-Admin-Email": "e2e@example.com",
            "X-E2E-Admin-Roles": "admin",
            "X-E2E-Proxy-Timestamp": timestamp,
            "X-E2E-Proxy-Signature": signature,
        },
    )

    assert response.status_code == 200


def test_missing_identity_and_signature_rejected(unauthenticated_client, monkeypatch):
    secret = _enable_proxy_auth(monkeypatch)

    response = unauthenticated_client.get(
        "/v1/admin/profile",
        headers={
            "X-Proxy-Auth-Secret": secret,
            "X-Auth-MFA": "true",
        },
    )

    assert response.status_code == 401
    assert response.headers.get("X-Admin-Auth-Fail-Reason") == "proxy_auth_required"


def test_invalid_signature_rejected(unauthenticated_client, monkeypatch):
    secret = _enable_proxy_auth(monkeypatch)
    timestamp = str(int(time.time()))

    response = unauthenticated_client.get(
        "/v1/admin/profile",
        headers={
            "X-Proxy-Auth-Secret": secret,
            "X-Auth-MFA": "true",
            "X-E2E-Admin-User": "e2e-user",
            "X-E2E-Admin-Email": "e2e@example.com",
            "X-E2E-Admin-Roles": "admin",
            "X-E2E-Proxy-Timestamp": timestamp,
            "X-E2E-Proxy-Signature": "invalid",
        },
    )

    assert response.status_code == 401
    assert response.headers.get("X-Admin-Auth-Fail-Reason") == "bad_signature"


def test_mfa_missing_rejected(unauthenticated_client, monkeypatch):
    secret = _enable_proxy_auth(monkeypatch)

    response = unauthenticated_client.get(
        "/v1/admin/profile",
        headers={
            "X-Admin-User": "admin",
            "X-Admin-Email": "admin@example.com",
            "X-Admin-Roles": "admin",
            "X-Proxy-Auth-Secret": secret,
        },
    )

    assert response.status_code == 401
    assert response.headers.get("X-Admin-Auth-Fail-Reason") == "mfa_required"
