import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.settings import Settings

PROD_SECRET = "a" * 32
PROD_PROXY_SECRET = "p" * 32


def test_cors_strict_blocks_when_empty(monkeypatch):
    monkeypatch.setenv("TESTING", "false")  # Prod mode requires TESTING=false
    monkeypatch.setenv("ADMIN_PROXY_AUTH_SECRET", PROD_PROXY_SECRET)
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        create_app(
            Settings(
                app_env="prod",
                strict_cors=True,
                cors_origins=[],
                auth_secret_key=PROD_SECRET,
                client_portal_secret=PROD_SECRET,
                worker_portal_secret=PROD_SECRET,
                admin_proxy_auth_secret=PROD_PROXY_SECRET,
                metrics_enabled=False,
            )
        )


def test_cors_allows_configured_origin(monkeypatch):
    monkeypatch.setenv("TESTING", "false")  # Prod mode requires TESTING=false
    monkeypatch.setenv("ADMIN_PROXY_AUTH_SECRET", PROD_PROXY_SECRET)
    app = create_app(
        Settings(
            app_env="prod",
            cors_origins=["https://example.com"],
            auth_secret_key=PROD_SECRET,
            client_portal_secret=PROD_SECRET,
            worker_portal_secret=PROD_SECRET,
            admin_proxy_auth_secret=PROD_PROXY_SECRET,
            metrics_enabled=False,
        )
    )
    with TestClient(app) as client:
        response = client.get("/healthz", headers={"Origin": "https://example.com"})
        assert response.headers["access-control-allow-origin"] == "https://example.com"
