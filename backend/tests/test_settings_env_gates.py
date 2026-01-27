import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_e2e_proxy_auth_allowed_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")

    settings = Settings(
        app_env="ci",
        e2e_proxy_auth_enabled=True,
        e2e_proxy_auth_secret="ci-secret",
        trust_proxy_headers=True,
        trusted_proxy_ips=["127.0.0.1"],
        _env_file=None,
    )

    assert settings.e2e_proxy_auth_enabled is True


def test_e2e_proxy_auth_rejected_in_prod(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("TESTING", raising=False)

    with pytest.raises(
        ValidationError,
        match=r"E2E_PROXY_AUTH_ENABLED is not allowed in prod .*APP_ENV=prod.*Set APP_ENV=ci",
    ):
        Settings(
            app_env="prod",
            e2e_proxy_auth_enabled=True,
            e2e_proxy_auth_secret="prod-secret",
            auth_secret_key="super-secret",
            client_portal_secret="client-secret",
            worker_portal_secret="worker-secret",
            metrics_enabled=False,
            trust_proxy_headers=True,
            trusted_proxy_ips=["127.0.0.1"],
            _env_file=None,
        )
