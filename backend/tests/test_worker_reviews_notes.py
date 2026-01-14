import base64
import datetime as dt
import uuid

import pytest

from app.domain.bookings.db_models import Booking, Team
from app.domain.bookings.service import ensure_default_team
from app.domain.saas.db_models import Organization
from app.domain.workers.db_models import Worker
from app.domain.workers import service as worker_service
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _dispatch_credentials():
    settings.dispatcher_basic_username = "dispatch"
    settings.dispatcher_basic_password = "secret"
    yield


@pytest.mark.anyio
async def test_worker_review_updates_rating_and_detail(client, async_session_maker):
    now = dt.datetime.now(tz=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await session.flush()
        worker = Worker(name="Reviewed Worker", phone="+1 555-1111", team_id=team.team_id)
        session.add(worker)
        await session.flush()
        booking = Booking(
            team_id=team.team_id,
            starts_at=now - dt.timedelta(days=1),
            duration_minutes=60,
            status="DONE",
            assigned_worker_id=worker.worker_id,
        )
        session.add(booking)
        await session.commit()

        await worker_service.record_worker_review(
            session,
            org_id=worker.org_id,
            booking_id=booking.booking_id,
            worker_id=worker.worker_id,
            rating=5,
            comment="Great job!",
        )
        await session.commit()

        refreshed = await session.get(Worker, worker.worker_id)
        assert refreshed is not None
        assert refreshed.rating_count == 1
        assert refreshed.rating_avg == pytest.approx(5.0)

    headers = _basic_auth("dispatch", "secret")
    detail_resp = client.get(f"/v1/admin/ui/workers/{worker.worker_id}", headers=headers)
    assert detail_resp.status_code == 200
    assert "Great job!" in detail_resp.text
    assert "5/5" in detail_resp.text

    list_resp = client.get("/v1/admin/ui/workers?rating_min=4.5", headers=headers)
    assert list_resp.status_code == 200
    assert "Reviewed Worker" in list_resp.text


@pytest.mark.anyio
async def test_worker_notes_incidents_org_scoped(client, async_session_maker):
    now = dt.datetime.now(tz=dt.timezone.utc)
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    async with async_session_maker() as session:
        session.add_all([Organization(org_id=org_a, name="Org A"), Organization(org_id=org_b, name="Org B")])
        await session.flush()
        team_a = Team(name="Team A", org_id=org_a)
        team_b = Team(name="Team B", org_id=org_b)
        session.add_all([team_a, team_b])
        await session.flush()
        worker_a = Worker(
            name="Worker A",
            phone="+1 555-2222",
            team_id=team_a.team_id,
            org_id=org_a,
        )
        worker_b = Worker(
            name="Worker B",
            phone="+1 555-3333",
            team_id=team_b.team_id,
            org_id=org_b,
        )
        session.add_all([worker_a, worker_b])
        await session.flush()
        booking_a = Booking(
            team_id=team_a.team_id,
            org_id=org_a,
            starts_at=now - dt.timedelta(days=2),
            duration_minutes=90,
            status="DONE",
            assigned_worker_id=worker_a.worker_id,
        )
        session.add(booking_a)
        await session.commit()

    headers_a = {**_basic_auth("dispatch", "secret"), "X-Test-Org": str(org_a)}
    headers_b = {**_basic_auth("dispatch", "secret"), "X-Test-Org": str(org_b)}

    note_resp = client.post(
        f"/v1/admin/ui/workers/{worker_a.worker_id}/notes/create",
        headers=headers_a,
        data={"text": "Followed checklist", "booking_id": booking_a.booking_id},
        follow_redirects=False,
    )
    assert note_resp.status_code == 303

    incident_resp = client.post(
        f"/v1/admin/ui/workers/{worker_a.worker_id}/incidents/create",
        headers=headers_a,
        data={"text": "Reported issue", "severity": "high", "booking_id": booking_a.booking_id},
        follow_redirects=False,
    )
    assert incident_resp.status_code == 303

    detail_resp = client.get(f"/v1/admin/ui/workers/{worker_a.worker_id}", headers=headers_a)
    assert detail_resp.status_code == 200
    assert "Followed checklist" in detail_resp.text
    assert "Reported issue" in detail_resp.text
    assert "Incident" in detail_resp.text
    assert "high" in detail_resp.text

    cross_org_resp = client.post(
        f"/v1/admin/ui/workers/{worker_b.worker_id}/notes/create",
        headers=headers_a,
        data={"text": "Should fail"},
        follow_redirects=False,
    )
    assert cross_org_resp.status_code == 404

    cross_org_detail = client.get(f"/v1/admin/ui/workers/{worker_a.worker_id}", headers=headers_b)
    assert cross_org_detail.status_code == 404
