import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.domain.bookings.db_models import Booking, Team
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.saas.db_models import Organization
from app.settings import settings


def _auth() -> tuple[str, str]:
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    return (settings.admin_basic_username, settings.admin_basic_password)


def test_geo_analytics_aggregates_and_org_scope(client, async_session_maker):
    auth = _auth()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    start = now - timedelta(days=30)

    async def _seed() -> None:
        async with async_session_maker() as session:
            team_a = Team(org_id=org_a, name="Team A", zones=["North"])
            team_b = Team(org_id=org_b, name="Team B", zones=["South"])
            org_a_row = Organization(org_id=org_a, name="Org A")
            org_b_row = Organization(org_id=org_b, name="Org B")
            session.add_all([org_a_row, org_b_row, team_a, team_b])
            await session.flush()

            client_a = ClientUser(org_id=org_a, email="a@example.com", name="Client A")
            client_b = ClientUser(org_id=org_b, email="b@example.com", name="Client B")
            session.add_all([client_a, client_b])
            await session.flush()

            addr_a = ClientAddress(
                org_id=org_a,
                client_id=client_a.client_id,
                label="Downtown",
                address_text="123 Main St",
                lat=53.54,
                lng=-113.50,
            )
            addr_a2 = ClientAddress(
                org_id=org_a,
                client_id=client_a.client_id,
                label="North",
                address_text="999 North Ave",
                lat=None,
                lng=None,
            )
            addr_b = ClientAddress(
                org_id=org_b,
                client_id=client_b.client_id,
                label="South",
                address_text="1 South St",
                lat=53.49,
                lng=-113.55,
            )
            session.add_all([addr_a, addr_a2, addr_b])
            await session.flush()

            booking_a1 = Booking(
                org_id=org_a,
                team_id=team_a.team_id,
                address_id=addr_a.address_id,
                starts_at=now - timedelta(days=5),
                duration_minutes=90,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=25000,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            booking_a2 = Booking(
                org_id=org_a,
                team_id=team_a.team_id,
                address_id=addr_a.address_id,
                starts_at=now - timedelta(days=3),
                duration_minutes=60,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=15000,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            booking_a3 = Booking(
                org_id=org_a,
                team_id=team_a.team_id,
                address_id=addr_a2.address_id,
                starts_at=now - timedelta(days=2),
                duration_minutes=60,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=10000,
                refund_total_cents=2000,
                credit_note_total_cents=0,
            )
            booking_b = Booking(
                org_id=org_b,
                team_id=team_b.team_id,
                address_id=addr_b.address_id,
                starts_at=now - timedelta(days=1),
                duration_minutes=60,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=30000,
                refund_total_cents=0,
                credit_note_total_cents=0,
            )
            session.add_all([booking_a1, booking_a2, booking_a3, booking_b])
            await session.commit()

    asyncio.run(_seed())

    response = client.get(
        "/v1/admin/analytics/geo",
        auth=auth,
        headers={"X-Test-Org": str(org_a)},
        params={"from": start.isoformat()},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["by_area"] == [
        {
            "area": "Downtown",
            "bookings": 2,
            "revenue_cents": 40000,
            "avg_ticket_cents": 20000,
        },
        {
            "area": "North",
            "bookings": 1,
            "revenue_cents": 8000,
            "avg_ticket_cents": 8000,
        },
    ]
    assert payload["points"] == [
        {"lat": 53.54, "lng": -113.5, "count": 2},
    ]
