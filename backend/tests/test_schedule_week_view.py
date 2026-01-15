import base64
import datetime as dt

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import ensure_default_team
from app.domain.clients.db_models import ClientAddress, ClientUser
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
        "viewer_basic_username": settings.viewer_basic_username,
        "viewer_basic_password": settings.viewer_basic_password,
    }
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.viewer_basic_username = "viewer"
    settings.viewer_basic_password = "viewpass"
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.mark.anyio
async def test_schedule_range_returns_bookings(client, async_session_maker):
    target_date = dt.date(2024, 5, 6)
    starts_at = dt.datetime(2024, 5, 6, 14, 0, tzinfo=dt.timezone.utc)
    outside_at = dt.datetime(2024, 5, 20, 14, 0, tzinfo=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(email="client@example.com", name="Jane Client", address="123 Main St")
        session.add(client_user)
        await session.flush()
        address = ClientAddress(
            client_id=client_user.client_id,
            label="Home",
            address_text="123 Main St, City",
        )
        worker = Worker(name="Worker Bee", phone="+1 555-0200", team_id=team.team_id)
        session.add_all([address, worker])
        await session.flush()
        booking = Booking(
            team_id=team.team_id,
            starts_at=starts_at,
            duration_minutes=120,
            status="CONFIRMED",
            client_id=client_user.client_id,
            address_id=address.address_id,
            assigned_worker_id=worker.worker_id,
            base_charge_cents=15000,
        )
        outside = Booking(
            team_id=team.team_id,
            starts_at=outside_at,
            duration_minutes=60,
            status="CONFIRMED",
            client_id=client_user.client_id,
        )
        session.add_all([booking, outside])
        await session.commit()

    response = client.get(
        "/v1/admin/schedule",
        params={"from": target_date.isoformat(), "to": target_date.isoformat()},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["from_date"] == target_date.isoformat()
    assert payload["to_date"] == target_date.isoformat()
    assert len(payload["bookings"]) == 1
    booking_payload = payload["bookings"][0]
    assert booking_payload["booking_id"] == booking.booking_id
    assert booking_payload["worker_id"] == worker.worker_id
    assert booking_payload["team_id"] == team.team_id
    assert booking_payload["client_label"] == "Jane Client"
    assert booking_payload["address"] == "123 Main St, City"
    assert booking_payload["price_cents"] == 15000


@pytest.mark.anyio
async def test_update_booking_requires_assign_permission(client, async_session_maker):
    starts_at = dt.datetime(2024, 5, 6, 9, 0, tzinfo=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        booking = Booking(
            team_id=team.team_id,
            starts_at=starts_at,
            duration_minutes=60,
            status="CONFIRMED",
        )
        session.add(booking)
        await session.commit()

    response = client.patch(
        f"/v1/admin/bookings/{booking.booking_id}",
        json={"starts_at": starts_at.isoformat()},
        headers=_basic_auth("viewer", "viewpass"),
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_update_booking_conflict_rejected(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        worker = Worker(name="Worker Bee", phone="+1 555-0200", team_id=team.team_id)
        session.add(worker)
        await session.flush()
        booking_one = Booking(
            team_id=team.team_id,
            starts_at=dt.datetime(2024, 5, 6, 9, 0, tzinfo=dt.timezone.utc),
            duration_minutes=120,
            status="CONFIRMED",
            assigned_worker_id=worker.worker_id,
        )
        booking_two = Booking(
            team_id=team.team_id,
            starts_at=dt.datetime(2024, 5, 6, 12, 0, tzinfo=dt.timezone.utc),
            duration_minutes=60,
            status="CONFIRMED",
            assigned_worker_id=worker.worker_id,
        )
        session.add_all([booking_one, booking_two])
        await session.commit()

    new_start = dt.datetime(2024, 5, 6, 10, 0, tzinfo=dt.timezone.utc)
    new_end = dt.datetime(2024, 5, 6, 11, 0, tzinfo=dt.timezone.utc)
    response = client.patch(
        f"/v1/admin/bookings/{booking_two.booking_id}",
        json={"starts_at": new_start.isoformat(), "ends_at": new_end.isoformat()},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["detail"]["message"] == "conflict_with_existing_booking"
