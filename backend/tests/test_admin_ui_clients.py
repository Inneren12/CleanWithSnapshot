import asyncio
import base64
import json
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import sqlalchemy as sa

from app.domain.analytics.db_models import EventLog
from app.domain.bookings.db_models import Booking, BookingWorker, Team
from app.domain.clients.db_models import ClientAddress, ClientFeedback, ClientNote, ClientUser
from app.domain.invoices import service as invoice_service
from app.domain.invoices.schemas import InvoiceItemCreate
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


def _seed_client_with_addresses(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            client_user = ClientUser(
                org_id=settings.default_org_id,
                name="Address Book Client",
                email=f"address-book-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-111-1234",
                address="Baseline",
                is_active=True,
            )
            session.add(client_user)
            await session.flush()

            home_address = ClientAddress(
                org_id=settings.default_org_id,
                client_id=client_user.client_id,
                label="Home",
                address_text="100 Main St",
                notes="Front door",
            )
            work_address = ClientAddress(
                org_id=settings.default_org_id,
                client_id=client_user.client_id,
                label="Work",
                address_text="200 Market St",
                notes=None,
            )
            session.add_all([home_address, work_address])
            await session.commit()
            return (
                client_user.client_id,
                home_address.address_id,
                home_address.address_text,
                work_address.address_id,
                work_address.address_text,
            )

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

            notes = [
                ClientNote(
                    org_id=settings.default_org_id,
                    client_id=client.client_id,
                    note_text="General note",
                    note_type=ClientNote.NOTE_TYPE_NOTE,
                    created_by="admin",
                ),
                ClientNote(
                    org_id=settings.default_org_id,
                    client_id=client.client_id,
                    note_text="Complaint note",
                    note_type=ClientNote.NOTE_TYPE_COMPLAINT,
                    created_by="admin",
                ),
                ClientNote(
                    org_id=settings.default_org_id,
                    client_id=client.client_id,
                    note_text="Praise note",
                    note_type=ClientNote.NOTE_TYPE_PRAISE,
                    created_by="admin",
                ),
            ]
            session.add_all(notes)
            await session.commit()
            return client.client_id, booking.booking_id

    return asyncio.run(create())


def _seed_client_with_feedback(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Feedback Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            client = ClientUser(
                org_id=settings.default_org_id,
                name="Feedback Client",
                email=f"feedback-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-111-9999",
                address="800 Feedback Way",
                is_active=True,
            )
            session.add(client)
            await session.flush()

            booking_one = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=client.client_id,
                team_id=team.team_id,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=90,
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            booking_two = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=client.client_id,
                team_id=team.team_id,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=120,
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add_all([booking_one, booking_two])
            await session.flush()

            feedback_rows = [
                ClientFeedback(
                    org_id=settings.default_org_id,
                    client_id=client.client_id,
                    booking_id=booking_one.booking_id,
                    rating=5,
                    comment="Great service",
                    channel="admin",
                ),
                ClientFeedback(
                    org_id=settings.default_org_id,
                    client_id=client.client_id,
                    booking_id=booking_two.booking_id,
                    rating=2,
                    comment="Not satisfied",
                    channel="admin",
                ),
            ]
            session.add_all(feedback_rows)
            await session.commit()
            return client.client_id, booking_one.booking_id, booking_two.booking_id

    return asyncio.run(create())


def _seed_clients_with_risk_flags(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Risk Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            now = datetime.now(tz=timezone.utc)

            risky_client = ClientUser(
                org_id=settings.default_org_id,
                name="Risky Client",
                email=f"risky-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-222-3333",
                address="901 Risk Way",
                is_active=True,
            )
            complaints_only = ClientUser(
                org_id=settings.default_org_id,
                name="Complaints Only",
                email=f"complaints-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-222-4444",
                address="902 Risk Way",
                is_active=True,
            )
            low_ratings_only = ClientUser(
                org_id=settings.default_org_id,
                name="Low Ratings Only",
                email=f"low-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-222-5555",
                address="903 Risk Way",
                is_active=True,
            )
            safe_client = ClientUser(
                org_id=settings.default_org_id,
                name="Safe Client",
                email=f"safe-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-222-6666",
                address="904 Risk Way",
                is_active=True,
            )
            session.add_all([risky_client, complaints_only, low_ratings_only, safe_client])
            await session.flush()

            complaints = [
                ClientNote(
                    org_id=settings.default_org_id,
                    client_id=risky_client.client_id,
                    note_text="Complaint A",
                    note_type=ClientNote.NOTE_TYPE_COMPLAINT,
                    created_by="admin",
                    created_at=now - timedelta(days=5),
                ),
                ClientNote(
                    org_id=settings.default_org_id,
                    client_id=risky_client.client_id,
                    note_text="Complaint B",
                    note_type=ClientNote.NOTE_TYPE_COMPLAINT,
                    created_by="admin",
                    created_at=now - timedelta(days=3),
                ),
                ClientNote(
                    org_id=settings.default_org_id,
                    client_id=risky_client.client_id,
                    note_text="Complaint C",
                    note_type=ClientNote.NOTE_TYPE_COMPLAINT,
                    created_by="admin",
                    created_at=now - timedelta(days=2),
                ),
                ClientNote(
                    org_id=settings.default_org_id,
                    client_id=complaints_only.client_id,
                    note_text="Complaint only",
                    note_type=ClientNote.NOTE_TYPE_COMPLAINT,
                    created_by="admin",
                    created_at=now - timedelta(days=4),
                ),
                ClientNote(
                    org_id=settings.default_org_id,
                    client_id=complaints_only.client_id,
                    note_text="Complaint only 2",
                    note_type=ClientNote.NOTE_TYPE_COMPLAINT,
                    created_by="admin",
                    created_at=now - timedelta(days=1),
                ),
            ]
            session.add_all(complaints)

            risky_booking_one = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=risky_client.client_id,
                team_id=team.team_id,
                starts_at=now - timedelta(days=6),
                duration_minutes=90,
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            risky_booking_two = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=risky_client.client_id,
                team_id=team.team_id,
                starts_at=now - timedelta(days=2),
                duration_minutes=90,
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            low_booking_one = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=low_ratings_only.client_id,
                team_id=team.team_id,
                starts_at=now - timedelta(days=7),
                duration_minutes=90,
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            low_booking_two = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=low_ratings_only.client_id,
                team_id=team.team_id,
                starts_at=now - timedelta(days=4),
                duration_minutes=90,
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            safe_booking = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=settings.default_org_id,
                client_id=safe_client.client_id,
                team_id=team.team_id,
                starts_at=now - timedelta(days=2),
                duration_minutes=90,
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add_all(
                [
                    risky_booking_one,
                    risky_booking_two,
                    low_booking_one,
                    low_booking_two,
                    safe_booking,
                ]
            )
            await session.flush()

            feedback_rows = [
                ClientFeedback(
                    org_id=settings.default_org_id,
                    client_id=risky_client.client_id,
                    booking_id=risky_booking_one.booking_id,
                    rating=1,
                    comment="Very bad",
                    channel="admin",
                    created_at=now - timedelta(days=5),
                ),
                ClientFeedback(
                    org_id=settings.default_org_id,
                    client_id=risky_client.client_id,
                    booking_id=risky_booking_two.booking_id,
                    rating=2,
                    comment="Bad",
                    channel="admin",
                    created_at=now - timedelta(days=2),
                ),
                ClientFeedback(
                    org_id=settings.default_org_id,
                    client_id=low_ratings_only.client_id,
                    booking_id=low_booking_one.booking_id,
                    rating=2,
                    comment="Low",
                    channel="admin",
                    created_at=now - timedelta(days=6),
                ),
                ClientFeedback(
                    org_id=settings.default_org_id,
                    client_id=low_ratings_only.client_id,
                    booking_id=low_booking_two.booking_id,
                    rating=1,
                    comment="Low again",
                    channel="admin",
                    created_at=now - timedelta(days=3),
                ),
                ClientFeedback(
                    org_id=settings.default_org_id,
                    client_id=safe_client.client_id,
                    booking_id=safe_booking.booking_id,
                    rating=5,
                    comment="Great",
                    channel="admin",
                    created_at=now - timedelta(days=1),
                ),
            ]
            session.add_all(feedback_rows)
            await session.commit()
            return (
                risky_client.client_id,
                complaints_only.client_id,
                low_ratings_only.client_id,
                safe_client.client_id,
            )

    return asyncio.run(create())


def _seed_client_and_cross_org_booking(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Feedback Admin {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            client = ClientUser(
                org_id=settings.default_org_id,
                name="Feedback Admin Client",
                email=f"feedback-admin-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-999-1111",
                address="900 Feedback Way",
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
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add(booking)

            other_org_id = uuid.uuid4()
            session.add(Organization(org_id=other_org_id, name="Feedback Other Org"))
            other_team = Team(name=f"Feedback Other {uuid.uuid4().hex[:6]}", org_id=other_org_id)
            session.add(other_team)
            await session.flush()

            other_client = ClientUser(
                org_id=other_org_id,
                name="Feedback Other Client",
                email=f"feedback-other-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-222-8888",
                address="901 Feedback Way",
                is_active=True,
            )
            session.add(other_client)
            await session.flush()

            other_booking = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=other_org_id,
                client_id=other_client.client_id,
                team_id=other_team.team_id,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=90,
                status="COMPLETED",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add(other_booking)
            await session.commit()
            return client.client_id, booking.booking_id, other_booking.booking_id

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


def _seed_client_finance(async_session_maker):
    async def create():
        async with async_session_maker() as session:
            team = Team(name=f"Finance Team {uuid.uuid4().hex[:6]}", org_id=settings.default_org_id)
            session.add(team)
            await session.flush()

            client = ClientUser(
                org_id=settings.default_org_id,
                name="Finance Client",
                email=f"finance-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-222-9090",
                address="100 Finance Way",
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
                duration_minutes=60,
                status="DONE",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add(booking)
            await session.flush()

            invoice = await invoice_service.create_invoice_from_order(
                session,
                booking,
                items=[
                    InvoiceItemCreate(
                        description="Standard clean",
                        qty=1,
                        unit_price_cents=20000,
                        tax_rate=Decimal("0.00"),
                    )
                ],
                created_by="admin",
            )
            await invoice_service.record_manual_payment(session, invoice, 20000, method="cash")

            other_org_id = uuid.uuid4()
            session.add(Organization(org_id=other_org_id, name="Other Org"))
            other_team = Team(name=f"Other Team {uuid.uuid4().hex[:6]}", org_id=other_org_id)
            session.add(other_team)
            await session.flush()

            other_client = ClientUser(
                org_id=other_org_id,
                name="Other Finance Client",
                email=f"other-finance-{uuid.uuid4().hex[:6]}@example.com",
                phone="+1 555-777-8888",
                address="200 Other Way",
                is_active=True,
            )
            session.add(other_client)
            await session.flush()

            other_booking = Booking(
                booking_id=str(uuid.uuid4()),
                org_id=other_org_id,
                client_id=other_client.client_id,
                team_id=other_team.team_id,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=90,
                status="DONE",
                deposit_cents=0,
                base_charge_cents=0,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add(other_booking)
            await session.flush()

            other_invoice = await invoice_service.create_invoice_from_order(
                session,
                other_booking,
                items=[
                    InvoiceItemCreate(
                        description="Other clean",
                        qty=1,
                        unit_price_cents=15000,
                        tax_rate=Decimal("0.00"),
                    )
                ],
                created_by="admin",
            )
            await invoice_service.record_manual_payment(session, other_invoice, 15000, method="cash")
            await session.commit()
            return client.client_id, invoice.invoice_number, other_invoice.invoice_number

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


def test_admin_client_feedback_summary(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id, _, _ = _seed_client_with_feedback(async_session_maker)
        headers = _basic_auth("admin", "secret")

        response = client.get(f"/v1/admin/ui/clients/{client_id}", headers=headers)
        assert response.status_code == 200
        assert "Ratings &amp; reviews" in response.text
        assert "3.5/5" in response.text
        assert "Low ratings (≤2)" in response.text
        assert "Great service" in response.text
        assert "Not satisfied" in response.text
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_can_create_client_feedback_and_scope_booking(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id, booking_id, other_booking_id = _seed_client_and_cross_org_booking(
            async_session_maker
        )
        headers = _basic_auth("admin", "secret")

        create_response = client.post(
            f"/v1/admin/ui/clients/{client_id}/feedback/create",
            headers=headers,
            data={"booking_id": booking_id, "rating": "4", "comment": "Solid clean"},
            follow_redirects=False,
        )
        assert create_response.status_code == 303

        async def verify_feedback():
            async with async_session_maker() as session:
                feedback = (
                    await session.execute(
                        sa.select(ClientFeedback).where(
                            ClientFeedback.booking_id == booking_id,
                            ClientFeedback.org_id == settings.default_org_id,
                        )
                    )
                ).scalar_one_or_none()
                assert feedback is not None
                assert feedback.rating == 4
                assert feedback.comment == "Solid clean"

        asyncio.run(verify_feedback())

        invalid_response = client.post(
            f"/v1/admin/ui/clients/{client_id}/feedback/create",
            headers=headers,
            data={"booking_id": other_booking_id, "rating": "5", "comment": "Nope"},
            follow_redirects=False,
        )
        assert invalid_response.status_code == 400
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
    previous_chat_enabled = settings.chat_enabled
    previous_promos_enabled = settings.promos_enabled
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.chat_enabled = False
    settings.promos_enabled = False

    try:
        client_id, booking_id = _seed_client_with_notes_and_bookings(async_session_maker)
        headers = _basic_auth("admin", "secret")

        response = client.get(f"/v1/admin/ui/clients/{client_id}", headers=headers)
        assert response.status_code == 200
        assert "Bookings history" in response.text
        assert "COMPLETED" in response.text
        assert "Assigned Worker" in response.text
        assert "General note" in response.text
        assert "Complaint note" in response.text
        assert "Praise note" in response.text
        assert "Complaint" in response.text
        assert "Praise" in response.text
        assert booking_id in response.text
        assert "Chat not enabled yet" in response.text
        assert "Promos not enabled yet" in response.text
        assert f"/v1/admin/ui/clients/{client_id}/chat" not in response.text
        assert f"/v1/admin/ui/clients/{client_id}/promos" not in response.text
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password
        settings.chat_enabled = previous_chat_enabled
        settings.promos_enabled = previous_promos_enabled


def test_admin_client_detail_lists_addresses(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        (
            client_id,
            home_address_id,
            home_address_text,
            work_address_id,
            work_address_text,
        ) = _seed_client_with_addresses(async_session_maker)
        headers = _basic_auth("admin", "secret")

        response = client.get(f"/v1/admin/ui/clients/{client_id}", headers=headers)
        assert response.status_code == 200
        assert "Addresses" in response.text
        assert home_address_text in response.text
        assert work_address_text in response.text
        assert "Usage N/A" in response.text
        assert (
            f"/v1/admin/ui/bookings/new?client_id={client_id}&address_id={home_address_id}"
            in response.text
        )
        assert (
            f"/v1/admin/ui/bookings/new?client_id={client_id}&address_id={work_address_id}"
            in response.text
        )
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_client_notes_filter_by_type(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id, _booking_id = _seed_client_with_notes_and_bookings(async_session_maker)
        headers = _basic_auth("admin", "secret")

        response = client.get(
            f"/v1/admin/ui/clients/{client_id}?note_type=complaint",
            headers=headers,
        )
        assert response.status_code == 200
        assert "Complaint note" in response.text
        assert "General note" not in response.text
        assert "Praise note" not in response.text
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_admin_client_risk_flags_and_filters(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    previous_complaints_window = settings.client_risk_complaints_window_days
    previous_complaints_threshold = settings.client_risk_complaints_threshold
    previous_feedback_window = settings.client_risk_feedback_window_days
    previous_avg_threshold = settings.client_risk_avg_rating_threshold
    previous_low_rating_threshold = settings.client_risk_low_rating_threshold
    previous_low_rating_count_threshold = settings.client_risk_low_rating_count_threshold
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    settings.client_risk_complaints_window_days = 90
    settings.client_risk_complaints_threshold = 2
    settings.client_risk_feedback_window_days = 30
    settings.client_risk_avg_rating_threshold = 3.0
    settings.client_risk_low_rating_threshold = 2
    settings.client_risk_low_rating_count_threshold = 2

    try:
        risky_id, complaints_id, low_ratings_id, safe_id = _seed_clients_with_risk_flags(
            async_session_maker
        )
        headers = _basic_auth("admin", "secret")

        response = client.get(f"/v1/admin/ui/clients/{risky_id}", headers=headers)
        assert response.status_code == 200
        assert "⚠️ Frequent complaints" in response.text
        assert "⭐ Low ratings" in response.text
        assert "Complaints last 90 days: 3" in response.text
        assert "Low ratings (≤2) last 30 days: 2" in response.text

        complaints_response = client.get(
            "/v1/admin/ui/clients?risk=frequent_complaints", headers=headers
        )
        assert complaints_response.status_code == 200
        assert "Risky Client" in complaints_response.text
        assert "Complaints Only" in complaints_response.text
        assert "Low Ratings Only" not in complaints_response.text
        assert "Safe Client" not in complaints_response.text

        low_ratings_response = client.get("/v1/admin/ui/clients?risk=low_rater", headers=headers)
        assert low_ratings_response.status_code == 200
        assert "Risky Client" in low_ratings_response.text
        assert "Low Ratings Only" in low_ratings_response.text
        assert "Complaints Only" not in low_ratings_response.text
        assert "Safe Client" not in low_ratings_response.text

        any_response = client.get("/v1/admin/ui/clients?risk=any", headers=headers)
        assert any_response.status_code == 200
        assert "Risky Client" in any_response.text
        assert "Complaints Only" in any_response.text
        assert "Low Ratings Only" in any_response.text
        assert "Safe Client" not in any_response.text
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password
        settings.client_risk_complaints_window_days = previous_complaints_window
        settings.client_risk_complaints_threshold = previous_complaints_threshold
        settings.client_risk_feedback_window_days = previous_feedback_window
        settings.client_risk_avg_rating_threshold = previous_avg_threshold
        settings.client_risk_low_rating_threshold = previous_low_rating_threshold
        settings.client_risk_low_rating_count_threshold = previous_low_rating_count_threshold


def test_admin_client_finance_section_is_org_scoped(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        client_id, invoice_number, other_invoice_number = _seed_client_finance(async_session_maker)
        headers = _basic_auth("admin", "secret")

        response = client.get(f"/v1/admin/ui/clients/{client_id}", headers=headers)
        assert response.status_code == 200
        assert "Finance" in response.text
        assert "LTV" in response.text
        assert "Avg check" in response.text
        assert "CAD 200.00" in response.text
        assert invoice_number in response.text
        assert other_invoice_number not in response.text
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
            data={"note_text": "Added note", "note_type": "COMPLAINT"},
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
                assert [note.note_type for note in notes] == [ClientNote.NOTE_TYPE_COMPLAINT]

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
