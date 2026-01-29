"""Tests for admin proxy authentication.

These tests verify the proxy-based admin authentication where:
- Reverse proxy authenticates users and injects trusted headers
- Backend validates proxy headers using a shared secret
- Direct access without proxy headers is rejected when proxy auth is required
"""
import pytest

from app.settings import settings


def _enable_proxy_auth(monkeypatch: pytest.MonkeyPatch, *, required: bool = False) -> str:
    """Enable proxy auth and return the shared secret."""
    secret = "test-proxy-auth-secret-at-least-32-chars"
    monkeypatch.setattr(settings, "admin_proxy_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_proxy_auth_required", required)
    monkeypatch.setattr(settings, "admin_proxy_auth_secret", secret)
    monkeypatch.setattr(settings, "legacy_basic_auth_enabled", False)
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_ips", ["testclient"])
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", [])
    monkeypatch.setattr(settings, "admin_proxy_auth_e2e_enabled", False)
    return secret


def _disable_proxy_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable proxy auth."""
    monkeypatch.setattr(settings, "admin_proxy_auth_enabled", False)
    monkeypatch.setattr(settings, "admin_proxy_auth_required", False)


def _set_basic_auth_creds(
    monkeypatch: pytest.MonkeyPatch, username: str = "admin", password: str = "super-secure-pass"
) -> None:
    monkeypatch.setattr(settings, "admin_basic_username", username)
    monkeypatch.setattr(settings, "admin_basic_password", password)
    monkeypatch.setattr(settings, "legacy_basic_auth_enabled", True)


class TestProxyAuthEnabled:
    """Tests when proxy auth is enabled."""

    def test_valid_proxy_headers_allow_access(self, unauthenticated_client, monkeypatch):
        """Valid proxy headers with correct secret should allow access."""
        secret = _enable_proxy_auth(monkeypatch)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            headers={
                "X-Admin-User": "admin",
                "X-Admin-Roles": "admin",
                "X-Proxy-Auth-Secret": secret,
                "X-Auth-MFA": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data.get("username") == "admin"

    def test_proxy_auth_with_owner_role(self, unauthenticated_client, monkeypatch):
        """Proxy auth with owner role should grant full permissions."""
        secret = _enable_proxy_auth(monkeypatch)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            headers={
                "X-Admin-User": "owner-user",
                "X-Admin-Roles": "owner",
                "X-Proxy-Auth-Secret": secret,
                "X-Auth-MFA": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data.get("username") == "owner-user"
        assert data.get("role") == "owner"

    def test_proxy_auth_with_viewer_role(self, unauthenticated_client, monkeypatch):
        """Proxy auth with viewer role should allow read access."""
        secret = _enable_proxy_auth(monkeypatch)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            headers={
                "X-Admin-User": "viewer-user",
                "X-Admin-Roles": "viewer",
                "X-Proxy-Auth-Secret": secret,
                "X-Auth-MFA": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data.get("username") == "viewer-user"
        assert data.get("role") == "viewer"

    def test_invalid_proxy_secret_rejects_access(self, unauthenticated_client, monkeypatch):
        """Invalid proxy secret should reject access."""
        _enable_proxy_auth(monkeypatch)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            headers={
                "X-Admin-User": "admin",
                "X-Admin-Roles": "admin",
                "X-Proxy-Auth-Secret": "wrong-secret",
                "X-Auth-MFA": "true",
            },
        )

        assert response.status_code == 401

    def test_missing_proxy_secret_rejects_access(self, unauthenticated_client, monkeypatch):
        """Missing proxy secret should reject access."""
        _enable_proxy_auth(monkeypatch)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            headers={
                "X-Admin-User": "admin",
                "X-Admin-Roles": "admin",
                "X-Auth-MFA": "true",
            },
        )

        assert response.status_code == 401

    def test_missing_user_header_rejects_access(self, unauthenticated_client, monkeypatch):
        """Missing user header should reject access."""
        secret = _enable_proxy_auth(monkeypatch)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            headers={
                "X-Admin-Roles": "admin",
                "X-Proxy-Auth-Secret": secret,
                "X-Auth-MFA": "true",
            },
        )

        assert response.status_code == 401

    def test_multiple_roles_uses_highest_privilege(self, unauthenticated_client, monkeypatch):
        """When multiple roles are provided, highest privilege should be used."""
        secret = _enable_proxy_auth(monkeypatch)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            headers={
                "X-Admin-User": "multi-role-user",
                "X-Admin-Roles": "viewer,dispatcher,admin",
                "X-Proxy-Auth-Secret": secret,
                "X-Auth-MFA": "true",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data.get("role") == "admin"


class TestProxyAuthRequired:
    """Tests when proxy auth is required (blocks direct access)."""

    def test_no_headers_rejects_access(self, unauthenticated_client, monkeypatch):
        """Without proxy headers, access should be rejected."""
        _enable_proxy_auth(monkeypatch, required=True)

        response = unauthenticated_client.get("/v1/admin/profile")

        assert response.status_code == 401
        assert "proxy authentication" in response.json().get("detail", "").lower()

    def test_basic_auth_ignored_when_proxy_required(self, unauthenticated_client, monkeypatch):
        """Basic auth should be ignored when proxy auth is required."""
        _enable_proxy_auth(monkeypatch, required=True)
        _set_basic_auth_creds(monkeypatch)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            auth=("admin", "super-secure-pass"),
        )

        assert response.status_code == 401

    def test_valid_proxy_headers_allow_access_when_required(self, unauthenticated_client, monkeypatch):
        """Valid proxy headers should allow access when required."""
        secret = _enable_proxy_auth(monkeypatch, required=True)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            headers={
                "X-Admin-User": "admin",
                "X-Admin-Roles": "admin",
                "X-Proxy-Auth-Secret": secret,
                "X-Auth-MFA": "true",
            },
        )

        assert response.status_code == 200


class TestProxyAuthStrict:
    """Tests that proxy auth blocks Basic Auth when enabled."""

    def test_basic_auth_rejected_when_proxy_enabled(self, unauthenticated_client, monkeypatch):
        _enable_proxy_auth(monkeypatch, required=False)
        _set_basic_auth_creds(monkeypatch)

        response = unauthenticated_client.get(
            "/v1/admin/profile",
            auth=("admin", "super-secure-pass"),
        )

        assert response.status_code == 401


class TestNonAdminRoutesUnaffected:
    """Tests that non-admin routes are not affected by proxy auth settings."""

    def test_healthz_accessible_with_proxy_auth_required(self, unauthenticated_client, monkeypatch):
        """Health check endpoint should be accessible regardless of proxy auth."""
        _enable_proxy_auth(monkeypatch, required=True)

        response = unauthenticated_client.get("/healthz")

        assert response.status_code == 200

    def test_readyz_accessible_with_proxy_auth_required(self, unauthenticated_client, monkeypatch):
        """Readiness endpoint should be accessible regardless of proxy auth."""
        _enable_proxy_auth(monkeypatch, required=True)

        response = unauthenticated_client.get("/readyz")

        assert response.status_code == 200

    def test_docs_accessible_with_proxy_auth_required(self, unauthenticated_client, monkeypatch):
        """OpenAPI docs should be accessible regardless of proxy auth."""
        _enable_proxy_auth(monkeypatch, required=True)

        response = unauthenticated_client.get("/openapi.json")

        assert response.status_code == 200


class TestProxyAuthSettingsValidation:
    """Tests for settings validation related to proxy auth."""

    def test_proxy_required_without_enabled_fails_in_prod(self, monkeypatch):
        """Setting proxy_auth_required=True without enabled=True should fail in prod."""
        from app.settings import Settings

        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("AUTH_SECRET_KEY", "prod-auth-secret-at-least-32-chars")
        monkeypatch.setenv("CLIENT_PORTAL_SECRET", "prod-client-secret")
        monkeypatch.setenv("WORKER_PORTAL_SECRET", "prod-worker-secret")
        monkeypatch.setenv("ADMIN_PROXY_AUTH_SECRET", "proxy-secret-at-least-32-chars")
        monkeypatch.setenv("METRICS_ENABLED", "false")
        monkeypatch.setenv("ADMIN_PROXY_AUTH_ENABLED", "false")
        monkeypatch.setenv("ADMIN_PROXY_AUTH_REQUIRED", "true")

        with pytest.raises(ValueError, match="ADMIN_PROXY_AUTH_REQUIRED.*ADMIN_PROXY_AUTH_ENABLED"):
            Settings()

    def test_proxy_enabled_without_secret_fails_in_prod(self, monkeypatch):
        """Enabling proxy auth without a secret should fail in prod."""
        from app.settings import Settings

        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("AUTH_SECRET_KEY", "prod-auth-secret-at-least-32-chars")
        monkeypatch.setenv("CLIENT_PORTAL_SECRET", "prod-client-secret")
        monkeypatch.setenv("WORKER_PORTAL_SECRET", "prod-worker-secret")
        monkeypatch.setenv("METRICS_ENABLED", "false")
        monkeypatch.setenv("ADMIN_PROXY_AUTH_ENABLED", "true")

        with pytest.raises(ValueError, match="ADMIN_PROXY_AUTH_SECRET.*required"):
            Settings()

    def test_proxy_secret_too_short_fails_in_prod(self, monkeypatch):
        """Proxy auth secret that is too short should fail in prod."""
        from app.settings import Settings

        monkeypatch.setenv("APP_ENV", "prod")
        monkeypatch.setenv("AUTH_SECRET_KEY", "prod-auth-secret-at-least-32-chars")
        monkeypatch.setenv("CLIENT_PORTAL_SECRET", "prod-client-secret")
        monkeypatch.setenv("WORKER_PORTAL_SECRET", "prod-worker-secret")
        monkeypatch.setenv("METRICS_ENABLED", "false")
        monkeypatch.setenv("ADMIN_PROXY_AUTH_ENABLED", "true")
        monkeypatch.setenv("ADMIN_PROXY_AUTH_SECRET", "too-short")

        with pytest.raises(ValueError, match="32 characters"):
            Settings()
