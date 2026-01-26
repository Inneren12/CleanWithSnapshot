import base64

import pytest

from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


def _proxy_headers(username: str, *, email: str | None = None, roles: str | None = None) -> dict[str, str]:
    headers = {
        "X-Admin-User": username,
        "X-Admin-Email": email or username,
        "X-Proxy-Auth": "1",
    }
    if roles:
        headers["X-Admin-Roles"] = roles
    return headers


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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

    response = client.get(
        "/v1/admin/profile",
        headers={**_proxy_headers("admin", roles="admin"), "X-Test-Inspect-Admin-Identity": "1"},
    )
    assert response.status_code == 200
    assert response.headers["X-Test-Admin-Identity-Source"] == "proxy"


@pytest.mark.anyio
async def test_admin_routes_reject_saas_tokens_without_proxy_headers(async_session_maker, client_no_raise):
    settings.admin_proxy_auth_enabled = True
    settings.trust_proxy_headers = True
    settings.trusted_proxy_ips = ["testclient"]
    settings.trusted_proxy_cidrs = []

    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Proxy Gate Org")
        user = await saas_service.create_user(session, "proxy-gate@example.com", "SecretPass123!")
        membership = await saas_service.create_membership(session, org, user, MembershipRole.ADMIN)
        await session.commit()

    token = saas_service.build_access_token(user, membership)

    response = client_no_raise.get(
        "/v1/admin/profile",
        headers={"Authorization": f"Bearer {token}", "X-Test-Inspect-Admin-Identity": "1"},
    )
    assert response.status_code == 401
    assert response.headers["X-Test-Admin-Identity-Source"] == "saas"


def test_admin_routes_allow_basic_auth_when_proxy_disabled(client):
    settings.admin_proxy_auth_enabled = False

    response = client.get(
        "/v1/admin/profile",
        headers={**_basic_auth("admin", "admin123"), "X-Test-Inspect-Admin-Identity": "1"},
    )
    assert response.status_code == 200
    assert response.headers["X-Test-Admin-Identity-Source"] == "basic"


def test_non_admin_routes_unchanged(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
