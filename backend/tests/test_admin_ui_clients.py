import asyncio
import base64
import json
import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa

from app.domain.analytics.db_models import EventLog
from app.domain.bookings.db_models import Booking, BookingWorker, Team
from app.domain.clients.db_models import ClientNote, ClientUser
from app.domain.saas.db_models import Organization
from app.domain.subscriptions.db_models import Subscription
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _seed_clients(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Client Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            active_client = ClientUser(
                org_id=settings.default_org_id,
                name="Active Client",
                email=f"active-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-111-2222",
                address="100 Active Way",
                is_active=True,
            )
            archived_client = ClientUser(
                org_id=settings.default_org_id,
                name="Archived Client",
                email=f"archived-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-333-4444",
                address="200 Archived Way",
                is_active=False,
            )
            session.add_all([active_client, archived_client])
            await session.flush()

            booking = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=active_client.client_id,
                team_id=team.team_id,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=90,
                status="PENDING",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add(booking)
            await session.commit()
            return active_client.client_id, archived_client.client_id, booking.booking_id

    return asyncio.run(create())


def _seed_client_with_booking(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Delete Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            client = ClientUser(
                org_id=settings.default_org_id,
                name="Delete Client",
                email=f"delete-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-777-8888",
                address="400 Delete Lane",
                is_active=True,
            )
            session.add(client)
            await session.flush()

            booking = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=client.client_id,
                team_id=team.team_id,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=90,
                status="PENDING",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add(booking)
            event_log = EventLog(event_type="booking_created", booking_id=booking.booking_id)
            session.add(event_log)
            await session.commit()
            return client.client_id, booking.booking_id, event_log.event_id

    return asyncio.run(create())


def _seed_client_with_subscription(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            client = ClientUser(
                org_id=settings.default_org_id,
                name="Subscription Client",
                email=f"subscription-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-999-0000",
                address="500 Subscription Way",
                is_active=True,
            )
            session.add(client)
            await session.flush()

            subscription = Subscription(
                org_id=settings.default_org_id,
                client_id=client.client_id,
                status="active",
                frequency="monthly",
                start_date=date.today(),
                next_run_at=datetime.now(tz=timezone.utc),
                base_service_type="standard",
                base_price=15000,
            )
            session.add(subscription)
            await session.commit()
            return client.client_id, subscription.subscription_id

    return asyncio.run(create())


def _seed_client_with_notes_and_bookings(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Note Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            worker = Worker(
                org_id=settings.default_org_id,
                team_id=team.team_id,
                name="Assigned Worker",
                phone="+1 555-222-3333",
                is_active=True,
            )
            session.add(worker)

            client = ClientUser(
                org_id=settings.default_org_id,
                name="Notes Client",
                email=f"notes-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-444-5555",
                address="600 Notes Way",
                is_active=True,
            )
            session.add(client)
            await session.flush()

            booking = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=client.client_id,
                team_id=team.team_id,
                assigned_worker_id=worker.worker_id,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=120,
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=25000,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add(booking)
            session.add(BookingWorker(booking_id=booking.booking_id, worker_id=worker.worker_id))

            note = ClientNote(
                org_id=settings.default_org_id,
                client_id=client.client_id,
                note_text="First note",
                created_by="admin",
            )
            session.add(note)
            await session.commit()
            return client.client_id, booking.booking_id

    return asyncio.run(create())


def _seed_client_in_other_org(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            org_id = uuid.uuid4()
            session.add(Organization(org_id=org_id, name="Other Org"))
            client = ClientUser(
                org_id=org_id,
                name="Other Org Client",
                email=f"other-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-666-7777",
                address="700 Other Way",
                is_active=True,
            )
            session.add(client)
            await session.commit()
            return client.client_id

    return asyncio.run(create())


def test_admin_can_archive_clients_and_filter(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        active_client_id, archived_client_id, booking_id = _seed_clients(async_session_maker)
        headers = _basic_auth("admin", "secret")

        list_response = client.get("/v1/admin/ui/clients", headers=headers)
        assert list_response.status_code == 200
        assert "Active Client" in list_response.text
        assert "Archived Client" not in list_response.text

        archived_list = client.get("/v1/admin/ui/clients?show=archived", headers=headers)
        assert archived_list.status_code == 200
        assert "Archived Client" in archived_list.text

        archive_response = client.post(
            f"/v1/admin/ui/clients/{active_client_id}/archive",
            headers=headers,
            follow_redirects=False,
        )
        assert archive_response.status_code == 303

        list_after = client.get("/v1/admin/ui/clients", headers=headers)
        assert list_after.status_code == 200
        assert "Active Client" not in list_after.text

        booking_form = client.get("/v1/admin/ui/bookings/new", headers=headers)
        assert booking_form.status_code == 200
        assert "Active Client" not in booking_form.text

        archived_list_after = client.get("/v1/admin/ui/clients?show=archived", headers=headers)
        assert archived_list_after.status_code == 200
        assert "Active Client" in archived_list_after.text

        unarchive_response = client.post(
            f"/v1/admin/ui/clients/{active_client_id}/unarchive",
            headers=headers,
            follow_redirects=False,
        )
        assert unarchive_response.status_code == 303

        list_after_unarchive = client.get("/v1/admin/ui/clients", headers=headers)
        assert list_after_unarchive.status_code == 200
        assert "Active Client" in list_after_unarchive.text

        async def verify_booking():
            async with async_session_maker() as session:
                refreshed = await session.get(Booking, booking_id)
                assert refreshed is not None
                assert refreshed.client_id == active_client_id

        asyncio.run(verify_booking())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_can_delete_client_with_detach_strategy(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id, booking_id, event_log_id = _seed_client_with_booking(async_session_maker)
        headers = _basic_auth("admin", "secret")

        delete_response = client.post(
            f"/v1/admin/ui/clients/{client_id}/delete",
            headers=headers,
            data={"confirm": "DELETE", "strategy": "detach"},
            follow_redirects=False,
        )
        assert delete_response.status_code == 303

        async def verify_detach():
            async with async_session_maker() as session:
                booking = await session.get(Booking, booking_id)
                assert booking is not None
                assert booking.client_id is None
                event_log = await session.get(EventLog, event_log_id)
                assert event_log is not None
                deleted_client = await session.get(ClientUser, client_id)
                assert deleted_client is None

        asyncio.run(verify_detach())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_can_delete_client_with_cascade_strategy(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id, booking_id, event_log_id = _seed_client_with_booking(async_session_maker)
        headers = _basic_auth("admin", "secret")

        delete_response = client.post(
            f"/v1/admin/ui/clients/{client_id}/delete",
            headers=headers,
            data={"confirm": "DELETE", "strategy": "cascade"},
            follow_redirects=False,
        )
        assert delete_response.status_code == 303

        async def verify_cascade():
            async with async_session_maker() as session:
                booking = await session.get(Booking, booking_id)
                assert booking is None
                event_logs = (
                    await session.execute(
                        sa.select(EventLog).where(EventLog.booking_id == booking_id)
                    )
                ).scalars().all()
                assert event_logs == []
                deleted_event_log = await session.get(EventLog, event_log_id)
                assert deleted_event_log is None
                deleted_client = await session.get(ClientUser, client_id)
                assert deleted_client is None

        asyncio.run(verify_cascade())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_cannot_delete_client_with_subscriptions(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id, subscription_id = _seed_client_with_subscription(async_session_maker)
        headers = _basic_auth("admin", "secret")

        delete_response = client.post(
            f"/v1/admin/ui/clients/{client_id}/delete",
            headers=headers,
            data={"confirm": "DELETE", "strategy": "detach"},
            follow_redirects=False,
        )
        assert delete_response.status_code == 409
        assert "Client has subscriptions" in delete_response.text

        async def verify_blocked():
            async with async_session_maker() as session:
                existing_client = await session.get(ClientUser, client_id)
                assert existing_client is not None
                existing_subscription = await session.get(Subscription, subscription_id)
                assert existing_subscription is not None

        asyncio.run(verify_blocked())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_client_detail_shows_bookings_and_notes(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id, booking_id = _seed_client_with_notes_and_bookings(async_session_maker)
        headers = _basic_auth("admin", "secret")

        response = client.get(f"/v1/admin/ui/clients/{client_id}", headers=headers)
        assert response.status_code == 200
        assert "Bookings history" in response.text
        assert "COMPLETED" in response.text
        assert "Assigned Worker" in response.text
        assert "First note" in response.text
        assert booking_id in response.text
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_can_update_client_tags(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        async def create_client():
            async with async_session_maker() as session:
                client_user = ClientUser(
                    org_id=settings.default_org_id,
                    name="Tagged Client",
                    email=f"tags-{uuid.uuid4().hex[:6]}@example.com",
                    phone="+1 555-888-9999",
                    address="800 Tags Way",
                    is_active=True,
                )
                session.add(client_user)
                await session.commit()
                return client_user.client_id

        client_id = asyncio.run(create_client())
        headers = _basic_auth("admin", "secret")

        response = client.post(
            f"/v1/admin/ui/clients/{client_id}/tags/update",
            headers=headers,
            data={"tags": "VIP, problematic"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        async def verify_tags():
            async with async_session_maker() as session:
                refreshed = await session.get(ClientUser, client_id)
                assert refreshed is not None
                assert json.loads(refreshed.tags_json) == ["VIP", "problematic"]

        asyncio.run(verify_tags())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_can_block_and_unblock_client(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        async def create_client():
            async with async_session_maker() as session:
                client_user = ClientUser(
                    org_id=settings.default_org_id,
                    name="Blocked Client",
                    email=f"blocked-{uuid.uuid4().hex[:6]}@example.com",
                    phone="+1 555-000-1111",
                    address="900 Blocked Way",
                    is_active=True,
                )
                session.add(client_user)
                await session.commit()
                return client_user.client_id

        client_id = asyncio.run(create_client())
        headers = _basic_auth("admin", "secret")

        block_response = client.post(
            f"/v1/admin/ui/clients/{client_id}/block",
            headers=headers,
            follow_redirects=False,
        )
        assert block_response.status_code == 303

        async def verify_blocked():
            async with async_session_maker() as session:
                refreshed = await session.get(ClientUser, client_id)
                assert refreshed is not None
                assert refreshed.is_blocked is True

        asyncio.run(verify_blocked())

        unblock_response = client.post(
            f"/v1/admin/ui/clients/{client_id}/unblock",
            headers=headers,
            follow_redirects=False,
        )
        assert unblock_response.status_code == 303

        async def verify_unblocked():
            async with async_session_maker() as session:
                refreshed = await session.get(ClientUser, client_id)
                assert refreshed is not None
                assert refreshed.is_blocked is False

        asyncio.run(verify_unblocked())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_can_add_client_note(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        async def create_client():
            async with async_session_maker() as session:
                client_user = ClientUser(
                    org_id=settings.default_org_id,
                    name="Noted Client",
                    email=f"note-{uuid.uuid4().hex[:6]}@example.com",
                    phone="+1 555-121-2121",
                    address="1000 Note Way",
                    is_active=True,
                )
                session.add(client_user)
                await session.commit()
                return client_user.client_id

        client_id = asyncio.run(create_client())
        headers = _basic_auth("admin", "secret")

        response = client.post(
            f"/v1/admin/ui/clients/{client_id}/notes/create",
            headers=headers,
            data={"note_text": "Added note"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        async def verify_note():
            async with async_session_maker() as session:
                notes = (
                    await session.execute(
                        sa.select(ClientNote).where(
                            ClientNote.client_id == client_id,
                            ClientNote.org_id == settings.default_org_id,
                        )
                    )
                ).scalars().all()
                assert [note.note_text for note in notes] == ["Added note"]

        asyncio.run(verify_note())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_client_org_scope_enforced(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id = _seed_client_in_other_org(async_session_maker)
        headers = _basic_auth("admin", "secret")

        response = client.get(f"/v1/admin/ui/clients/{client_id}", headers=headers)
        assert response.status_code == 404
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password
