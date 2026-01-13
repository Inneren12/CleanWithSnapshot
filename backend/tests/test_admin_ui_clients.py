import asyncio
import base64
import uuid
from datetime import datetime, timezone

from app.domain.bookings.db_models import Booking, Team
from app.domain.clients.db_models import ClientUser
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

        async def verify_booking():
            async with async_session_maker() as session:
                refreshed = await session.get(Booking, booking_id)
                assert refreshed is not None
                assert refreshed.client_id == active_client_id

        asyncio.run(verify_booking())
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password
