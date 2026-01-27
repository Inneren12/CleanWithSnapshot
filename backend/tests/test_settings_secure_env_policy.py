import pytest
from pydantic import ValidationError

from app.settings import Settings


@pytest.mark.parametrize("app_env", ["prod", "staging"])
def test_secure_envs_require_secrets(monkeypatch, app_env):
    monkeypatch.delenv("TESTING", raising=False)
    with pytest.raises(ValidationError, match="AUTH_SECRET_KEY"):
        Settings(app_env=app_env, metrics_enabled=False, _env_file=None)


@pytest.mark.parametrize("app_env", ["dev", "ci", "e2e", "test", "local"])
def test_dev_like_envs_allow_default_secrets(app_env):
    settings = Settings(app_env=app_env, _env_file=None)

    assert settings.auth_secret_key == "dev-auth-secret"
    assert settings.client_portal_secret == "dev-client-portal-secret"
    assert settings.worker_portal_secret == "dev-worker-portal-secret"
