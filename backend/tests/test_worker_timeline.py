import base64
import datetime as dt

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import ensure_default_team
from app.domain.org_settings import service as org_settings_service
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
async def test_worker_timeline_aggregates_in_org_timezone(client, async_session_maker):
    start_date = dt.date(2024, 5, 6)
    end_date = dt.date(2024, 5, 7)
    booking_local_may6 = dt.datetime(2024, 5, 6, 14, 0, tzinfo=dt.timezone.utc)
    booking_local_may7 = dt.datetime(2024, 5, 7, 16, 0, tzinfo=dt.timezone.utc)
    booking_outside = dt.datetime(2024, 5, 6, 5, 0, tzinfo=dt.timezone.utc)

    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        worker_one = Worker(name="Worker One", phone="+1 555-0100", team_id=team.team_id)
        worker_two = Worker(name="Worker Two", phone="+1 555-0101", team_id=team.team_id)
        session.add_all([worker_one, worker_two])
        await session.flush()

        org_settings = await org_settings_service.get_or_create_org_settings(
            session, settings.default_org_id
        )
        org_settings.timezone = "America/Edmonton"

        session.add_all(
            [
                Booking(
                    team_id=team.team_id,
                    starts_at=booking_local_may6,
                    duration_minutes=120,
                    status="CONFIRMED",
                    assigned_worker_id=worker_one.worker_id,
                    base_charge_cents=20000,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=booking_local_may7,
                    duration_minutes=60,
                    status="CONFIRMED",
                    assigned_worker_id=worker_one.worker_id,
                    base_charge_cents=10000,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=booking_outside,
                    duration_minutes=90,
                    status="CONFIRMED",
                    assigned_worker_id=worker_one.worker_id,
                    base_charge_cents=5000,
                ),
            ]
        )
        await session.commit()

    response = client.get(
        "/v1/admin/schedule/worker_timeline",
        params={"from": start_date.isoformat(), "to": end_date.isoformat()},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["from_date"] == start_date.isoformat()
    assert payload["to_date"] == end_date.isoformat()
    assert payload["days"] == [start_date.isoformat(), end_date.isoformat()]

    workers = {worker["worker_id"]: worker for worker in payload["workers"]}
    assert worker_one.worker_id in workers
    assert worker_two.worker_id in workers

    worker_one_payload = workers[worker_one.worker_id]
    day_entries = {entry["date"]: entry for entry in worker_one_payload["days"]}
    assert day_entries[start_date.isoformat()]["booked_minutes"] == 120
    assert day_entries[start_date.isoformat()]["booking_count"] == 1
    assert day_entries[start_date.isoformat()]["revenue_cents"] == 20000
    assert day_entries[end_date.isoformat()]["booked_minutes"] == 60
    assert day_entries[end_date.isoformat()]["booking_count"] == 1
    assert day_entries[end_date.isoformat()]["revenue_cents"] == 10000

    worker_two_payload = workers[worker_two.worker_id]
    day_two_entries = {entry["date"]: entry for entry in worker_two_payload["days"]}
    assert day_two_entries[start_date.isoformat()]["booking_count"] == 0
    assert day_two_entries[end_date.isoformat()]["booking_count"] == 0

    assert payload["totals"]["booked_minutes"] == 180
    assert payload["totals"]["booking_count"] == 2
    assert payload["totals"]["revenue_cents"] == 30000
