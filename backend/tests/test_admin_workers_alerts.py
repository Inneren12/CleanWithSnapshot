import base64
import datetime as dt
import json

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import ensure_default_team
from app.domain.workers.db_models import Worker, WorkerReview
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _alert_settings():
    original = {
        "dispatcher_basic_username": settings.dispatcher_basic_username,
        "dispatcher_basic_password": settings.dispatcher_basic_password,
        "worker_alert_inactive_days": settings.worker_alert_inactive_days,
        "worker_alert_rating_drop_threshold": settings.worker_alert_rating_drop_threshold,
        "worker_alert_rating_drop_review_window": settings.worker_alert_rating_drop_review_window,
        "worker_alert_skill_thresholds_raw": settings.worker_alert_skill_thresholds_raw,
    }
    settings.dispatcher_basic_username = "dispatch"
    settings.dispatcher_basic_password = "secret"
    settings.worker_alert_inactive_days = 7
    settings.worker_alert_rating_drop_threshold = 0.5
    settings.worker_alert_rating_drop_review_window = 2
    settings.worker_alert_skill_thresholds_raw = json.dumps(
        {"window-cleaning": {"rating_drop_threshold": 0.2}}
    )
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.mark.anyio
async def test_admin_worker_alerts_page(client, async_session_maker):
    now = dt.datetime.now(tz=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await session.flush()

        worker_inactive = Worker(
            name="Inactive Worker",
            phone="+1 555-1111",
            team_id=team.team_id,
            skills=["standard"],
            created_at=now - dt.timedelta(days=10),
            is_active=True,
        )
        worker_rating_drop = Worker(
            name="Rating Drop Worker",
            phone="+1 555-2222",
            team_id=team.team_id,
            skills=["window-cleaning"],
            created_at=now - dt.timedelta(days=30),
            is_active=True,
        )
        worker_active = Worker(
            name="Active Worker",
            phone="+1 555-3333",
            team_id=team.team_id,
            skills=["standard"],
            created_at=now - dt.timedelta(days=2),
            is_active=True,
        )
        session.add_all([worker_inactive, worker_rating_drop, worker_active])
        await session.flush()

        active_booking = Booking(
            team_id=team.team_id,
            starts_at=now - dt.timedelta(days=1),
            duration_minutes=60,
            status="DONE",
            assigned_worker_id=worker_active.worker_id,
        )
        review_bookings = [
            Booking(
                team_id=team.team_id,
                starts_at=now - dt.timedelta(days=12),
                duration_minutes=90,
                status="DONE",
                assigned_worker_id=worker_rating_drop.worker_id,
            ),
            Booking(
                team_id=team.team_id,
                starts_at=now - dt.timedelta(days=11),
                duration_minutes=90,
                status="DONE",
                assigned_worker_id=worker_rating_drop.worker_id,
            ),
            Booking(
                team_id=team.team_id,
                starts_at=now - dt.timedelta(days=2),
                duration_minutes=90,
                status="DONE",
                assigned_worker_id=worker_rating_drop.worker_id,
            ),
            Booking(
                team_id=team.team_id,
                starts_at=now - dt.timedelta(days=1),
                duration_minutes=90,
                status="DONE",
                assigned_worker_id=worker_rating_drop.worker_id,
            ),
        ]
        session.add(active_booking)
        session.add_all(review_bookings)
        await session.flush()

        reviews = [
            WorkerReview(
                booking_id=review_bookings[0].booking_id,
                worker_id=worker_rating_drop.worker_id,
                rating=5,
                created_at=now - dt.timedelta(days=12),
            ),
            WorkerReview(
                booking_id=review_bookings[1].booking_id,
                worker_id=worker_rating_drop.worker_id,
                rating=5,
                created_at=now - dt.timedelta(days=11),
            ),
            WorkerReview(
                booking_id=review_bookings[2].booking_id,
                worker_id=worker_rating_drop.worker_id,
                rating=3,
                created_at=now - dt.timedelta(days=2),
            ),
            WorkerReview(
                booking_id=review_bookings[3].booking_id,
                worker_id=worker_rating_drop.worker_id,
                rating=3,
                created_at=now - dt.timedelta(days=1),
            ),
        ]
        session.add_all(reviews)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    response = client.get("/v1/admin/ui/workers/alerts", headers=headers)
    assert response.status_code == 200
    assert "Inactive worker" in response.text
    assert "Rating drop" in response.text
    assert "Unread messages" in response.text
    assert "Inactive Worker" in response.text
    assert "Rating Drop Worker" in response.text

    skill_response = client.get(
        "/v1/admin/ui/workers/alerts?skill=window-cleaning", headers=headers
    )
    assert "Rating Drop Worker" in skill_response.text
    assert "Inactive Worker" not in skill_response.text

    severity_response = client.get(
        "/v1/admin/ui/workers/alerts?severity=high", headers=headers
    )
    assert "Rating Drop Worker" in severity_response.text
    assert "Inactive Worker" not in severity_response.text
