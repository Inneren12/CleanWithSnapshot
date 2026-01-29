from app.settings import settings


def test_admin_read_only_blocks_writes(admin_client):
    settings.admin_read_only = True
    settings.admin_ip_allowlist_cidrs = []
    response = admin_client.post("/v1/admin/pricing/reload")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["detail"] == "Admin writes temporarily disabled"
    assert body["status"] == 409


def test_admin_ip_allowlist_blocks_non_matching_ip(admin_client):
    settings.admin_read_only = False
    settings.admin_ip_allowlist_cidrs = ["10.0.0.0/24"]
    settings.trust_proxy_headers = True
    settings.trusted_proxy_ips = ["testclient"]
    response = admin_client.get(
        "/v1/admin/profile",
        headers={"x-forwarded-for": "192.0.2.1"},
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["detail"] == "Admin access restricted to allowlisted IPs"
    assert body["status"] == 403


def test_admin_allowlist_allows_gets_when_matched(admin_client):
    settings.admin_read_only = False
    settings.admin_ip_allowlist_cidrs = ["127.0.0.0/8"]
    settings.trust_proxy_headers = True
    settings.trusted_proxy_ips = ["testclient"]
    response = admin_client.get(
        "/v1/admin/profile",
        headers={"x-forwarded-for": "127.0.0.5"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "admin"
