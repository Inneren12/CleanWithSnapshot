import asyncio
import uuid
from datetime import datetime, timezone

from app.domain.bookings.db_models import Booking, Team
from app.domain.clients.db_models import ClientUser
from app.domain.invoices.db_models import Payment
from app.domain.invoices.statuses import PAYMENT_STATUS_SUCCEEDED
from app.domain.saas.db_models import Organization
from app.settings import settings


def _auth() -> tuple[str, str]:
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    return (settings.admin_basic_username, settings.admin_basic_password)


def _payment(
    *,
    booking_id: str,
    org_id: uuid.UUID,
    amount_cents: int,
    received_at: datetime,
) -> Payment:
    return Payment(
        booking_id=booking_id,
        org_id=org_id,
        provider="manual",
        method="cash",
        status=PAYMENT_STATUS_SUCCEEDED,
        currency="CAD",
        amount_cents=amount_cents,
        received_at=received_at,
    )


def test_client_clv_uses_paid_revenue(client, async_session_maker):
    auth = _auth()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    now = datetime(2025, 6, 1, tzinfo=timezone.utc)

    async def _seed() -> None:
        async with async_session_maker() as session:
            org_a_row = Organization(org_id=org_a, name="Org A")
            org_b_row = Organization(org_id=org_b, name="Org B")
            team_a = Team(org_id=org_a, name="Team A")
            team_b = Team(org_id=org_b, name="Team B")
            session.add_all([org_a_row, org_b_row, team_a, team_b])
            await session.flush()

            client_a = ClientUser(org_id=org_a, email="a@example.com", name="Client A")
            client_b = ClientUser(org_id=org_a, email="b@example.com", name="Client B")
            client_c = ClientUser(org_id=org_b, email="c@example.com", name="Client C")
            session.add_all([client_a, client_b, client_c])
            await session.flush()

            booking_a = Booking(
                org_id=org_a,
                team_id=team_a.team_id,
                client_id=client_a.client_id,
                starts_at=now,
                duration_minutes=60,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=10000,
            )
            booking_b = Booking(
                org_id=org_a,
                team_id=team_a.team_id,
                client_id=client_b.client_id,
                starts_at=now,
                duration_minutes=90,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=30000,
            )
            booking_c = Booking(
                org_id=org_b,
                team_id=team_b.team_id,
                client_id=client_c.client_id,
                starts_at=now,
                duration_minutes=90,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=30000,
            )
            session.add_all([booking_a, booking_b, booking_c])
            await session.flush()

            payments = [
                _payment(
                    booking_id=booking_a.booking_id,
                    org_id=org_a,
                    amount_cents=10000,
                    received_at=now,
                ),
                _payment(
                    booking_id=booking_a.booking_id,
                    org_id=org_a,
                    amount_cents=5000,
                    received_at=now,
                ),
                _payment(
                    booking_id=booking_b.booking_id,
                    org_id=org_a,
                    amount_cents=30000,
                    received_at=now,
                ),
                _payment(
                    booking_id=booking_c.booking_id,
                    org_id=org_b,
                    amount_cents=99999,
                    received_at=now,
                ),
            ]
            session.add_all(payments)
            await session.commit()

    asyncio.run(_seed())

    response = client.get(
        "/v1/admin/analytics/clients/clv",
        auth=auth,
        headers={"X-Test-Org": str(org_a)},
        params={"from": "2025-01-01T00:00:00Z", "to": "2025-12-31T23:59:59Z", "top": 1},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["average_clv_cents"] == 22500.0
    assert payload["median_clv_cents"] == 22500.0
    assert payload["top_clients"][0]["name"] == "Client B"
    assert payload["top_clients"][0]["total_paid_cents"] == 30000
    assert payload["top_clients"][0]["payments_count"] == 1


def test_client_retention_cohort_shape(client, async_session_maker):
    auth = _auth()
    org_id = uuid.uuid4()

    async def _seed() -> None:
        async with async_session_maker() as session:
            org = Organization(org_id=org_id, name="Org A")
            team = Team(org_id=org_id, name="Team Retention")
            session.add_all([org, team])
            await session.flush()

            client_1 = ClientUser(org_id=org_id, email="jan@example.com", name="Jan")
            client_2 = ClientUser(org_id=org_id, email="jan2@example.com", name="Jan 2")
            client_3 = ClientUser(org_id=org_id, email="feb@example.com", name="Feb")
            client_4 = ClientUser(org_id=org_id, email="mar@example.com", name="Mar")
            session.add_all([client_1, client_2, client_3, client_4])
            await session.flush()

            booking_1 = Booking(
                org_id=org_id,
                team_id=team.team_id,
                client_id=client_1.client_id,
                starts_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
                duration_minutes=60,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=10000,
            )
            booking_2 = Booking(
                org_id=org_id,
                team_id=team.team_id,
                client_id=client_2.client_id,
                starts_at=datetime(2025, 1, 6, tzinfo=timezone.utc),
                duration_minutes=60,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=10000,
            )
            booking_3 = Booking(
                org_id=org_id,
                team_id=team.team_id,
                client_id=client_3.client_id,
                starts_at=datetime(2025, 2, 5, tzinfo=timezone.utc),
                duration_minutes=60,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=10000,
            )
            booking_4 = Booking(
                org_id=org_id,
                team_id=team.team_id,
                client_id=client_4.client_id,
                starts_at=datetime(2025, 3, 5, tzinfo=timezone.utc),
                duration_minutes=60,
                status="DONE",
                deposit_required=False,
                deposit_policy=[],
                base_charge_cents=10000,
            )
            session.add_all([booking_1, booking_2, booking_3, booking_4])
            await session.flush()

            session.add_all(
                [
                    _payment(
                        booking_id=booking_1.booking_id,
                        org_id=org_id,
                        amount_cents=10000,
                        received_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
                    ),
                    _payment(
                        booking_id=booking_1.booking_id,
                        org_id=org_id,
                        amount_cents=10000,
                        received_at=datetime(2025, 2, 6, tzinfo=timezone.utc),
                    ),
                    _payment(
                        booking_id=booking_2.booking_id,
                        org_id=org_id,
                        amount_cents=10000,
                        received_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
                    ),
                    _payment(
                        booking_id=booking_3.booking_id,
                        org_id=org_id,
                        amount_cents=10000,
                        received_at=datetime(2025, 2, 12, tzinfo=timezone.utc),
                    ),
                    _payment(
                        booking_id=booking_3.booking_id,
                        org_id=org_id,
                        amount_cents=10000,
                        received_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
                    ),
                    _payment(
                        booking_id=booking_4.booking_id,
                        org_id=org_id,
                        amount_cents=10000,
                        received_at=datetime(2025, 3, 18, tzinfo=timezone.utc),
                    ),
                ]
            )
            await session.commit()

    asyncio.run(_seed())

    response = client.get(
        "/v1/admin/analytics/clients/retention",
        auth=auth,
        headers={"X-Test-Org": str(org_id)},
        params={"cohort": "monthly", "months": 3},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["months"] == 3
    assert [row["cohort_month"] for row in payload["cohorts"]] == [
        "2025-01-01T00:00:00Z",
        "2025-02-01T00:00:00Z",
        "2025-03-01T00:00:00Z",
    ]
    assert payload["cohorts"][0]["retention"] == [1.0, 0.5, 0.0]
    assert payload["cohorts"][1]["retention"] == [1.0, 1.0, None]
    assert payload["cohorts"][2]["retention"] == [1.0, None, None]
