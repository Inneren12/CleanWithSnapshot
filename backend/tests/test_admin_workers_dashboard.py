import base64
import datetime as dt

import pytest

from app.domain.bookings.db_models import Booking
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
async def test_admin_workers_dashboard_segments(client, async_session_maker):
    now = dt.datetime.now(tz=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await session.flush()

        worker_top = Worker(
            name="Top Rated",
            phone="+1 555-1000",
            team_id=team.team_id,
            skills=["deep"],
            rating_avg=4.9,
            rating_count=20,
            is_active=True,
        )
        worker_busy = Worker(
            name="Busy Bee",
            phone="+1 555-2000",
            team_id=team.team_id,
            skills=["standard"],
            rating_avg=4.1,
            rating_count=5,
            is_active=True,
        )
        worker_newbie = Worker(
            name="Newbie",
            phone="+1 555-3000",
            team_id=team.team_id,
            skills=["standard"],
            rating_avg=3.8,
            rating_count=1,
            created_at=now - dt.timedelta(days=3),
            is_active=True,
        )
        worker_problem = Worker(
            name="Problem Worker",
            phone="+1 555-4000",
            team_id=team.team_id,
            skills=["standard"],
            rating_avg=3.0,
            rating_count=2,
            is_active=True,
        )
        worker_revenue = Worker(
            name="Top Revenue",
            phone="+1 555-5000",
            team_id=team.team_id,
            skills=["deep"],
            rating_avg=4.5,
            rating_count=10,
            is_active=True,
        )
        worker_rate = Worker(
            name="Rate Watch",
            phone="+1 555-6000",
            team_id=team.team_id,
            skills=["standard"],
            rating_avg=4.0,
            rating_count=3,
            is_active=True,
        )
        session.add_all(
            [
                worker_top,
                worker_busy,
                worker_newbie,
                worker_problem,
                worker_revenue,
                worker_rate,
            ]
        )
        await session.flush()

        session.add_all(
            [
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(days=1),
                    duration_minutes=120,
                    status="DONE",
                    assigned_worker_id=worker_busy.worker_id,
                    base_charge_cents=12000,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(days=2),
                    duration_minutes=90,
                    status="DONE",
                    assigned_worker_id=worker_busy.worker_id,
                    base_charge_cents=9000,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(days=1),
                    duration_minutes=60,
                    status="DONE",
                    assigned_worker_id=worker_revenue.worker_id,
                    base_charge_cents=50000,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(days=1),
                    duration_minutes=45,
                    status="CANCELLED",
                    assigned_worker_id=worker_problem.worker_id,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(days=2),
                    duration_minutes=30,
                    status="CANCELLED",
                    assigned_worker_id=worker_problem.worker_id,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(days=3),
                    duration_minutes=30,
                    status="DONE",
                    assigned_worker_id=worker_problem.worker_id,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(days=1),
                    duration_minutes=30,
                    status="CANCELLED",
                    assigned_worker_id=worker_rate.worker_id,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(days=2),
                    duration_minutes=30,
                    status="DONE",
                    assigned_worker_id=worker_rate.worker_id,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(days=3),
                    duration_minutes=30,
                    status="CONFIRMED",
                    assigned_worker_id=worker_rate.worker_id,
                ),
            ]
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    response = client.get("/v1/admin/ui/workers/dashboard", headers=headers)
    assert response.status_code == 200
    assert "Top Rated" in response.text
    assert "Busy Bee" in response.text
    assert "Newbie" in response.text
    assert "Problem Worker" in response.text
    assert "Top Revenue" in response.text
    assert "Rate Watch" in response.text

    skill_response = client.get(
        "/v1/admin/ui/workers/dashboard?skill=deep", headers=headers
    )
    assert "Top Rated" in skill_response.text
    assert "Top Revenue" in skill_response.text
    assert "Busy Bee" not in skill_response.text
    assert "Newbie" not in skill_response.text
    assert "Problem Worker" not in skill_response.text
