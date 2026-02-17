import pytest
from pydantic import ValidationError

from app.settings import Settings


@pytest.mark.parametrize("app_env", ["prod", "staging"])
def test_secure_envs_require_secrets(monkeypatch, app_env):
    monkeypatch.delenv("TESTING", raising=False)
    with pytest.raises(ValidationError, match="AUTH_SECRET_KEY"):
        Settings(
            app_env=app_env,
            admin_proxy_auth_secret="p" * 32,
            metrics_enabled=False,
            _env_file=None,
        )


@pytest.mark.parametrize("app_env", ["dev", "ci", "e2e", "test", "local"])
def test_dev_like_envs_allow_default_secrets(app_env):
    settings = Settings(app_env=app_env, _env_file=None)

    assert settings.auth_secret_key.get_secret_value() == "dev-auth-secret"
    assert settings.client_portal_secret.get_secret_value() == "dev-client-portal-secret"
    assert settings.worker_portal_secret.get_secret_value() == "dev-worker-portal-secret"
