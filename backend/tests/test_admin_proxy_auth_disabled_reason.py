import base64

from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _proxy_headers(username: str) -> dict[str, str]:
    return {
        "X-Admin-User": username,
        "X-Admin-Email": username,
        "X-Admin-Roles": "admin",
        "X-Proxy-Auth": "1",
    }


def test_proxy_headers_rejected_when_proxy_disabled(client_no_raise):
    settings.app_env = "dev"
    settings.admin_proxy_auth_enabled = False

    response = client_no_raise.get("/v1/admin/profile", headers=_proxy_headers("admin"))
    assert response.status_code == 401
    assert response.headers["X-Admin-Auth-Fail-Reason"] == "proxy_disabled"


def test_proxy_headers_allowed_when_proxy_enabled(client):
    settings.app_env = "dev"
    settings.admin_proxy_auth_enabled = True
    settings.trust_proxy_headers = True
    settings.trusted_proxy_ips = ["testclient"]
    settings.trusted_proxy_cidrs = []

    response = client.get("/v1/admin/profile", headers=_proxy_headers("admin"))
    assert response.status_code == 200


def test_basic_auth_still_allowed_when_proxy_disabled(client):
    settings.app_env = "dev"
    settings.admin_proxy_auth_enabled = False
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "admin123"

    response = client.get(
        "/v1/admin/profile",
        headers={**_basic_auth("admin", "admin123"), "X-Test-Inspect-Admin-Identity": "1"},
    )
    assert response.status_code == 200
