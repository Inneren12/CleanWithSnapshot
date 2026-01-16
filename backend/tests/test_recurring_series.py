import base64
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import ensure_default_team
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.org_settings import service as org_settings_service
from app.domain.pricing_settings.db_models import ServiceType
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _admin_creds():
    original = {
        "admin_basic_username": settings.admin_basic_username,
        "admin_basic_password": settings.admin_basic_password,
    }
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.mark.anyio
async def test_recurring_generation_creates_bookings(client, async_session_maker):
    org_tz = ZoneInfo(org_settings_service.DEFAULT_TIMEZONE)
    now_local = dt.datetime.now(org_tz)
    starts_on = now_local.date() + dt.timedelta(days=1)

    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(email="client@example.com", name="Test Client")
        session.add(client_user)
        await session.flush()
        address = ClientAddress(
            client_id=client_user.client_id,
            label="Home",
            address_text="123 Main St",
        )
        service_type = ServiceType(name="Standard", active=True, default_duration_minutes=120)
        worker = Worker(name="Worker Bee", phone="+1 555-0101", team_id=team.team_id)
        session.add_all([address, service_type, worker])
        await session.commit()

    payload = {
        "client_id": client_user.client_id,
        "address_id": address.address_id,
        "service_type_id": service_type.service_type_id,
        "preferred_team_id": team.team_id,
        "preferred_worker_id": worker.worker_id,
        "status": "active",
        "starts_on": starts_on.isoformat(),
        "start_time": "09:00:00",
        "frequency": "weekly",
        "interval": 1,
        "by_weekday": [starts_on.weekday()],
        "duration_minutes": 90,
        "horizon_days": 6,
    }

    create_response = client.post(
        "/v1/admin/recurring-series",
        json=payload,
        headers=_basic_auth("admin", "secret"),
    )
    assert create_response.status_code == 200
    series_id = create_response.json()["series_id"]

    generate_response = client.post(
        f"/v1/admin/recurring-series/{series_id}/generate",
        json={},
        headers=_basic_auth("admin", "secret"),
    )
    assert generate_response.status_code == 200
    payload = generate_response.json()
    assert len(payload["created"]) == 1

    booking_id = payload["created"][0]["booking_id"]
    async with async_session_maker() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.recurring_series_id is not None
        assert booking.scheduled_date == starts_on


@pytest.mark.anyio
async def test_recurring_pause_blocks_generation(client, async_session_maker):
    org_tz = ZoneInfo(org_settings_service.DEFAULT_TIMEZONE)
    now_local = dt.datetime.now(org_tz)
    starts_on = now_local.date() + dt.timedelta(days=1)

    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(email="pause@example.com")
        session.add(client_user)
        await session.flush()
        address = ClientAddress(
            client_id=client_user.client_id,
            label="Home",
            address_text="456 Main St",
        )
        service_type = ServiceType(name="Pause Standard", active=True, default_duration_minutes=60)
        session.add_all([address, service_type])
        await session.commit()

    payload = {
        "client_id": client_user.client_id,
        "address_id": address.address_id,
        "service_type_id": service_type.service_type_id,
        "preferred_team_id": team.team_id,
        "status": "active",
        "starts_on": starts_on.isoformat(),
        "start_time": "10:00:00",
        "frequency": "weekly",
        "interval": 1,
        "by_weekday": [starts_on.weekday()],
        "duration_minutes": 60,
        "horizon_days": 6,
    }
    create_response = client.post(
        "/v1/admin/recurring-series",
        json=payload,
        headers=_basic_auth("admin", "secret"),
    )
    assert create_response.status_code == 200
    series_id = create_response.json()["series_id"]

    pause_response = client.patch(
        f"/v1/admin/recurring-series/{series_id}",
        json={"status": "paused"},
        headers=_basic_auth("admin", "secret"),
    )
    assert pause_response.status_code == 200

    generate_response = client.post(
        f"/v1/admin/recurring-series/{series_id}/generate",
        json={},
        headers=_basic_auth("admin", "secret"),
    )
    assert generate_response.status_code == 409


@pytest.mark.anyio
async def test_recurring_conflict_skips_booking(client, async_session_maker):
    org_tz = ZoneInfo(org_settings_service.DEFAULT_TIMEZONE)
    now_local = dt.datetime.now(org_tz)
    starts_on = now_local.date() + dt.timedelta(days=1)
    starts_at = dt.datetime.combine(starts_on, dt.time(9, 0), tzinfo=org_tz).astimezone(dt.timezone.utc)

    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(email="conflict@example.com")
        session.add(client_user)
        await session.flush()
        address = ClientAddress(
            client_id=client_user.client_id,
            label="Home",
            address_text="789 Main St",
        )
        service_type = ServiceType(name="Conflict Standard", active=True, default_duration_minutes=60)
        session.add_all([address, service_type])
        await session.flush()
        booking = Booking(
            team_id=team.team_id,
            client_id=client_user.client_id,
            address_id=address.address_id,
            starts_at=starts_at,
            duration_minutes=60,
            status="CONFIRMED",
        )
        session.add(booking)
        await session.commit()

    payload = {
        "client_id": client_user.client_id,
        "address_id": address.address_id,
        "service_type_id": service_type.service_type_id,
        "preferred_team_id": team.team_id,
        "status": "active",
        "starts_on": starts_on.isoformat(),
        "start_time": "09:00:00",
        "frequency": "weekly",
        "interval": 1,
        "by_weekday": [starts_on.weekday()],
        "duration_minutes": 60,
        "horizon_days": 6,
    }
    create_response = client.post(
        "/v1/admin/recurring-series",
        json=payload,
        headers=_basic_auth("admin", "secret"),
    )
    assert create_response.status_code == 200
    series_id = create_response.json()["series_id"]

    generate_response = client.post(
        f"/v1/admin/recurring-series/{series_id}/generate",
        json={},
        headers=_basic_auth("admin", "secret"),
    )
    assert generate_response.status_code == 200
    payload = generate_response.json()
    assert payload["created"] == []
    assert len(payload["conflicted"]) == 1
