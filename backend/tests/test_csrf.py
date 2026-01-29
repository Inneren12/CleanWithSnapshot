import base64

import pytest

from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}", "X-Auth-MFA": "true"}


def _csrf_cookie_attributes(response) -> list[str]:
    header = response.headers.get("set-cookie", "")
    assert "csrf_token=" in header
    return [part.strip().lower() for part in header.split(";")[1:]]


@pytest.mark.anyio
async def test_csrf_enforced_when_testing_disabled(client):
    original = {
        "testing": settings.testing,
        "admin_basic_username": settings.admin_basic_username,
        "admin_basic_password": settings.admin_basic_password,
    }
    settings.testing = False
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        headers = _basic_auth("admin", "secret")
        get_resp = client.get("/v1/admin/ui/workers", headers=headers)
        assert get_resp.status_code == 200

        post_resp = client.post(
            "/v1/admin/ui/workers/new",
            headers=headers,
            data={
                "name": "CSRF Test Worker",
                "phone": "+1 555-0000",
                "team_id": 1,
            },
            follow_redirects=False,
        )
        assert post_resp.status_code == 403
    finally:
        settings.testing = original["testing"]
        settings.admin_basic_username = original["admin_basic_username"]
        settings.admin_basic_password = original["admin_basic_password"]


@pytest.mark.anyio
async def test_csrf_cookie_flags_in_prod(client):
    original_env = settings.app_env
    original_user = settings.dispatcher_basic_username
    original_password = settings.dispatcher_basic_password
    settings.app_env = "prod"
    settings.dispatcher_basic_username = "dispatch"
    settings.dispatcher_basic_password = "secret"

    try:
        headers = _basic_auth("dispatch", "secret")
        response = client.get("/v1/admin/ui/clients/new", headers=headers)
        assert response.status_code == 200

        attrs = _csrf_cookie_attributes(response)
        assert "httponly" in attrs
        assert "secure" in attrs
        assert "samesite=lax" in attrs
    finally:
        settings.app_env = original_env
        settings.dispatcher_basic_username = original_user
        settings.dispatcher_basic_password = original_password


@pytest.mark.anyio
async def test_csrf_cookie_flags_in_dev(client):
    original_env = settings.app_env
    original_user = settings.dispatcher_basic_username
    original_password = settings.dispatcher_basic_password
    settings.app_env = "dev"
    settings.dispatcher_basic_username = "dispatch"
    settings.dispatcher_basic_password = "secret"

    try:
        headers = _basic_auth("dispatch", "secret")
        response = client.get("/v1/admin/ui/clients/new", headers=headers)
        assert response.status_code == 200

        attrs = _csrf_cookie_attributes(response)
        assert "httponly" in attrs
        assert "samesite=lax" in attrs
        assert "secure" not in attrs
    finally:
        settings.app_env = original_env
        settings.dispatcher_basic_username = original_user
        settings.dispatcher_basic_password = original_password
