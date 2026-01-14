import base64
import datetime as dt
import uuid

import pytest

from app.domain.bookings.db_models import Booking, Team
from app.domain.bookings.service import ensure_default_team
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.saas.service import ensure_org
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
async def test_admin_can_read_dispatcher_board(client, async_session_maker):
    target_date = dt.date(2024, 5, 10)
    starts_at = dt.datetime(2024, 5, 10, 15, 0, tzinfo=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(
            email="client@example.com",
            name="Jane Client",
            phone="+1 555-0100",
        )
        session.add(client_user)
        await session.flush()
        address = ClientAddress(
            client_id=client_user.client_id,
            label="Home",
            address_text="123 Main St",
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
        )
        session.add(booking)
        await session.commit()

    response = client.get(
        "/v1/admin/dispatcher/board",
        params={"date": target_date.isoformat(), "tz": "America/Edmonton"},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["bookings"][0]["booking_id"] == booking.booking_id
    assert payload["bookings"][0]["client"]["name"] == "Jane Client"
    assert payload["bookings"][0]["assigned_worker"]["display_name"] == "Worker Bee"
    assert payload["workers"][0]["display_name"] == "Worker Bee"


@pytest.mark.anyio
async def test_dispatcher_board_non_admin_forbidden(client):
    response = client.get(
        "/v1/admin/dispatcher/board",
        params={"date": "2024-05-10", "tz": "America/Edmonton"},
        headers=_basic_auth("viewer", "viewpass"),
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_dispatcher_board_org_isolation(client, async_session_maker):
    target_date = dt.date(2024, 5, 10)
    starts_at = dt.datetime(2024, 5, 10, 15, 0, tzinfo=dt.timezone.utc)
    other_org = uuid.uuid4()
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        session.add(
            Booking(
                team_id=team.team_id,
                starts_at=starts_at,
                duration_minutes=60,
                status="CONFIRMED",
            )
        )
        await ensure_org(session, other_org, name="Other Org")
        other_team = Team(name="Other Team", org_id=other_org)
        session.add(other_team)
        await session.flush()
        session.add(
            Booking(
                team_id=other_team.team_id,
                org_id=other_org,
                starts_at=starts_at,
                duration_minutes=45,
                status="CONFIRMED",
            )
        )
        await session.commit()

    response_default = client.get(
        "/v1/admin/dispatcher/board",
        params={"date": target_date.isoformat(), "tz": "America/Edmonton"},
        headers=_basic_auth("admin", "secret"),
    )
    response_other = client.get(
        "/v1/admin/dispatcher/board",
        params={"date": target_date.isoformat(), "tz": "America/Edmonton"},
        headers={**_basic_auth("admin", "secret"), "X-Test-Org": str(other_org)},
    )

    assert response_default.status_code == 200
    assert response_other.status_code == 200
    assert len(response_default.json()["bookings"]) == 1
    assert len(response_other.json()["bookings"]) == 1


@pytest.mark.anyio
async def test_dispatcher_board_timezone_window(client, async_session_maker):
    target_date = dt.date(2024, 5, 10)
    starts_before = dt.datetime(2024, 5, 10, 5, 30, tzinfo=dt.timezone.utc)
    starts_inside = dt.datetime(2024, 5, 10, 6, 30, tzinfo=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        session.add_all(
            [
                Booking(
                    team_id=team.team_id,
                    starts_at=starts_before,
                    duration_minutes=30,
                    status="CONFIRMED",
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=starts_inside,
                    duration_minutes=30,
                    status="CONFIRMED",
                ),
            ]
        )
        await session.commit()

    response = client.get(
        "/v1/admin/dispatcher/board",
        params={"date": target_date.isoformat(), "tz": "America/Edmonton"},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    bookings = response.json()["bookings"]
    assert len(bookings) == 1
    assert bookings[0]["starts_at"].startswith("2024-05-10T06:30:00")
