def test_admin_client_authenticates_by_default(admin_client):
    response = admin_client.get("/v1/admin/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "admin"


def test_anon_client_rejects_admin_profile(client):
    response = client.get("/v1/admin/profile")

    assert response.status_code == 401
    assert response.headers.get("X-Admin-Auth-Fail-Reason") == "missing_authorization"
