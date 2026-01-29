def test_admin_client_authenticates_by_default(client):
    response = client.get("/v1/admin/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "admin"
