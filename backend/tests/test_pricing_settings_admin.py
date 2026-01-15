import base64

from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_service_types_crud_owner(client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    headers = _auth_headers("owner", "secret")
    payload = {
        "name": "Deep Clean",
        "description": "Full deep clean",
        "active": True,
        "default_duration_minutes": 240,
        "pricing_model": "flat",
        "base_price_cents": 25000,
        "hourly_rate_cents": 0,
        "currency": "CAD",
    }

    create_resp = client.post("/v1/admin/service-types", json=payload, headers=headers)
    assert create_resp.status_code == 201
    service_type_id = create_resp.json()["service_type_id"]

    list_resp = client.get("/v1/admin/service-types", headers=headers)
    assert list_resp.status_code == 200
    assert any(item["service_type_id"] == service_type_id for item in list_resp.json())

    update_resp = client.patch(
        f"/v1/admin/service-types/{service_type_id}",
        json={"name": "Deep Clean Plus"},
        headers=headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Deep Clean Plus"

    addon_resp = client.post(
        f"/v1/admin/service-types/{service_type_id}/addons",
        json={"name": "Oven", "price_cents": 3500, "active": True},
        headers=headers,
    )
    assert addon_resp.status_code == 201
    addon_id = addon_resp.json()["addon_id"]

    addon_update = client.patch(
        f"/v1/admin/service-addons/{addon_id}",
        json={"price_cents": 4000},
        headers=headers,
    )
    assert addon_update.status_code == 200
    assert addon_update.json()["price_cents"] == 4000

    addon_delete = client.delete(f"/v1/admin/service-addons/{addon_id}", headers=headers)
    assert addon_delete.status_code == 204

    delete_resp = client.delete(f"/v1/admin/service-types/{service_type_id}", headers=headers)
    assert delete_resp.status_code == 204


def test_pricing_settings_rbac(client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.dispatcher_basic_username = "dispatcher"
    settings.dispatcher_basic_password = "dispatch"
    settings.legacy_basic_auth_enabled = True

    owner_headers = _auth_headers("owner", "secret")
    dispatcher_headers = _auth_headers("dispatcher", "dispatch")

    get_resp = client.get("/v1/admin/pricing-settings", headers=dispatcher_headers)
    assert get_resp.status_code == 200

    update_resp = client.patch(
        "/v1/admin/pricing-settings",
        json={"gst_rate": 0.05, "promo_enabled": True},
        headers=dispatcher_headers,
    )
    assert update_resp.status_code == 403

    owner_update = client.patch(
        "/v1/admin/pricing-settings",
        json={"gst_rate": 0.05, "promo_enabled": True},
        headers=owner_headers,
    )
    assert owner_update.status_code == 200


def test_booking_policies_rbac(client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.dispatcher_basic_username = "dispatcher"
    settings.dispatcher_basic_password = "dispatch"
    settings.legacy_basic_auth_enabled = True

    owner_headers = _auth_headers("owner", "secret")
    dispatcher_headers = _auth_headers("dispatcher", "dispatch")

    get_resp = client.get("/v1/admin/booking-policies", headers=dispatcher_headers)
    assert get_resp.status_code == 200

    update_resp = client.patch(
        "/v1/admin/booking-policies",
        json={"deposit": {"enabled": True, "percent": 0.3, "minimum_cents": 0, "due_days": 1}},
        headers=dispatcher_headers,
    )
    assert update_resp.status_code == 403

    owner_update = client.patch(
        "/v1/admin/booking-policies",
        json={"deposit": {"enabled": True, "percent": 0.3, "minimum_cents": 0, "due_days": 1}},
        headers=owner_headers,
    )
    assert owner_update.status_code == 200
