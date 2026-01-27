import pytest

from app.settings import Settings


@pytest.mark.parametrize(
    "env_var, value, attr",
    [
        ("AUTH_SECRET_KEY", "alias-auth-secret", "auth_secret_key"),
        ("CLIENT_PORTAL_SECRET", "alias-client-secret", "client_portal_secret"),
        ("WORKER_PORTAL_SECRET", "alias-worker-secret", "worker_portal_secret"),
    ],
)
def test_secret_env_aliases(monkeypatch, env_var, value, attr):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv(env_var, value)

    settings = Settings(_env_file=None)

    assert getattr(settings, attr) == value


@pytest.mark.parametrize(
    "env_var, value, attr",
    [
        ("auth_secret_key", "legacy-auth-secret", "auth_secret_key"),
        ("client_portal_secret", "legacy-client-secret", "client_portal_secret"),
        ("worker_portal_secret", "legacy-worker-secret", "worker_portal_secret"),
    ],
)
def test_secret_env_aliases_accept_legacy_names(monkeypatch, env_var, value, attr):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv(env_var, value)

    settings = Settings(_env_file=None)

    assert getattr(settings, attr) == value
