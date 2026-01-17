import base64
from datetime import datetime, timedelta, timezone

from app.domain.leads.db_models import Lead
from app.settings import settings


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _create_lead(client) -> str:
    estimate_response = client.post(
        "/v1/estimate",
        json={
            "beds": 1,
            "baths": 1,
            "cleaning_type": "standard",
            "heavy_grease": False,
            "multi_floor": False,
            "frequency": "one_time",
            "add_ons": {},
        },
    )
    assert estimate_response.status_code == 200
    payload = {
        "name": "Quote Lead",
        "phone": "780-555-1111",
        "address": "100 Quote Road",
        "preferred_dates": ["Wed afternoon"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": estimate_response.json(),
    }
    lead_response = client.post("/v1/leads", json=payload)
    assert lead_response.status_code == 201
    return lead_response.json()["lead_id"]


def test_admin_quote_create_marks_expired(client):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    lead_id = _create_lead(client)
    headers = _basic_auth_header("admin", "secret")

    expires_at = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
    response = client.post(
        f"/v1/admin/leads/{lead_id}/quotes",
        headers=headers,
        json={
            "amount": 12500,
            "currency": "CAD",
            "status": "SENT",
            "expires_at": expires_at,
        },
    )
    assert response.status_code == 200

    list_response = client.get(f"/v1/admin/leads/{lead_id}/quotes", headers=headers)
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert items
    assert items[0]["status"] == "EXPIRED"


def test_lead_loss_reason_stored(client, async_session_maker):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    lead_id = _create_lead(client)
    headers = _basic_auth_header("admin", "secret")

    response = client.patch(
        f"/v1/admin/leads/{lead_id}",
        headers=headers,
        json={"status": "LOST", "loss_reason": "Budget too high"},
    )
    assert response.status_code == 200
    assert response.json()["loss_reason"] == "Budget too high"

    async def _fetch_loss_reason() -> str | None:
        async with async_session_maker() as session:
            lead = await session.get(Lead, lead_id)
            assert lead
            return lead.loss_reason

    import asyncio

    assert asyncio.run(_fetch_loss_reason()) == "Budget too high"


def test_viewer_cannot_create_lead_quote(client):
    original_admin_username = settings.admin_basic_username
    original_admin_password = settings.admin_basic_password
    original_viewer_username = settings.viewer_basic_username
    original_viewer_password = settings.viewer_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.viewer_basic_username = "viewer"
    settings.viewer_basic_password = "view-secret"

    try:
        lead_id = _create_lead(client)
        viewer_headers = _basic_auth_header("viewer", "view-secret")

        response = client.post(
            f"/v1/admin/leads/{lead_id}/quotes",
            headers=viewer_headers,
            json={"amount": 9900, "currency": "CAD", "status": "DRAFT"},
        )
        assert response.status_code == 403
    finally:
        settings.admin_basic_username = original_admin_username
        settings.admin_basic_password = original_admin_password
        settings.viewer_basic_username = original_viewer_username
        settings.viewer_basic_password = original_viewer_password
