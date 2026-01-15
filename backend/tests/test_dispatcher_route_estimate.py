import base64

import pytest

from app.domain.dispatcher import route_estimates
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _admin_creds():
    original = {
        "admin_basic_username": settings.admin_basic_username,
        "admin_basic_password": settings.admin_basic_password,
        "viewer_basic_username": settings.viewer_basic_username,
        "viewer_basic_password": settings.viewer_basic_password,
        "google_maps_api_key": settings.google_maps_api_key,
    }
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.viewer_basic_username = "viewer"
    settings.viewer_basic_password = "viewpass"
    settings.google_maps_api_key = None
    yield
    for key, value in original.items():
        setattr(settings, key, value)


def test_heuristic_estimate_enforces_min_duration():
    estimate = route_estimates.estimate_route_heuristic(
        origin_lat=53.5461,
        origin_lng=-113.4938,
        dest_lat=53.5462,
        dest_lng=-113.494,
    )

    assert estimate.provider == "heuristic"
    assert estimate.duration_min >= 5
    assert estimate.distance_km >= 0


@pytest.mark.anyio
async def test_dispatcher_route_estimate_uses_heuristic_without_google_key(client):
    route_estimates.clear_cache()
    response = client.post(
        "/v1/admin/dispatcher/routes/estimate",
        json={
            "origin": {"lat": 53.5461, "lng": -113.4938},
            "dest": {"lat": 53.6, "lng": -113.7},
            "depart_at": "2024-06-01T10:00:00Z",
            "mode": "driving",
        },
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "heuristic"
    assert payload["cached"] is False
    assert payload["duration_min"] >= 5
    assert payload["base_duration_min"] >= 5
    assert payload["duration_min"] == payload["base_duration_min"]
    assert payload["adjustments"] == []


@pytest.mark.anyio
async def test_dispatcher_route_estimate_forbidden_for_viewer(client):
    response = client.post(
        "/v1/admin/dispatcher/routes/estimate",
        json={
            "origin": {"lat": 53.5461, "lng": -113.4938},
            "dest": {"lat": 53.558, "lng": -113.473},
            "mode": "driving",
        },
        headers=_basic_auth("viewer", "viewpass"),
    )

    assert response.status_code == 403
