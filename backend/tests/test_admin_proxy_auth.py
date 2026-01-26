from app.settings import settings


def _proxy_headers(username: str, *, email: str | None = None, roles: str | None = None) -> dict[str, str]:
    headers = {
        "X-Admin-User": username,
        "X-Admin-Email": email or username,
    }
    if roles:
        headers["X-Admin-Roles"] = roles
    return headers


def test_admin_routes_require_proxy_headers(client_no_raise):
    settings.admin_proxy_auth_enabled = True
    settings.trust_proxy_headers = True
    settings.trusted_proxy_ips = ["testclient"]
    settings.trusted_proxy_cidrs = []

    response = client_no_raise.get("/v1/admin/profile")
    assert response.status_code == 401
    assert response.json()["detail"] == "Admin access requires proxy authentication"


def test_admin_routes_accept_proxy_headers(client):
    settings.admin_proxy_auth_enabled = True
    settings.trust_proxy_headers = True
    settings.trusted_proxy_ips = ["testclient"]
    settings.trusted_proxy_cidrs = []

    response = client.get("/v1/admin/profile", headers=_proxy_headers("admin", roles="admin"))
    assert response.status_code == 200


def test_non_admin_routes_unchanged(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
