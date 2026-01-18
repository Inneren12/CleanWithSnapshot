import base64
from datetime import datetime, timezone
import uuid

import pytest

from app.domain.feature_modules import service as feature_service
from app.settings import settings


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _create_lead(client, org_header: dict[str, str] | None = None) -> str:
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
        headers=org_header,
    )
    assert estimate_response.status_code == 200
    payload = {
        "name": "Attribution Test",
        "phone": "780-555-0102",
        "address": "200 Test Street",
        "preferred_dates": ["Tue afternoon"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": estimate_response.json(),
    }
    lead_response = client.post("/v1/leads", json=payload, headers=org_header)
    assert lead_response.status_code == 201
    return lead_response.json()["lead_id"]


def _enable_attribution(async_session_maker, org_id: uuid.UUID) -> None:
    async def _apply() -> None:
        async with async_session_maker() as session:
            await feature_service.upsert_org_feature_overrides(
                session,
                org_id,
                {"analytics.attribution_multitouch": True},
            )
            await session.commit()

    import asyncio

    asyncio.run(_apply())


def test_lead_touchpoints_ordering_and_split(client, async_session_maker):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    _enable_attribution(async_session_maker, settings.default_org_id)

    lead_id = _create_lead(client)
    headers = _basic_auth_header("admin", "secret")

    touchpoints = [
        {
            "occurred_at": "2026-01-01T10:00:00Z",
            "channel": "Email",
        },
        {
            "occurred_at": "2026-01-01T09:00:00Z",
            "channel": "Search",
        },
        {
            "occurred_at": "2026-01-02T12:00:00Z",
            "channel": "Direct",
        },
    ]
    for payload in touchpoints:
        response = client.post(f"/v1/admin/leads/{lead_id}/touchpoints", headers=headers, json=payload)
        assert response.status_code == 200

    attribution = client.get(f"/v1/admin/leads/{lead_id}/attribution", headers=headers)
    assert attribution.status_code == 200
    body = attribution.json()
    ordered_channels = [touchpoint["channel"] for touchpoint in body["touchpoints"]]
    assert ordered_channels == ["Search", "Email", "Direct"]

    split_weights = [entry["weight"] for entry in body["split"]]
    assert split_weights == pytest.approx([0.4, 0.3, 0.3])


def test_lead_attribution_org_scope_and_rbac(client, async_session_maker):
    original_admin_username = settings.admin_basic_username
    original_admin_password = settings.admin_basic_password
    original_accountant_username = settings.accountant_basic_username
    original_accountant_password = settings.accountant_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.accountant_basic_username = "accountant"
    settings.accountant_basic_password = "acct-secret"
    _enable_attribution(async_session_maker, settings.default_org_id)

    try:
        lead_id = _create_lead(client)
        accountant_headers = _basic_auth_header("accountant", "acct-secret")
        accountant_response = client.get(
            f"/v1/admin/leads/{lead_id}/attribution",
            headers=accountant_headers,
        )
        assert accountant_response.status_code == 403

        other_org_id = uuid.uuid4()
        other_org_headers = {"X-Test-Org": str(other_org_id)}
        other_lead_id = _create_lead(client, org_header=other_org_headers)
        admin_headers = _basic_auth_header("admin", "secret")
        other_response = client.get(f"/v1/admin/leads/{other_lead_id}/attribution", headers=admin_headers)
        assert other_response.status_code == 404
    finally:
        settings.admin_basic_username = original_admin_username
        settings.admin_basic_password = original_admin_password
        settings.accountant_basic_username = original_accountant_username
        settings.accountant_basic_password = original_accountant_password
