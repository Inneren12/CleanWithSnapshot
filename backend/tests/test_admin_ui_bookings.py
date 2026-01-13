import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app.domain.analytics.db_models import EventLog
from app.domain.bookings.db_models import Booking, BookingWorker, Team
from app.domain.clients.db_models import ClientUser
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _seed_booking(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Dispatch Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            client = ClientUser(
                org_id=settings.default_org_id,
                name="UI Client",
                email=f"client-{uuid.uuid4().hex[:8]}@example.com",
                phone="+1 555-111-2222",
                address="123 Admin Way",
            )
            session.add(client)
            await session.flush()

            worker = Worker(
                org_id=settings.default_org_id,
                team_id=team.team_id,
                name="UI Worker",
                email=f"worker-{uuid.uuid4().hex[:8]}@example.com",
                phone="+1 555-333-4444",
                is_active=True,
            )
            session.add(worker)
            await session.flush()

            booking = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=client.client_id,
                team_id=team.team_id,
                assigned_worker_id=worker.worker_id,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=120,
                status="PENDING",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add(booking)
            session.add(BookingWorker(booking_id=booking.booking_id, worker_id=worker.worker_id))
            await session.commit()
            return booking.booking_id, team.team_id, client.client_id, worker.worker_id

    return asyncio.run(create())


def test_admin_create_booking_form_action(client):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        headers = _basic_auth("admin", "secret")
        response = client.get("/v1/admin/ui/bookings/new", headers=headers)
        assert response.status_code == 200
        assert 'action="/v1/admin/ui/bookings/create"' in response.text
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_can_create_edit_delete_booking(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        booking_id, team_id, client_id, worker_id = _seed_booking(async_session_maker)
        headers = _basic_auth("admin", "secret")

        starts_at = datetime.now(tz=timezone.utc).replace(microsecond=0)
        create_response = client.post(
            "/v1/admin/ui/bookings/create",
            headers=headers,
            data={
                "team_id": team_id,
                "client_id": client_id,
                "worker_ids": [worker_id],
                "starts_at": starts_at.isoformat(),
                "duration_minutes": 90,
            },
            follow_redirects=False,
        )
        assert create_response.status_code == 303

        new_starts = (starts_at + timedelta(hours=2)).isoformat()
        update_response = client.post(
            f"/v1/admin/ui/bookings/{booking_id}/update",
            headers=headers,
            data={
                "team_id": team_id,
                "client_id": client_id,
                "worker_ids": [worker_id],
                "starts_at": new_starts,
                "duration_minutes": 150,
            },
            follow_redirects=False,
        )
        assert update_response.status_code == 303

        async def verify_update():
            async with async_session_maker() as session:
                refreshed = await session.get(Booking, booking_id)
                assert refreshed is not None
                assert refreshed.duration_minutes == 150
                expected = datetime.fromisoformat(new_starts).replace(tzinfo=None)
                assert refreshed.starts_at == expected

        asyncio.run(verify_update())

        async def seed_event_log():
            async with async_session_maker() as session:
                session.add(
                    EventLog(
                        event_type="BOOKING_DELETED_TEST",
                        booking_id=booking_id,
                    )
                )
                await session.commit()

        asyncio.run(seed_event_log())

        delete_response = client.post(
            f"/v1/admin/ui/bookings/{booking_id}/delete",
            headers=headers,
            data={"confirm": "DELETE"},
            follow_redirects=False,
        )
        assert delete_response.status_code == 303

        async def verify_delete():
            async with async_session_maker() as session:
                deleted = await session.get(Booking, booking_id)
                assert deleted is None
                is_sqlite = session.get_bind().dialect.name == "sqlite"
                foreign_keys_enabled = (
                    (await session.execute(sa.text("PRAGMA foreign_keys"))).scalar()
                    if is_sqlite
                    else True
                )
                remaining = (
                    await session.execute(
                        sa.select(EventLog).where(EventLog.booking_id == booking_id)
                    )
                ).scalars().all()
                if foreign_keys_enabled:
                    assert remaining == []

        asyncio.run(verify_delete())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_can_purge_bookings(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        headers = _basic_auth("admin", "secret")

        async def seed_bookings():
            async with async_session_maker() as session:
                team = Team(name=f"Purge Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
                session.add(team)
                await session.flush()

                booking_recent = Booking(
                    booking_id=str(uuid.uuid4()),
                    org_id=settings.default_org_id,
                    team_id=team.team_id,
                    starts_at=datetime.now(tz=timezone.utc),
                    duration_minutes=60,
                    status="PENDING",
                    deposit_cents=0,
                    base_charge_cents=0,
                    refund_total_cents=0,
                    credit_note_total_cents=0,
                )
                booking_old = Booking(
                    booking_id=str(uuid.uuid4()),
                    org_id=settings.default_org_id,
                    team_id=team.team_id,
                    starts_at=datetime.now(tz=timezone.utc) - timedelta(days=10),
                    duration_minutes=60,
                    status="PENDING",
                    deposit_cents=0,
                    base_charge_cents=0,
                    refund_total_cents=0,
                    credit_note_total_cents=0,
                )
                session.add_all([booking_recent, booking_old])
                await session.commit()
                return booking_recent.booking_id, booking_old.booking_id

        booking_recent_id, booking_old_id = asyncio.run(seed_bookings())

        guard_response = client.post(
            "/v1/admin/ui/bookings/purge",
            headers=headers,
            data={},
            follow_redirects=False,
        )
        assert guard_response.status_code == 400

        target_date = (datetime.now(tz=timezone.utc) - timedelta(days=5)).date().isoformat()
        purge_response = client.post(
            "/v1/admin/ui/bookings/purge",
            headers=headers,
            data={"confirm": "PURGE", "date_to": target_date},
            follow_redirects=False,
        )
        assert purge_response.status_code == 303

        async def verify_purge():
            async with async_session_maker() as session:
                recent = await session.get(Booking, booking_recent_id)
                old = await session.get(Booking, booking_old_id)
                assert recent is not None
                assert old is None

        asyncio.run(verify_purge())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_edit_booking_syncs_assigned_worker(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        async def seed_booking():
            async with async_session_maker() as session:
                team = Team(name=f"Edit Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
                session.add(team)
                await session.flush()

                client = ClientUser(
                    org_id=settings.default_org_id,
                    name="Edit Client",
                    email=f"client-{uuid.uuid4().hex[:8]}@example.com",
                    phone="+1 555-111-2222",
                    address="456 Admin Way",
                )
                session.add(client)
                await session.flush()

                worker_a = Worker(
                    org_id=settings.default_org_id,
                    team_id=team.team_id,
                    name="Worker A",
                    email=f"worker-a-{uuid.uuid4().hex[:8]}@example.com",
                    phone="+1 555-333-4444",
                    is_active=True,
                )
                worker_b = Worker(
                    org_id=settings.default_org_id,
                    team_id=team.team_id,
                    name="Worker B",
                    email=f"worker-b-{uuid.uuid4().hex[:8]}@example.com",
                    phone="+1 555-333-5555",
                    is_active=True,
                )
                worker_c = Worker(
                    org_id=settings.default_org_id,
                    team_id=team.team_id,
                    name="Worker C",
                    email=f"worker-c-{uuid.uuid4().hex[:8]}@example.com",
                    phone="+1 555-333-6666",
                    is_active=True,
                )
                session.add_all([worker_a, worker_b, worker_c])
                await session.flush()

                starts_at = datetime.now(tz=timezone.utc).replace(microsecond=0)
                booking = Booking(
                    booking_id=str(uuid.uuid4()),
                    org_id=settings.default_org_id,
                    client_id=client.client_id,
                    team_id=team.team_id,
                    assigned_worker_id=worker_a.worker_id,
                    starts_at=starts_at,
                    duration_minutes=120,
                    status="PENDING",
                    deposit_cents=0,
                    base_charge_cents=0,
                    refund_total_cents=0,
                    credit_note_total_cents=0,
                )
                session.add(booking)
                session.add(BookingWorker(booking_id=booking.booking_id, worker_id=worker_a.worker_id))
                session.add(BookingWorker(booking_id=booking.booking_id, worker_id=worker_b.worker_id))
                await session.commit()
                return (
                    booking.booking_id,
                    team.team_id,
                    client.client_id,
                    worker_a.worker_id,
                    worker_b.worker_id,
                    worker_c.worker_id,
                    starts_at,
                )

        booking_id, team_id, client_id, worker_a_id, worker_b_id, worker_c_id, starts_at = asyncio.run(seed_booking())
        headers = _basic_auth("admin", "secret")

        preserve_response = client.post(
            f"/v1/admin/ui/bookings/{booking_id}/update",
            headers=headers,
            data={
                "team_id": team_id,
                "client_id": client_id,
                "worker_ids": [worker_a_id, worker_b_id],
                "starts_at": starts_at.isoformat(),
                "duration_minutes": 120,
            },
            follow_redirects=False,
        )
        assert preserve_response.status_code == 303

        async def verify_preserved():
            async with async_session_maker() as session:
                booking = await session.get(Booking, booking_id)
                assert booking is not None
                assert booking.assigned_worker_id == worker_a_id
                assignments = (
                    await session.execute(
                        sa.select(BookingWorker.worker_id).where(BookingWorker.booking_id == booking_id)
                    )
                ).scalars().all()
                assert sorted(assignments) == sorted([worker_a_id, worker_b_id])

        asyncio.run(verify_preserved())

        update_response = client.post(
            f"/v1/admin/ui/bookings/{booking_id}/update",
            headers=headers,
            data={
                "team_id": team_id,
                "client_id": client_id,
                "worker_ids": [worker_b_id, worker_c_id],
                "starts_at": starts_at.isoformat(),
                "duration_minutes": 120,
            },
            follow_redirects=False,
        )
        assert update_response.status_code == 303

        async def verify_replaced():
            async with async_session_maker() as session:
                booking = await session.get(Booking, booking_id)
                assert booking is not None
                assert booking.assigned_worker_id == worker_b_id
                assignments = (
                    await session.execute(
                        sa.select(BookingWorker.worker_id).where(BookingWorker.booking_id == booking_id)
                    )
                ).scalars().all()
                assert sorted(assignments) == sorted([worker_b_id, worker_c_id])

        asyncio.run(verify_replaced())

        clear_response = client.post(
            f"/v1/admin/ui/bookings/{booking_id}/update",
            headers=headers,
            data={
                "team_id": team_id,
                "client_id": client_id,
                "starts_at": starts_at.isoformat(),
                "duration_minutes": 120,
            },
            follow_redirects=False,
        )
        assert clear_response.status_code == 303

        async def verify_cleared():
            async with async_session_maker() as session:
                booking = await session.get(Booking, booking_id)
                assert booking is not None
                assert booking.assigned_worker_id is None
                assignments = (
                    await session.execute(
                        sa.select(BookingWorker.worker_id).where(BookingWorker.booking_id == booking_id)
                    )
                ).scalars().all()
                assert assignments == []

        asyncio.run(verify_cleared())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password
