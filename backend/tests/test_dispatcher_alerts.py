import base64
import datetime as dt
import uuid

import pytest

from app.domain.bookings.db_models import Booking, Team
from app.domain.bookings.service import ensure_default_team
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
async def test_dispatcher_alerts_returns_late_and_cancelled(client, async_session_maker):
    now = dt.datetime.now(dt.timezone.utc)
    target_date = now.date()
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        worker = Worker(name="Worker Bee", phone="+1 555-0200", team_id=team.team_id)
        session.add(worker)
        await session.flush()
        session.add_all(
            [
                Booking(
                    team_id=team.team_id,
                    starts_at=now - dt.timedelta(minutes=30),
                    duration_minutes=60,
                    status="planned",
                    assigned_worker_id=worker.worker_id,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=now + dt.timedelta(hours=2),
                    duration_minutes=60,
                    status="CANCELLED",
                    updated_at=now,
                ),
            ]
        )
        await session.commit()

    response = client.get(
        "/v1/admin/dispatcher/alerts",
        params={"date": target_date.isoformat(), "tz": "UTC"},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    alert_types = {alert["type"] for alert in response.json()["alerts"]}
    assert "LATE_WORKER" in alert_types
    assert "CLIENT_CANCELLED_TODAY" in alert_types


@pytest.mark.anyio
async def test_dispatcher_alerts_org_isolation(client, async_session_maker):
    now = dt.datetime.now(dt.timezone.utc)
    target_date = now.date()
    other_org = uuid.uuid4()
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        worker = Worker(name="Worker Bee", phone="+1 555-0200", team_id=team.team_id)
        session.add(worker)
        await session.flush()
        session.add(
            Booking(
                team_id=team.team_id,
                starts_at=now - dt.timedelta(minutes=30),
                duration_minutes=60,
                status="planned",
                assigned_worker_id=worker.worker_id,
            )
        )
        await ensure_org(session, other_org, name="Other Org")
        other_team = Team(name="Other Team", org_id=other_org)
        session.add(other_team)
        await session.flush()
        other_worker = Worker(
            name="Other Worker",
            phone="+1 555-0300",
            team_id=other_team.team_id,
            org_id=other_org,
        )
        session.add(other_worker)
        await session.flush()
        session.add(
            Booking(
                team_id=other_team.team_id,
                org_id=other_org,
                starts_at=now - dt.timedelta(minutes=45),
                duration_minutes=60,
                status="planned",
                assigned_worker_id=other_worker.worker_id,
            )
        )
        await session.commit()

    response_default = client.get(
        "/v1/admin/dispatcher/alerts",
        params={"date": target_date.isoformat(), "tz": "UTC"},
        headers=_basic_auth("admin", "secret"),
    )
    response_other = client.get(
        "/v1/admin/dispatcher/alerts",
        params={"date": target_date.isoformat(), "tz": "UTC"},
        headers={**_basic_auth("admin", "secret"), "X-Test-Org": str(other_org)},
    )

    assert response_default.status_code == 200
    assert response_other.status_code == 200
    assert len(response_default.json()["alerts"]) == 1
    assert len(response_other.json()["alerts"]) == 1
