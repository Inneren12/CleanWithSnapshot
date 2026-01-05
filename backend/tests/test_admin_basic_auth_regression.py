from fastapi.testclient import TestClient

from app.settings import Settings, settings


def _set_admin_creds(username: str = "admin", password: str = "secret") -> None:
    settings.admin_basic_username = username
    settings.admin_basic_password = password


def test_prod_defaults_enable_basic_auth_when_creds_present(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("AUTH_SECRET_KEY", "basic-auth-secret")
    monkeypatch.setenv("CLIENT_PORTAL_SECRET", "client-secret")
    monkeypatch.setenv("WORKER_PORTAL_SECRET", "worker-secret")
    monkeypatch.setenv("ADMIN_BASIC_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_BASIC_PASSWORD", "secret")
    monkeypatch.setenv("METRICS_ENABLED", "false")

    prod_settings = Settings()

    assert prod_settings.legacy_basic_auth_enabled is True


def test_admin_basic_auth_allows_valid_credentials(client: TestClient):
    original_env = settings.app_env
    settings.app_env = "prod"
    settings.legacy_basic_auth_enabled = None
    _set_admin_creds()

    response = client.get("/v1/admin/profile", auth=("admin", "secret"))

    settings.app_env = original_env

    assert response.status_code == 200
    assert response.json().get("username") == "admin"


def test_admin_basic_auth_missing_credentials_rejected(client: TestClient):
    original_env = settings.app_env
    settings.app_env = "prod"
    settings.legacy_basic_auth_enabled = None
    _set_admin_creds()

    response = client.get("/v1/admin/profile")

    settings.app_env = original_env

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Basic"
