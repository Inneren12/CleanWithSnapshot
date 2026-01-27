import hashlib
import hmac
import time

from app.settings import settings


def _signed_headers(user: str, email: str, roles: str, timestamp: int, secret: str) -> dict[str, str]:
    canonical = f"{user}|{email}|{roles}|{timestamp}"
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Proxy-Admin-User": user,
        "X-Proxy-Admin-Email": email,
        "X-Proxy-Admin-Roles": roles,
        "X-Proxy-Admin-Timestamp": str(timestamp),
        "X-Proxy-Admin-Signature": signature,
    }


def _configure_settings() -> None:
    settings.app_env = "dev"
    settings.admin_proxy_auth_enabled = True
    settings.trust_proxy_headers = True
    settings.trusted_proxy_cidrs = []
    settings.e2e_proxy_auth_enabled = True
    settings.e2e_proxy_auth_secret = "e2e-secret"
    settings.testing = True


def test_e2e_proxy_headers_trusted_peer(client):
    _configure_settings()
    settings.trusted_proxy_ips = ["testclient"]

    now = int(time.time())
    headers = _signed_headers("e2e-admin", "e2e-admin@example.com", "admin", now, settings.e2e_proxy_auth_secret)
    response = client.get("/v1/admin/profile", headers=headers)
    assert response.status_code == 200


def test_e2e_proxy_headers_untrusted_peer(client_no_raise):
    _configure_settings()
    settings.trusted_proxy_ips = ["127.0.0.1"]

    now = int(time.time())
    headers = _signed_headers("e2e-admin", "e2e-admin@example.com", "admin", now, settings.e2e_proxy_auth_secret)
    response = client_no_raise.get("/v1/admin/profile", headers=headers)
    assert response.status_code == 401
    assert response.headers["X-Admin-Auth-Fail-Reason"] == "untrusted_proxy"
    assert response.headers["X-Admin-Auth-Peer-IP"] == "testclient"
