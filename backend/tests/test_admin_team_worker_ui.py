import base64
import datetime as dt

import pytest
import sqlalchemy as sa

from app.domain.analytics.db_models import EventLog
from app.domain.bookings.db_models import Booking, BookingWorker, Team
from app.domain.reason_logs.db_models import ReasonLog
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
async def test_admin_can_create_and_edit_team_ui(client, async_session_maker):
    async with async_session_maker() as session:
        await ensure_default_team(session)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    form_resp = client.get("/v1/admin/ui/teams/new", headers=headers)
    assert form_resp.status_code == 200
    assert "action=\"/v1/admin/ui/teams/create\"" in form_resp.text

    create_resp = client.post(
        "/v1/admin/ui/teams/create",
        headers=headers,
        data={"name": "Crew B"},
        follow_redirects=False,
    )
    assert create_resp.status_code == 303

    async with async_session_maker() as session:
        team = (
            await session.execute(sa.select(Team).where(Team.name == "Crew B"))
        ).scalar_one()

    update_resp = client.post(
        f"/v1/admin/ui/teams/{team.team_id}/update",
        headers=headers,
        data={"name": "Crew Beta"},
        follow_redirects=False,
    )
    assert update_resp.status_code == 303

    async with async_session_maker() as session:
        updated = await session.get(Team, team.team_id)
        assert updated is not None
        assert updated.name == "Crew Beta"


@pytest.mark.anyio
async def test_admin_team_reassign_and_delete(client, async_session_maker):
    async with async_session_maker() as session:
        await ensure_default_team(session)
        team = Team(name="Crew Delete")
        target = Team(name="Crew Target")
        session.add_all([team, target])
        await session.flush()
        worker = Worker(name="Worker A", phone="+1 555-0000", team_id=team.team_id)
        session.add(worker)
        await session.flush()
        booking = Booking(
            team_id=team.team_id,
            starts_at=dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=1),
            duration_minutes=60,
            status="PENDING",
        )
        session.add(booking)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    reassign_resp = client.post(
        f"/v1/admin/ui/teams/{team.team_id}/delete",
        headers=headers,
        data={"strategy": "reassign", "target_team_id": str(target.team_id), "confirm": "DELETE"},
        follow_redirects=False,
    )
    assert reassign_resp.status_code == 303

    async with async_session_maker() as session:
        deleted = await session.get(Team, team.team_id)
        assert deleted is None
        moved_worker = await session.get(Worker, worker.worker_id)
        assert moved_worker is not None
        assert moved_worker.team_id == target.team_id
        moved_booking = await session.get(Booking, booking.booking_id)
        assert moved_booking is not None
        assert moved_booking.team_id == target.team_id


@pytest.mark.anyio
async def test_admin_team_delete_empty(client, async_session_maker):
    async with async_session_maker() as session:
        team = Team(name="Delete Empty")
        session.add(team)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    delete_resp = client.post(
        f"/v1/admin/ui/teams/{team.team_id}/delete",
        headers=headers,
        data={"strategy": "delete", "confirm": "DELETE"},
        follow_redirects=False,
    )
    assert delete_resp.status_code == 303

    async with async_session_maker() as session:
        deleted = await session.get(Team, team.team_id)
        assert deleted is None


