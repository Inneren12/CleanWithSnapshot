import base64
import datetime as dt

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import ensure_default_team
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Payment
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _admin_creds():
    original = {
        "admin_basic_username": settings.admin_basic_username,
        "admin_basic_password": settings.admin_basic_password,
    }
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.mark.anyio
async def test_dispatcher_stats_counts_and_revenue(client, async_session_maker):
    target_date = dt.date(2024, 5, 10)
    starts_at = dt.datetime(2024, 5, 10, 15, 0, tzinfo=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(
            email="client@example.com",
            name="Jane Client",
            phone="+1 555-0100",
        )
        session.add(client_user)
        await session.flush()
        address = ClientAddress(
            client_id=client_user.client_id,
            label="Home",
            address_text="123 Main St",
            lat=53.5461,
            lng=-113.4938,
        )
        session.add(address)
        await session.flush()
        bookings = [
            Booking(
                team_id=team.team_id,
                starts_at=starts_at,
                duration_minutes=120,
                actual_duration_minutes=90,
                status="DONE",
                client_id=client_user.client_id,
                address_id=address.address_id,
            ),
            Booking(
                team_id=team.team_id,
                starts_at=starts_at + dt.timedelta(hours=2),
                duration_minutes=60,
                status="DONE",
                client_id=client_user.client_id,
                address_id=address.address_id,
            ),
            Booking(
                team_id=team.team_id,
                starts_at=starts_at + dt.timedelta(hours=1),
                duration_minutes=60,
                status="IN_PROGRESS",
                client_id=client_user.client_id,
                address_id=address.address_id,
            ),
            Booking(
                team_id=team.team_id,
                starts_at=starts_at + dt.timedelta(hours=3),
                duration_minutes=60,
                status="PLANNED",
                client_id=client_user.client_id,
                address_id=address.address_id,
            ),
            Booking(
                team_id=team.team_id,
                starts_at=starts_at + dt.timedelta(hours=4),
                duration_minutes=60,
                status="CANCELLED",
                client_id=client_user.client_id,
                address_id=address.address_id,
            ),
        ]
        session.add_all(bookings)
        await session.flush()
        payments = [
            Payment(
                booking_id=bookings[0].booking_id,
                provider="stripe",
                method="card",
                amount_cents=20000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=starts_at + dt.timedelta(hours=1),
            ),
            Payment(
                booking_id=bookings[0].booking_id,
                provider="stripe",
                method="card",
                amount_cents=15000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_FAILED,
                received_at=starts_at + dt.timedelta(hours=1),
            ),
            Payment(
                booking_id=bookings[1].booking_id,
                provider="stripe",
                method="card",
                amount_cents=5000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=starts_at - dt.timedelta(days=1),
            ),
        ]
        session.add_all(payments)
        await session.commit()

    response = client.get(
        "/v1/admin/dispatcher/stats",
        params={"date": target_date.isoformat(), "tz": "America/Edmonton"},
        headers=_basic_auth("admin", "secret"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["done_count"] == 2
    assert payload["in_progress_count"] == 1
    assert payload["planned_count"] == 1
    assert payload["avg_duration_hours"] == pytest.approx(1.25, rel=0.01)
    assert payload["revenue_today"] == 20000


@pytest.mark.anyio
async def test_dispatcher_board_zone_filter(client, async_session_maker):
    target_date = dt.date(2024, 5, 10)
    starts_at = dt.datetime(2024, 5, 10, 15, 0, tzinfo=dt.timezone.utc)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        client_user = ClientUser(email="zone@example.com", name="Zone Client", phone="+1 555-0101")
        session.add(client_user)
        await session.flush()
        downtown = ClientAddress(
            client_id=client_user.client_id,
            label="Downtown",
            address_text="Downtown",
            lat=53.5461,
            lng=-113.4938,
        )
        west = ClientAddress(
            client_id=client_user.client_id,
            label="West",
            address_text="West",
            lat=53.53,
            lng=-113.62,
        )
        session.add_all([downtown, west])
        await session.flush()
        session.add_all(
            [
                Booking(
                    team_id=team.team_id,
                    starts_at=starts_at,
                    duration_minutes=60,
                    status="PLANNED",
                    client_id=client_user.client_id,
                    address_id=downtown.address_id,
                ),
                Booking(
                    team_id=team.team_id,
                    starts_at=starts_at,
                    duration_minutes=60,
                    status="PLANNED",
                    client_id=client_user.client_id,
                    address_id=west.address_id,
                ),
            ]
        )
        await session.commit()

    response_all = client.get(
        "/v1/admin/dispatcher/board",
        params={"date": target_date.isoformat(), "tz": "America/Edmonton"},
        headers=_basic_auth("admin", "secret"),
    )
    response_zone = client.get(
        "/v1/admin/dispatcher/board",
        params={"date": target_date.isoformat(), "tz": "America/Edmonton", "zone": "Downtown"},
        headers=_basic_auth("admin", "secret"),
    )

    assert response_all.status_code == 200
    assert response_zone.status_code == 200
    assert len(response_all.json()["bookings"]) == 2
    zone_payload = response_zone.json()["bookings"]
    assert len(zone_payload) == 1
    assert zone_payload[0]["address"]["zone"] == "Downtown"
