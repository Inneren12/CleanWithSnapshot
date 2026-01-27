from app.settings import Settings


def test_admin_proxy_auth_enabled_env_true(monkeypatch):
    monkeypatch.setenv("ADMIN_PROXY_AUTH_ENABLED", "true")
    settings = Settings(_env_file=None)

    assert settings.admin_proxy_auth_enabled is True


def test_admin_proxy_auth_enabled_env_false(monkeypatch):
    monkeypatch.setenv("ADMIN_PROXY_AUTH_ENABLED", "false")
    settings = Settings(_env_file=None)

    assert settings.admin_proxy_auth_enabled is False
