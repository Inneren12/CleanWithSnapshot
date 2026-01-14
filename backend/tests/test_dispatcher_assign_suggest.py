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


async def _make_address(session, client_id: str, *, lat: float, lng: float) -> ClientAddress:
    address = ClientAddress(
        client_id=client_id,
        label="Home",
        address_text="123 Main St",
        lat=lat,
        lng=lng,
    )
    session.add(address)
    await session.flush()
    return address


@pytest.mark.anyio
async def test_suggestions_exclude_conflicting_worker(client, async_session_maker):
    starts_at = dt.datetime(2024, 6, 10, 10, 0, tzinfo=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(email="client@example.com", name="Client One", phone="+1 555-0100")
        session.add(client_user)
        await session.flush()
        address = await _make_address(session, client_user.client_id, lat=53.5461, lng=-113.4938)
        worker_conflict = Worker(name="Busy Worker", phone="+1 555-0200", team_id=team.team_id)
        worker_free = Worker(name="Free Worker", phone="+1 555-0201", team_id=team.team_id)
        session.add_all([worker_conflict, worker_free])
        await session.flush()
        booking = Booking(
            team_id=team.team_id,
            starts_at=starts_at,
            duration_minutes=60,
            status="CONFIRMED",
            client_id=client_user.client_id,
            address_id=address.address_id,
        )
        session.add(booking)
        session.add(
            Booking(
                team_id=team.team_id,
                starts_at=starts_at + dt.timedelta(minutes=30),
                duration_minutes=60,
                status="CONFIRMED",
                assigned_worker_id=worker_conflict.worker_id,
            )
        )
        await session.commit()

    response = client.get(
        "/v1/admin/dispatcher/assign/suggest",
        params={"booking_id": booking.booking_id, "limit": 5},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    payload = response.json()
    worker_ids = [entry["worker_id"] for entry in payload["suggestions"]]
    assert worker_conflict.worker_id not in worker_ids
    assert worker_free.worker_id in worker_ids


@pytest.mark.anyio
async def test_suggestions_are_ranked_stably(client, async_session_maker):
    starts_at = dt.datetime(2024, 6, 12, 12, 0, tzinfo=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(email="client2@example.com", name="Client Two", phone="+1 555-0102")
        session.add(client_user)
        await session.flush()
        target_address = await _make_address(session, client_user.client_id, lat=53.5461, lng=-113.4938)
        worker_close = Worker(
            name="Close Worker",
            phone="+1 555-0202",
            team_id=team.team_id,
            rating_avg=4.0,
        )
        worker_far = Worker(
            name="Far Worker",
            phone="+1 555-0203",
            team_id=team.team_id,
            rating_avg=5.0,
        )
        session.add_all([worker_close, worker_far])
        await session.flush()
        booking = Booking(
            team_id=team.team_id,
            starts_at=starts_at,
            duration_minutes=90,
            status="CONFIRMED",
            client_id=client_user.client_id,
            address_id=target_address.address_id,
        )
        session.add(booking)
        close_origin = await _make_address(session, client_user.client_id, lat=53.5465, lng=-113.4939)
        far_origin = await _make_address(session, client_user.client_id, lat=53.60, lng=-113.70)
        session.add_all(
            [
                Booking(
                    team_id=team.team_id,
                    starts_at=starts_at - dt.timedelta(hours=2),
                    duration_minutes=60,
                    status="CONFIRMED",
                    assigned_worker_id=worker_close.worker_id,
                    address_id=close_origin.address_id,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=starts_at - dt.timedelta(hours=2),
                    duration_minutes=60,
                    status="CONFIRMED",
                    assigned_worker_id=worker_far.worker_id,
                    address_id=far_origin.address_id,
                ),
            ]
        )
        await session.commit()

    response = client.get(
        "/v1/admin/dispatcher/assign/suggest",
        params={"booking_id": booking.booking_id, "limit": 5},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    payload = response.json()
    suggestions = payload["suggestions"]
    assert suggestions[0]["worker_id"] == worker_close.worker_id
    assert suggestions[1]["worker_id"] == worker_far.worker_id


@pytest.mark.anyio
async def test_suggestions_respect_org_scope(client, async_session_maker):
    starts_at = dt.datetime(2024, 6, 14, 14, 0, tzinfo=dt.timezone.utc)
    other_org = uuid.uuid4()
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(email="client3@example.com", name="Client Three", phone="+1 555-0103")
        session.add(client_user)
        await session.flush()
        target_address = await _make_address(session, client_user.client_id, lat=53.5461, lng=-113.4938)
        worker_default = Worker(name="Default Worker", phone="+1 555-0204", team_id=team.team_id)
        session.add(worker_default)
        await ensure_org(session, other_org, name="Other Org")
        other_team = Team(name="Other Team", org_id=other_org)
        session.add(other_team)
        await session.flush()
        session.add(
            Worker(name="Other Worker", phone="+1 555-0205", team_id=other_team.team_id, org_id=other_org)
        )
        booking = Booking(
            team_id=team.team_id,
            starts_at=starts_at,
            duration_minutes=45,
            status="CONFIRMED",
            client_id=client_user.client_id,
            address_id=target_address.address_id,
        )
        session.add(booking)
        await session.commit()

    response = client.get(
        "/v1/admin/dispatcher/assign/suggest",
        params={"booking_id": booking.booking_id, "limit": 5},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    payload = response.json()
    worker_ids = [entry["worker_id"] for entry in payload["suggestions"]]
    assert worker_default.worker_id in worker_ids
    assert len(worker_ids) == 1
