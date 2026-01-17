import base64
import time
import uuid

import pytest

from app.domain.saas.db_models import Organization
from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def admin_credentials():
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.viewer_basic_username = "viewer"
    settings.viewer_basic_password = "view-secret"
    yield


def _lead_payload(client) -> dict:
    estimate_response = client.post(
        "/v1/estimate",
        json={
            "beds": 2,
            "baths": 1,
            "cleaning_type": "standard",
            "heavy_grease": False,
            "multi_floor": False,
            "frequency": "one_time",
            "add_ons": {},
        },
    )
    assert estimate_response.status_code == 200
    return {
        "name": "Timeline Lead",
        "phone": "780-555-0101",
        "email": "lead@example.com",
        "address": "123 Timeline Rd",
        "preferred_dates": ["Tue afternoon"],
        "structured_inputs": {"beds": 2, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": estimate_response.json(),
    }


def _create_lead(client, headers: dict[str, str] | None = None) -> str:
    response = client.post("/v1/leads", json=_lead_payload(client), headers=headers or {})
    assert response.status_code == 201
    return response.json()["lead_id"]


def test_lead_detail_timeline_orders_latest_first(client):
    lead_id = _create_lead(client)
    headers = _auth_headers("admin", "secret")
    time.sleep(1.1)

    first_event = client.post(
        f"/v1/admin/leads/{lead_id}/timeline",
        headers=headers,
        json={"action": "Quote sent", "note": "Estimate delivered"},
    )
    assert first_event.status_code == 200
    time.sleep(1.1)

    status_update = client.patch(
        f"/v1/admin/leads/{lead_id}",
        headers=headers,
        json={"status": "CONTACTED"},
    )
    assert status_update.status_code == 200
    time.sleep(1.1)

    detail = client.get(f"/v1/admin/leads/{lead_id}", headers=headers)
    assert detail.status_code == 200
    timeline = detail.json()["timeline"]

    assert timeline[0]["action"] == "Status set to CONTACTED"
    assert timeline[1]["action"] == "Quote sent"
    assert timeline[-1]["event_type"] == "lead_created"


def test_lead_timeline_rbac_enforced(client):
    lead_id = _create_lead(client)
    viewer_headers = _auth_headers("viewer", "view-secret")

    detail = client.get(f"/v1/admin/leads/{lead_id}", headers=viewer_headers)
    assert detail.status_code == 200

    post = client.post(
        f"/v1/admin/leads/{lead_id}/timeline",
        headers=viewer_headers,
        json={"action": "Contacted"},
    )
    assert post.status_code == 403


@pytest.mark.anyio
async def test_lead_timeline_org_scoped(client, async_session_maker):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    async with async_session_maker() as session:
        session.add_all(
            [
                Organization(org_id=org_a, name="Org A"),
                Organization(org_id=org_b, name="Org B"),
            ]
        )
        await session.commit()

    lead_id = _create_lead(client, headers={"X-Test-Org": str(org_a)})
    headers_org_b = {**_auth_headers("admin", "secret"), "X-Test-Org": str(org_b)}

    detail_other_org = client.get(f"/v1/admin/leads/{lead_id}", headers=headers_org_b)
    assert detail_other_org.status_code == 404
