import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.bookings.service import ensure_default_team, LOCAL_TZ
from app.domain.clients.db_models import ClientUser
from app.domain.leads.db_models import Lead
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _estimate_payload() -> dict:
    return {
        "beds": 1,
        "baths": 1,
        "cleaning_type": "standard",
        "heavy_grease": False,
        "multi_floor": False,
        "frequency": "one_time",
        "add_ons": {},
    }


def _lead_payload(client) -> dict:
    estimate_response = client.post("/v1/estimate", json=_estimate_payload())
    assert estimate_response.status_code == 200
    return {
        "name": "Required Lead",
        "phone": "780-555-1234",
        "address": "10 Required Lane",
        "preferred_dates": ["Mon morning"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": estimate_response.json(),
    }


@pytest.mark.anyio
async def test_lead_create_rejects_missing_fields(client):
    payload = _lead_payload(client)
    payload.pop("address")
    response = client.post("/v1/leads", json=payload)
    assert response.status_code == 422

    payload = _lead_payload(client)
    payload["preferred_dates"] = []
    response = client.post("/v1/leads", json=payload)
    assert response.status_code == 422


def test_booking_requires_lead_contact(client, async_session_maker):
    start_local = datetime.now(tz=LOCAL_TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    starts_at = start_local.astimezone(timezone.utc).isoformat()

    response = client.post(
        "/v1/bookings",
        json={"starts_at": starts_at, "time_on_site_hours": 1.5},
    )
    assert response.status_code == 422

    async def _seed_lead() -> str:
        async with async_session_maker() as session:
            lead = Lead(
                name="Missing Address",
                phone="780-555-0000",
                preferred_dates=["Tue"],
                structured_inputs={"beds": 1, "baths": 1, "cleaning_type": "standard"},
                estimate_snapshot={
                    "pricing_config_version": "v1",
                    "config_hash": "hash",
                    "total_before_tax": 100.0,
                },
                pricing_config_version="v1",
                config_hash="hash",
                status="NEW",
            )
            session.add(lead)
            await session.commit()
            return lead.lead_id

    import asyncio

    lead_id = asyncio.run(_seed_lead())
    response = client.post(
        "/v1/bookings",
        json={"starts_at": starts_at, "time_on_site_hours": 1.5, "lead_id": lead_id},
    )
    assert response.status_code == 422


def test_admin_booking_requires_client_contact(client, async_session_maker):
    original_username = settings.dispatcher_basic_username
    original_password = settings.dispatcher_basic_password
    settings.dispatcher_basic_username = "dispatch"
    settings.dispatcher_basic_password = "secret"
    headers = _basic_auth("dispatch", "secret")

    async def _seed_client() -> tuple[int, str]:
        async with async_session_maker() as session:
            team = await ensure_default_team(session)
            client_user = ClientUser(
                email="admin-booking@example.com",
                name="",
                phone=None,
                address=None,
                org_id=team.org_id,
            )
            session.add(client_user)
            await session.commit()
            await session.refresh(client_user)
            return team.team_id, client_user.client_id

    import asyncio

    team_id, client_id = asyncio.run(_seed_client())
    starts_at = datetime.now(tz=timezone.utc).isoformat()

    try:
        response = client.post(
            "/v1/admin/ui/bookings/create",
            headers=headers,
            data={
                "team_id": str(team_id),
                "client_id": client_id,
                "starts_at": starts_at,
                "duration_minutes": "60",
            },
            follow_redirects=False,
        )
        assert response.status_code == 400
    finally:
        settings.dispatcher_basic_username = original_username
        settings.dispatcher_basic_password = original_password


def test_public_booking_rejects_blocked_client(client, async_session_maker):
    start_local = datetime.now(tz=LOCAL_TZ).replace(hour=9, minute=0, second=0, microsecond=0)
    starts_at = start_local.astimezone(timezone.utc).isoformat()
    blocked_email = "blocked-client@example.com"

    async def _seed_blocked_lead() -> str:
        async with async_session_maker() as session:
            session.add(
                ClientUser(
                    email=blocked_email,
                    name="Blocked Client",
                    phone="780-555-8888",
                    address="88 Blocked Way",
                    is_blocked=True,
                    org_id=settings.default_org_id,
                )
            )
            lead = Lead(
                name="Blocked Lead",
                email=blocked_email,
                phone="780-555-1234",
                address="77 Blocked Lane",
                preferred_dates=["Wed"],
                structured_inputs={"beds": 1, "baths": 1, "cleaning_type": "standard"},
                estimate_snapshot={
                    "pricing_config_version": "v1",
                    "config_hash": "hash",
                    "total_before_tax": 120.0,
                },
                pricing_config_version="v1",
                config_hash="hash",
                status="NEW",
            )
            session.add(lead)
            await session.commit()
            return lead.lead_id

    import asyncio

    lead_id = asyncio.run(_seed_blocked_lead())
    response = client.post(
        "/v1/bookings",
        json={"starts_at": starts_at, "time_on_site_hours": 1.5, "lead_id": lead_id},
    )
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Client is blocked from booking."
