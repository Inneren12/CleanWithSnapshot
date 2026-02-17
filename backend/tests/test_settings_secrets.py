import os
import pytest
from pydantic import ValidationError
from app.settings import Settings

@pytest.fixture
def clean_env():
    keys = [
        "APP_ENV", "app_env",
        "AUTH_SECRET_KEY", "auth_secret_key",
        "CLIENT_PORTAL_SECRET", "client_portal_secret",
        "WORKER_PORTAL_SECRET", "worker_portal_secret",
        "ADMIN_PROXY_AUTH_SECRET", "admin_proxy_auth_secret",
        "ADMIN_PROXY_AUTH_ENABLED",
    ]
    old_env = {}
    for key in keys:
        if key in os.environ:
            old_env[key] = os.environ.pop(key)
    yield
    # Restore
    for key in keys:
        if key in os.environ:
            del os.environ[key]
    os.environ.update(old_env)

def test_prod_missing_secrets_fail(clean_env):
    """Test A: prod + missing secrets => FAIL"""
    # app_env defaults to "prod" if not set in Settings definition,
    # but we want to ensure we test explicit prod behavior too.
    os.environ["APP_ENV"] = "prod"
    # Secrets are missing.
    with pytest.raises(ValidationError) as excinfo:
        Settings()
    # Check that it failed because of missing secrets
    assert "auth_secret_key" in str(excinfo.value) or "AUTH_SECRET_KEY" in str(excinfo.value)

def test_dev_missing_secrets_ok(clean_env):
    """Test B: dev + missing secrets => OK (injected)"""
    os.environ["APP_ENV"] = "dev"
    s = Settings()
    assert s.auth_secret_key.get_secret_value() == "dev-auth-secret"
    assert s.client_portal_secret.get_secret_value() == "dev-client-portal-secret"
    assert s.worker_portal_secret.get_secret_value() == "dev-worker-portal-secret"
    # Admin proxy auth secret is also injected (even if not enabled, field is present)
    assert s.admin_proxy_auth_secret.get_secret_value() == "dev-admin-proxy-secret-must-be-at-least-32-chars-long"

def test_prod_placeholder_secrets_fail(clean_env):
    """Test C: prod + placeholder/dev-default secret => FAIL"""
    os.environ["APP_ENV"] = "prod"
    os.environ["AUTH_SECRET_KEY"] = "dev-auth-secret" # Weak/default
    os.environ["CLIENT_PORTAL_SECRET"] = "strong-secret-but-others-missing"
    os.environ["WORKER_PORTAL_SECRET"] = "strong-secret-but-others-missing"
    # admin_proxy_auth_secret is optional unless enabled?
    # Based on my changes, it is a required SecretStr field.
    # But validation logic:
    # if self.admin_proxy_auth_enabled:
    #    ... check secret ...
    # Wait, strict typing says SecretStr. Default None was removed.
    # So it MUST be provided.
    os.environ["ADMIN_PROXY_AUTH_SECRET"] = "some-secret"

    with pytest.raises(ValueError) as excinfo:
        Settings()

    # We expect validation error from validate_prod_settings
    assert "AUTH_SECRET_KEY" in str(excinfo.value) and "non-default value" in str(excinfo.value)

def test_prod_strong_secrets_ok(clean_env):
    """Test D: prod + strong secrets => OK"""
    os.environ["APP_ENV"] = "prod"
    os.environ["METRICS_ENABLED"] = "false"
    os.environ["AUTH_SECRET_KEY"] = "very-secure-secret-key-for-auth-12345"
    os.environ["CLIENT_PORTAL_SECRET"] = "very-secure-client-portal-secret-12345"
    os.environ["WORKER_PORTAL_SECRET"] = "very-secure-worker-portal-secret-12345"
    os.environ["ADMIN_PROXY_AUTH_SECRET"] = "very-secure-admin-proxy-secret-12345"

    s = Settings()
    assert s.auth_secret_key.get_secret_value() == "very-secure-secret-key-for-auth-12345"
