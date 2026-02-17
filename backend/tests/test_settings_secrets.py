import pytest
from pydantic import SecretStr, ValidationError
from app.settings import Settings

def test_settings_secrets_types():
    """Verify that sensitive fields are typed as SecretStr."""
    settings = Settings(app_env="dev")

    assert isinstance(settings.client_portal_secret, SecretStr)
    assert isinstance(settings.worker_portal_secret, SecretStr)
    assert isinstance(settings.auth_secret_key, SecretStr)
    assert isinstance(settings.admin_proxy_auth_secret, SecretStr)

    assert settings.client_portal_secret.get_secret_value() == "dev-client-portal-secret"
    assert settings.worker_portal_secret.get_secret_value() == "dev-worker-portal-secret"
    assert settings.auth_secret_key.get_secret_value() == "dev-auth-secret"
    assert settings.admin_proxy_auth_secret.get_secret_value() == "dev-admin-proxy-auth-secret-0000"

def test_settings_prod_missing_secrets():
    """Verify that missing secrets raise validation error in prod."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            app_env="prod",
            testing=False, # Override testing=True from conftest.py
            metrics_enabled=False,
        )

    errors = excinfo.value.errors()
    fields = {str(e["loc"][0]).lower() for e in errors}

    assert "client_portal_secret" in fields
    assert "worker_portal_secret" in fields
    assert "auth_secret_key" in fields
    assert "admin_proxy_auth_secret" in fields

def test_settings_prod_explicit_secrets():
    """Verify that explicit secrets work in prod."""
    settings = Settings(
        app_env="prod",
        testing=False, # Override testing=True from conftest.py
        metrics_enabled=False,
        client_portal_secret="prod-client-secret-32-chars-minimum-length-required",
        worker_portal_secret="prod-worker-secret-32-chars-minimum-length-required",
        auth_secret_key="prod-auth-secret-32-chars-minimum-length-required",
        admin_proxy_auth_secret="prod-admin-proxy-secret-very-long-to-satisfy-length-requirement",
        admin_proxy_auth_enabled=True,
        cors_origins="https://example.com",
    )

    assert settings.client_portal_secret.get_secret_value() == "prod-client-secret-32-chars-minimum-length-required"
    assert settings.worker_portal_secret.get_secret_value() == "prod-worker-secret-32-chars-minimum-length-required"
    assert settings.auth_secret_key.get_secret_value() == "prod-auth-secret-32-chars-minimum-length-required"
    assert settings.admin_proxy_auth_secret.get_secret_value() == "prod-admin-proxy-secret-very-long-to-satisfy-length-requirement"

def test_settings_prod_validation_failures():
    """Verify validate_prod_settings catches weak secrets."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            app_env="prod",
            testing=False, # Override testing=True from conftest.py
            metrics_enabled=False,
            client_portal_secret="prod-client-secret-32-chars-minimum-length-required",
            worker_portal_secret="prod-worker-secret-32-chars-minimum-length-required",
            auth_secret_key="prod-auth-secret-32-chars-minimum-length-required",
            admin_proxy_auth_secret="short",
            admin_proxy_auth_enabled=True,
            cors_origins="https://example.com",
        )
    assert "ADMIN_PROXY_AUTH_SECRET must be at least 32 characters" in str(excinfo.value)
