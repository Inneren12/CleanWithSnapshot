"""Tests for MFA requirements in admin proxy authentication."""

import pytest

from app.settings import settings


def _enable_proxy_auth(monkeypatch: pytest.MonkeyPatch, *, trusted: bool = True) -> str:
    secret = "test-proxy-auth-secret-at-least-32-chars"
    monkeypatch.setattr(settings, "admin_proxy_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_proxy_auth_required", True)
    monkeypatch.setattr(settings, "admin_proxy_auth_secret", secret)
    monkeypatch.setattr(settings, "legacy_basic_auth_enabled", False)
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_ips", ["testclient"] if trusted else [])
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", [])
    monkeypatch.setattr(settings, "admin_proxy_auth_e2e_enabled", False)
    return secret


def _proxy_headers(secret: str, *, include_mfa: bool = True) -> dict[str, str]:
    headers = {
        "X-Admin-User": "admin",
        "X-Admin-Roles": "admin",
        "X-Proxy-Auth-Secret": secret,
    }
    if include_mfa:
        headers["X-Auth-MFA"] = "true"
    return headers


def test_proxy_auth_missing_mfa_header_rejected(unauthenticated_client, monkeypatch):
    secret = _enable_proxy_auth(monkeypatch, trusted=True)

    response = unauthenticated_client.get(
        "/v1/admin/profile",
        headers=_proxy_headers(secret, include_mfa=False),
    )

    assert response.status_code == 401
    assert response.headers.get("X-Admin-Auth-Fail-Reason") == "mfa_required"


def test_proxy_auth_with_mfa_header_allowed(unauthenticated_client, monkeypatch):
    secret = _enable_proxy_auth(monkeypatch, trusted=True)

    response = unauthenticated_client.get(
        "/v1/admin/profile",
        headers=_proxy_headers(secret, include_mfa=True),
    )

    assert response.status_code == 200


def test_untrusted_proxy_rejects_mfa_header(unauthenticated_client, monkeypatch):
    secret = _enable_proxy_auth(monkeypatch, trusted=False)

    response = unauthenticated_client.get(
        "/v1/admin/profile",
        headers=_proxy_headers(secret, include_mfa=True),
    )

    assert response.status_code == 401
    assert response.headers.get("X-Admin-Auth-Fail-Reason") == "untrusted_proxy"
