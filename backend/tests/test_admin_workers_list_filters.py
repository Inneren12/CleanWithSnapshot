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
async def test_admin_workers_list_filters(client, async_session_maker):
    now = dt.datetime.now(tz=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await session.flush()

        worker_free = Worker(
            name="Free Worker",
            phone="+1 555-1000",
            team_id=team.team_id,
            skills=["deep"],
            rating_avg=4.6,
            rating_count=12,
            is_active=True,
        )
        worker_busy_primary = Worker(
            name="Busy Primary",
            phone="+1 555-2000",
            team_id=team.team_id,
            skills=["standard"],
            rating_avg=4.2,
            rating_count=5,
            is_active=True,
        )
        worker_busy_crew = Worker(
            name="Busy Crew",
            phone="+1 555-3000",
            team_id=team.team_id,
            skills=["move_out"],
            rating_avg=3.5,
            rating_count=2,
            is_active=True,
        )
        worker_archived = Worker(
            name="Archived Worker",
            phone="+1 555-4000",
            team_id=team.team_id,
            archived_at=now,
            is_active=False,
        )
        worker_inactive = Worker(
            name="Inactive Worker",
            phone="+1 555-5000",
            team_id=team.team_id,
            is_active=False,
        )
        session.add_all(
            [worker_free, worker_busy_primary, worker_busy_crew, worker_archived, worker_inactive]
        )
        await session.flush()

        booking = Booking(
            team_id=team.team_id,
            starts_at=now - dt.timedelta(minutes=30),
            duration_minutes=120,
            status="CONFIRMED",
            assigned_worker_id=worker_busy_primary.worker_id,
        )
        session.add(booking)
        await session.flush()
        session.add(BookingWorker(booking_id=booking.booking_id, worker_id=worker_busy_crew.worker_id))
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    list_resp = client.get("/v1/admin/ui/workers", headers=headers)
    assert list_resp.status_code == 200
    assert "Inactive Worker" not in list_resp.text

    status_resp = client.get("/v1/admin/ui/workers?status=archived", headers=headers)
    assert "Archived Worker" in status_resp.text
    assert "Free Worker" not in status_resp.text

    skill_resp = client.get("/v1/admin/ui/workers?skill=deep", headers=headers)
    assert "Free Worker" in skill_resp.text
    assert "Busy Primary" not in skill_resp.text

    rating_resp = client.get("/v1/admin/ui/workers?rating_min=4.5", headers=headers)
    assert "Free Worker" in rating_resp.text
    assert "Busy Primary" not in rating_resp.text

    busy_resp = client.get("/v1/admin/ui/workers?availability=busy", headers=headers)
    assert "Busy Primary" in busy_resp.text
    assert "Busy Crew" in busy_resp.text
    assert "Free Worker" not in busy_resp.text

    free_resp = client.get("/v1/admin/ui/workers?availability=free", headers=headers)
    assert "Free Worker" in free_resp.text
    assert "Busy Primary" not in free_resp.text

    inactive_resp = client.get("/v1/admin/ui/workers?active_state=inactive", headers=headers)
    assert "Inactive Worker" in inactive_resp.text
    assert "Free Worker" not in inactive_resp.text

    ru_headers = {**headers, "accept-language": "ru"}
    translated_resp = client.get("/v1/admin/ui/workers", headers=ru_headers)
    assert "Детали" in translated_resp.text
