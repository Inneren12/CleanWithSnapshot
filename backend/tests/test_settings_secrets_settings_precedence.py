from __future__ import annotations

from pathlib import Path


def test_secrets_backend_precedence_env_over_dotenv(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=dev",
                "SECRETS_BACKEND=aws_ssm",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("SECRETS_BACKEND", "aws_secrets_manager")
    monkeypatch.setenv(
        "AWS_SECRETS_MANAGER_SECRET_JSON",
        (
            '{"AUTH_SECRET_KEY":"env-auth","CLIENT_PORTAL_SECRET":"env-client",'
            '"WORKER_PORTAL_SECRET":"env-worker","ADMIN_PROXY_AUTH_SECRET":"env-admin"}'
        ),
    )

    from app.settings import Settings

    settings = Settings(_env_file=str(env_file))

    assert settings.secrets_backend == "aws_secrets_manager"
    assert settings.auth_secret_key == "env-auth"
    assert settings.client_portal_secret == "env-client"
    assert settings.worker_portal_secret == "env-worker"
    assert settings.admin_proxy_auth_secret == "env-admin"


def test_secrets_backend_missing_config_does_not_crash_in_dev(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=dev\n", encoding="utf-8")

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("SECRETS_BACKEND", "aws_ssm")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_SSM_PARAMETER_PATH", raising=False)

    from app.settings import Settings

    settings = Settings(_env_file=str(env_file))

    assert settings.auth_secret_key == "dev-auth-secret"
