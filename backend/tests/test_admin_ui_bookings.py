import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app.domain.analytics.db_models import EventLog
from app.domain.bookings.db_models import Booking, BookingWorker, Team
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.saas.db_models import Organization
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


def _seed_client_team_worker(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Dispatch Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            client = ClientUser(
                org_id=settings.default_org_id,
                name="Prefill Client",
                email=f"prefill-{uuid.uuid4().hex[:8]}@example.com",
                phone="+1 555-222-3333",
                address="901 Booking Blvd",
            )
            session.add(client)
            await session.flush()

            worker = Worker(
                org_id=settings.default_org_id,
                team_id=team.team_id,
                name="Prefill Worker",
                email=f"prefill-worker-{uuid.uuid4().hex[:8]}@example.com",
                phone="+1 555-999-0000",
                is_active=True,
            )
            session.add(worker)
            await session.commit()
            return team.team_id, client.client_id, worker.worker_id, client.name, client.address

    return asyncio.run(create())


def _seed_client_team_worker_with_addresses(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Dispatch Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            client = ClientUser(
                org_id=settings.default_org_id,
                name="Address Client",
                email=f"address-{uuid.uuid4().hex[:8]}@example.com",
                phone="+1 555-888-2222",
                address="Base Address",
            )
            session.add(client)
            await session.flush()

            worker = Worker(
                org_id=settings.default_org_id,
                team_id=team.team_id,
                name="Address Worker",
                email=f"address-worker-{uuid.uuid4().hex[:8]}@example.com",
                phone="+1 555-999-1111",
                is_active=True,
            )
            session.add(worker)
            await session.flush()

            address = ClientAddress(
                org_id=settings.default_org_id,
                client_id=client.client_id,
                label="Home",
                address_text="742 Evergreen Terrace",
                notes="Gate code 1234",
            )
            session.add(address)
            await session.commit()
            return team.team_id, client.client_id, worker.worker_id, address.address_id, address.address_text

    return asyncio.run(create())


def _seed_blocked_client(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            client = ClientUser(
                org_id=settings.default_org_id,
                name="Blocked UI Client",
                email=f"blocked-{uuid.uuid4().hex[:8]}@example.com",
                phone="+1 555-555-0000",
                address="404 Blocked Blvd",
                is_blocked=True,
            )
            session.add(client)
            await session.commit()
            return client.client_id

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

        confirm_response = client.get(
            f"/v1/admin/ui/bookings/{booking_id}/delete",
            headers=headers,
        )
        assert confirm_response.status_code == 200
        assert "Delete booking permanently" in confirm_response.text
        assert "Event Logs" in confirm_response.text

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


def test_admin_booking_update_clears_address_when_client_changes(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        async def seed_booking():
            async with async_session_maker() as session:
                team = Team(name=f"Address Update {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
                session.add(team)
                await session.flush()

                client_a = ClientUser(
                    org_id=settings.default_org_id,
                    name="Address Client A",
                    email=f"address-a-{uuid.uuid4().hex[:8]}@example.com",
                    phone="+1 555-111-2222",
                    address="111 A St",
                )
                client_b = ClientUser(
                    org_id=settings.default_org_id,
                    name="Address Client B",
                    email=f"address-b-{uuid.uuid4().hex[:8]}@example.com",
                    phone="+1 555-333-4444",
                    address="222 B St",
                )
                session.add_all([client_a, client_b])
                await session.flush()

                address = ClientAddress(
                    org_id=settings.default_org_id,
                    client_id=client_a.client_id,
                    label="Home",
                    address_text="111 A St",
                    notes=None,
                )
                session.add(address)
                await session.flush()

                starts_at = datetime.now(tz=timezone.utc).replace(microsecond=0)
                booking = Booking(
                    booking_id=str(uuid.uuid4()),
                    org_id=settings.default_org_id,
                    client_id=client_a.client_id,
                    team_id=team.team_id,
                    assigned_worker_id=None,
                    starts_at=starts_at,
                    duration_minutes=120,
                    status="PENDING",
                    deposit_cents=0,
                    base_charge_cents=0,
                    refund_total_cents=0,
                    credit_note_total_cents=0,
                    address_id=address.address_id,
                )
                session.add(booking)
                await session.commit()
                return booking.booking_id, team.team_id, client_b.client_id, starts_at

        booking_id, team_id, new_client_id, starts_at = asyncio.run(seed_booking())
        headers = _basic_auth("admin", "secret")

        update_response = client.post(
            f"/v1/admin/ui/bookings/{booking_id}/update",
            headers=headers,
            data={
                "team_id": team_id,
                "client_id": new_client_id,
                "starts_at": starts_at.isoformat(),
                "duration_minutes": 120,
            },
            follow_redirects=False,
        )
        assert update_response.status_code == 303

        async def verify_address_cleared():
            async with async_session_maker() as session:
                booking = await session.get(Booking, booking_id)
                assert booking is not None
                assert booking.client_id == new_client_id
                assert booking.address_id is None

        asyncio.run(verify_address_cleared())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_booking_form_warns_on_blocked_client(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id = _seed_blocked_client(async_session_maker)
        headers = _basic_auth("admin", "secret")
        response = client.get(f"/v1/admin/ui/bookings/new?client_id={client_id}", headers=headers)
        assert response.status_code == 200
        assert "Client is blocked" in response.text
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_booking_new_prefills_client_address(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        team_id, client_id, worker_id, client_name, client_address = _seed_client_team_worker(
            async_session_maker
        )
        headers = _basic_auth("admin", "secret")

        response = client.get(
            f"/v1/admin/ui/bookings/new?client_id={client_id}",
            headers=headers,
        )
        assert response.status_code == 200
        assert f'Creating booking for {client_name}' in response.text
        assert f'<option value="{client_id}" selected>' in response.text
        assert f'name="address" value="{client_address}"' in response.text

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
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_booking_new_prefills_selected_address(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        team_id, client_id, worker_id, address_id, address_text = (
            _seed_client_team_worker_with_addresses(async_session_maker)
        )
        headers = _basic_auth("admin", "secret")

        response = client.get(
            f"/v1/admin/ui/bookings/new?client_id={client_id}&address_id={address_id}",
            headers=headers,
        )
        assert response.status_code == 200
        assert f'Using address' in response.text
        assert f'name="address" value="{address_text}"' in response.text

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
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_booking_new_address_org_scope(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        _team_id, client_id, _worker_id, _address_id, _address_text = (
            _seed_client_team_worker_with_addresses(async_session_maker)
        )

        async def seed_other_org_address():
            async with async_session_maker() as session:
                other_org_id = uuid.uuid4()
                session.add(Organization(org_id=other_org_id, name="Other Org"))
                other_client = ClientUser(
                    org_id=other_org_id,
                    name="Other Client",
                    email=f"other-{uuid.uuid4().hex[:6]}@example.com",
                    phone="+1 555-222-7777",
                    address="Elsewhere",
                )
                session.add(other_client)
                await session.flush()
                other_address = ClientAddress(
                    org_id=other_org_id,
                    client_id=other_client.client_id,
                    label="Work",
                    address_text="555 Other St",
                )
                session.add(other_address)
                await session.commit()
                return other_address.address_id

        other_address_id = asyncio.run(seed_other_org_address())
        headers = _basic_auth("admin", "secret")

        response = client.get(
            f"/v1/admin/ui/bookings/new?client_id={client_id}&address_id={other_address_id}",
            headers=headers,
        )
        assert response.status_code == 200
        assert "Selected address not found" in response.text
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_can_archive_booking_and_filter_dispatch(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        booking_id, *_ = _seed_booking(async_session_maker)
        headers = _basic_auth("admin", "secret")

        async def get_booking_date():
            async with async_session_maker() as session:
                booking = await session.get(Booking, booking_id)
                assert booking is not None
                return booking.starts_at.date().isoformat()

        booking_date = asyncio.run(get_booking_date())

        visible_response = client.get(
            f"/v1/admin/ui/dispatch?date={booking_date}",
            headers=headers,
        )
        assert visible_response.status_code == 200
        assert f"/v1/admin/ui/bookings/{booking_id}/edit" in visible_response.text

        archive_response = client.post(
            f"/v1/admin/ui/bookings/{booking_id}/archive",
            headers=headers,
            data={},
            follow_redirects=False,
        )
        assert archive_response.status_code == 303

        hidden_response = client.get(
            f"/v1/admin/ui/dispatch?date={booking_date}",
            headers=headers,
        )
        assert hidden_response.status_code == 200
        assert f"/v1/admin/ui/bookings/{booking_id}/edit" not in hidden_response.text

        show_archived_response = client.get(
            f"/v1/admin/ui/dispatch?date={booking_date}&show_archived=true",
            headers=headers,
        )
        assert show_archived_response.status_code == 200
        assert f"/v1/admin/ui/bookings/{booking_id}/edit" in show_archived_response.text
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
