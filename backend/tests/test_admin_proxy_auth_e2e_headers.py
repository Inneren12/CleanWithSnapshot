import hmac
import hashlib
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


def test_e2e_proxy_headers_allow_admin_access(client):
    settings.admin_proxy_auth_enabled = True
    settings.trust_proxy_headers = True
    settings.trusted_proxy_ips = ["testclient"]
    settings.trusted_proxy_cidrs = []
    settings.e2e_proxy_auth_enabled = True
    settings.e2e_proxy_auth_secret = "e2e-secret"
    settings.testing = True

    now = int(time.time())
    headers = _signed_headers("e2e-admin", "e2e-admin@example.com", "admin", now, settings.e2e_proxy_auth_secret)
    response = client.get("/v1/admin/profile", headers=headers)
    assert response.status_code == 200


def test_e2e_proxy_headers_reject_invalid_signature(client_no_raise):
    settings.admin_proxy_auth_enabled = True
    settings.trust_proxy_headers = True
    settings.trusted_proxy_ips = ["testclient"]
    settings.trusted_proxy_cidrs = []
    settings.e2e_proxy_auth_enabled = True
    settings.e2e_proxy_auth_secret = "e2e-secret"
    settings.testing = True

    now = int(time.time())
    headers = _signed_headers("e2e-admin", "e2e-admin@example.com", "admin", now, "wrong-secret")
    response = client_no_raise.get("/v1/admin/profile", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Admin access requires proxy authentication"


def test_e2e_proxy_headers_reject_stale_timestamp(client_no_raise):
    settings.admin_proxy_auth_enabled = True
    settings.trust_proxy_headers = True
    settings.trusted_proxy_ips = ["testclient"]
    settings.trusted_proxy_cidrs = []
    settings.e2e_proxy_auth_enabled = True
    settings.e2e_proxy_auth_secret = "e2e-secret"
    settings.testing = True

    past = int(time.time()) - 600
    headers = _signed_headers("e2e-admin", "e2e-admin@example.com", "admin", past, settings.e2e_proxy_auth_secret)
    response = client_no_raise.get("/v1/admin/profile", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "Admin access requires proxy authentication"
