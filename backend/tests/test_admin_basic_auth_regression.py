import pytest

from app.settings import Settings, settings


def _set_admin_creds(monkeypatch: pytest.MonkeyPatch, username: str = "admin", password: str = "super-secure-pass") -> None:
    monkeypatch.setattr(settings, "admin_basic_username", username)
    monkeypatch.setattr(settings, "admin_basic_password", password)


def test_prod_defaults_disable_basic_auth_even_if_creds_present(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("AUTH_SECRET_KEY", "basic-auth-secret-prod")
    monkeypatch.setenv("CLIENT_PORTAL_SECRET", "client-secret-prod")
    monkeypatch.setenv("WORKER_PORTAL_SECRET", "worker-secret-prod")
    monkeypatch.setenv("ADMIN_BASIC_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_BASIC_PASSWORD", "very-strong-admin-pass")
    monkeypatch.setenv("METRICS_ENABLED", "false")

    prod_settings = Settings()

    assert prod_settings.legacy_basic_auth_enabled is False


def test_prod_basic_auth_requires_explicit_enable(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "legacy_basic_auth_enabled", False)
    _set_admin_creds(monkeypatch)

    response = client.get("/v1/admin/profile", auth=("admin", "super-secure-pass"))

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Basic"


def test_prod_basic_auth_enabled_allows_valid_credentials(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "legacy_basic_auth_enabled", True)
    _set_admin_creds(monkeypatch, password="really-strong-admin-pass")

    response = client.get("/v1/admin/profile", auth=("admin", "really-strong-admin-pass"))

    assert response.status_code == 200
    assert response.json().get("username") == "admin"


def test_prod_basic_auth_enabled_rejects_placeholder_passwords(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("AUTH_SECRET_KEY", "basic-auth-secret-prod")
    monkeypatch.setenv("CLIENT_PORTAL_SECRET", "client-secret-prod")
    monkeypatch.setenv("WORKER_PORTAL_SECRET", "worker-secret-prod")
    monkeypatch.setenv("METRICS_ENABLED", "false")
    monkeypatch.setenv("LEGACY_BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("ADMIN_BASIC_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_BASIC_PASSWORD", "change-me")

    with pytest.raises(ValueError):
        Settings()
