import base64
import datetime as dt

import pytest

from app.domain.bookings.db_models import Booking, BookingWorker
from app.domain.bookings.service import ensure_default_team
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _reset_dispatch_creds():
    original = {
        "dispatcher_basic_username": settings.dispatcher_basic_username,
        "dispatcher_basic_password": settings.dispatcher_basic_password,
    }
    settings.dispatcher_basic_username = "dispatch"
    settings.dispatcher_basic_password = "secret"
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.mark.anyio
async def test_admin_workers_availability_heatmap(client, async_session_maker):
    start_date = dt.date(2024, 1, 1)
    start_dt = dt.datetime(2024, 1, 1, 9, 0, tzinfo=dt.timezone.utc)
    second_dt = dt.datetime(2024, 1, 2, 10, 0, tzinfo=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await session.flush()

        worker_deep = Worker(
            name="Deep Cleaner",
            phone="+1 555-5000",
            team_id=team.team_id,
            skills=["deep"],
            is_active=True,
        )
        worker_windows = Worker(
            name="Window Cleaner",
            phone="+1 555-6000",
            team_id=team.team_id,
            skills=["windows"],
            is_active=True,
        )
        session.add_all([worker_deep, worker_windows])
        await session.flush()

        booking_primary = Booking(
            team_id=team.team_id,
            starts_at=start_dt,
            duration_minutes=120,
            status="CONFIRMED",
            assigned_worker_id=worker_deep.worker_id,
        )
        booking_crew = Booking(
            team_id=team.team_id,
            starts_at=second_dt,
            duration_minutes=90,
            status="CONFIRMED",
            assigned_worker_id=worker_deep.worker_id,
        )
        session.add_all([booking_primary, booking_crew])
        await session.flush()
        session.add(
            BookingWorker(
                booking_id=booking_crew.booking_id,
                worker_id=worker_windows.worker_id,
            )
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    response = client.get(
        f"/v1/admin/ui/workers/availability?start={start_date.isoformat()}",
        headers=headers,
    )
    assert response.status_code == 200
    assert "Deep Cleaner" in response.text
    assert "Window Cleaner" in response.text
    assert "120m" in response.text
    assert "90m" in response.text

    filtered = client.get(
        f"/v1/admin/ui/workers/availability?start={start_date.isoformat()}&skill=deep",
        headers=headers,
    )
    assert "Deep Cleaner" in filtered.text
    assert "Window Cleaner" not in filtered.text