@pytest.mark.anyio
async def test_admin_team_cascade_delete(client, async_session_maker):
    async with async_session_maker() as session:
        team = Team(name="Cascade Team")
        session.add(team)
        await session.flush()
        worker = Worker(name="Cascade Worker", phone="+1 555-0001", team_id=team.team_id)
        session.add(worker)
        await session.flush()
        booking = Booking(
            team_id=team.team_id,
            starts_at=dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=1),
            duration_minutes=60,
            status="PENDING",
            assigned_worker_id=worker.worker_id,
        )
        session.add(booking)
        await session.flush()
        session.add(BookingWorker(booking_id=booking.booking_id, worker_id=worker.worker_id))
        session.add(
            EventLog(
                event_type="booking_created",
                booking_id=booking.booking_id,
            )
        )
        session.add(
            ReasonLog(
                order_id=booking.booking_id,
                kind="booking",
                code="cascade-test",
                note="Cascade delete team",
            )
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    delete_resp = client.post(
        f"/v1/admin/ui/teams/{team.team_id}/delete",
        headers=headers,
        data={"strategy": "cascade", "confirm": "DELETE"},
        follow_redirects=False,
    )
    assert delete_resp.status_code == 303

    async with async_session_maker() as session:
        deleted_team = await session.get(Team, team.team_id)
        assert deleted_team is None
        deleted_worker = await session.get(Worker, worker.worker_id)
        assert deleted_worker is None
        deleted_booking = await session.get(Booking, booking.booking_id)
        assert deleted_booking is None
        reason_logs = (
            await session.execute(
                sa.select(ReasonLog).where(ReasonLog.order_id == booking.booking_id)
            )
        ).scalars().all()
        assert reason_logs == []
        event_logs = (
            await session.execute(
                sa.select(EventLog).where(EventLog.booking_id == booking.booking_id)
            )
        ).scalars().all()
        assert event_logs == []


@pytest.mark.anyio
async def test_admin_team_archive_unarchive(client, async_session_maker):
    async with async_session_maker() as session:
        team = Team(name="Archive Team")
        session.add(team)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    archive_resp = client.post(
        f"/v1/admin/ui/teams/{team.team_id}/archive",
        headers=headers,
        follow_redirects=False,
    )
    assert archive_resp.status_code == 303

    async with async_session_maker() as session:
        archived = await session.get(Team, team.team_id)
        assert archived is not None
        assert archived.archived_at is not None

    unarchive_resp = client.post(
        f"/v1/admin/ui/teams/{team.team_id}/unarchive",
        headers=headers,
        follow_redirects=False,
    )
    assert unarchive_resp.status_code == 303

    async with async_session_maker() as session:
        unarchived = await session.get(Team, team.team_id)
        assert unarchived is not None
        assert unarchived.archived_at is None


@pytest.mark.anyio
async def test_admin_worker_archive_unarchive(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await session.flush()
        worker = Worker(name="Archive Me", phone="+1 555-9999", team_id=team.team_id)
        session.add(worker)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    archive_resp = client.post(
        f"/v1/admin/ui/workers/{worker.worker_id}/archive",
        headers=headers,
        follow_redirects=False,
    )
    assert archive_resp.status_code == 303

    async with async_session_maker() as session:
        archived = await session.get(Worker, worker.worker_id)
        assert archived is not None
        assert archived.archived_at is not None
        assert archived.is_active is False

    unarchive_resp = client.post(
        f"/v1/admin/ui/workers/{worker.worker_id}/unarchive",
        headers=headers,
        follow_redirects=False,
    )
    assert unarchive_resp.status_code == 303

    async with async_session_maker() as session:
        unarchived = await session.get(Worker, worker.worker_id)
        assert unarchived is not None
        assert unarchived.archived_at is None
        assert unarchived.is_active is True


@pytest.mark.anyio
async def test_admin_worker_delete_detach(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await session.flush()
        worker = Worker(name="Detach Me", phone="+1 555-1234", team_id=team.team_id)
        session.add(worker)
        await session.flush()
        booking = Booking(
            team_id=team.team_id,
            starts_at=dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=2),
            duration_minutes=90,
            status="PENDING",
            assigned_worker_id=worker.worker_id,
        )
        session.add(booking)
        await session.flush()
        session.add(BookingWorker(booking_id=booking.booking_id, worker_id=worker.worker_id))
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    delete_resp = client.post(
        f"/v1/admin/ui/workers/{worker.worker_id}/delete",
        headers=headers,
        data={"strategy": "detach", "confirm": "DELETE"},
        follow_redirects=False,
    )
    assert delete_resp.status_code == 303

    async with async_session_maker() as session:
        deleted_worker = await session.get(Worker, worker.worker_id)
        assert deleted_worker is None
        updated_booking = await session.get(Booking, booking.booking_id)
        assert updated_booking is not None
        assert updated_booking.assigned_worker_id is None
        assignments = (
            await session.execute(
                sa.select(BookingWorker).where(BookingWorker.booking_id == booking.booking_id)
            )
        ).scalars().all()
        assert assignments == []


@pytest.mark.anyio
async def test_admin_worker_delete_cascade(client, async_session_maker):
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        await session.flush()
        worker = Worker(name="Cascade Me", phone="+1 555-4321", team_id=team.team_id)
        session.add(worker)
        await session.flush()
        booking = Booking(
            team_id=team.team_id,
            starts_at=dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=3),
            duration_minutes=75,
            status="PENDING",
            assigned_worker_id=worker.worker_id,
        )
        session.add(booking)
        await session.flush()
        session.add(BookingWorker(booking_id=booking.booking_id, worker_id=worker.worker_id))
        session.add(
            EventLog(
                event_type="booking_created",
                booking_id=booking.booking_id,
            )
        )
        session.add(
            ReasonLog(
                order_id=booking.booking_id,
                kind="booking",
                code="cascade-test",
                note="Cascade delete worker",
            )
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    delete_resp = client.post(
        f"/v1/admin/ui/workers/{worker.worker_id}/delete",
        headers=headers,
        data={"strategy": "cascade", "confirm": "DELETE"},
        follow_redirects=False,
    )
    assert delete_resp.status_code == 303

    async with async_session_maker() as session:
        deleted_worker = await session.get(Worker, worker.worker_id)
        assert deleted_worker is None
        deleted_booking = await session.get(Booking, booking.booking_id)
        assert deleted_booking is None
        reason_logs = (
            await session.execute(
                sa.select(ReasonLog).where(ReasonLog.order_id == booking.booking_id)
            )
        ).scalars().all()
        assert reason_logs == []
        event_logs = (
            await session.execute(
                sa.select(EventLog).where(EventLog.booking_id == booking.booking_id)
            )
        ).scalars().all()
        assert event_logs == []

    list_resp = client.get("/v1/admin/ui/workers?active_only=1", headers=headers)
    assert list_resp.status_code == 200
    assert "Cascade Me" not in list_resp.text


@pytest.mark.anyio
async def test_admin_ui_requires_auth(client):
    response = client.get("/v1/admin/ui/teams")
    assert response.status_code == 401
