import asyncio
import base64
import uuid
from datetime import datetime, timezone

from app.domain.bookings.db_models import Booking, Team
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice
from app.domain.leads.db_models import Lead
from app.domain.saas.db_models import Organization
from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def _seed_org(async_session_maker, org_id: uuid.UUID, name: str) -> int:
    async with async_session_maker() as session:
        session.add(Organization(org_id=org_id, name=name))
        team = Team(org_id=org_id, name=f"{name} Team")
        session.add(team)
        await session.flush()
        team_id = team.team_id
        await session.commit()
        return team_id


async def _seed_lead(async_session_maker, org_id: uuid.UUID, source: str, created_at: datetime) -> str:
    async with async_session_maker() as session:
        lead = Lead(
            org_id=org_id,
            name="Marketing Lead",
            phone="555-0001",
            structured_inputs={},
            estimate_snapshot={},
            pricing_config_version="v1",
            config_hash="hash",
            status="NEW",
            source=source,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(lead)
        await session.commit()
        return lead.lead_id


async def _seed_booking(
    async_session_maker, org_id: uuid.UUID, team_id: int, lead_id: str, created_at: datetime
) -> str:
    async with async_session_maker() as session:
        booking = Booking(
            org_id=org_id,
            team_id=team_id,
            lead_id=lead_id,
            starts_at=created_at,
            duration_minutes=90,
            status="SCHEDULED",
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(booking)
        await session.commit()
        return booking.booking_id


async def _seed_invoice(
    async_session_maker, org_id: uuid.UUID, booking_id: str, lead_id: str, created_at: datetime
) -> None:
    async with async_session_maker() as session:
        invoice = Invoice(
            org_id=org_id,
            invoice_number=f"INV-{uuid.uuid4()}",
            order_id=booking_id,
            customer_id=lead_id,
            status=invoice_statuses.INVOICE_STATUS_PAID,
            issue_date=created_at.date(),
            currency="USD",
            subtotal_cents=10000,
            taxable_subtotal_cents=0,
            tax_cents=0,
            total_cents=10000,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(invoice)
        await session.commit()


def test_marketing_lead_source_analytics(client, async_session_maker):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    owner_headers = _auth_headers("owner", "secret")
    period = "2026-01"
    created_at = datetime(2026, 1, 5, tzinfo=timezone.utc)

    lead_id = asyncio.run(_seed_lead(async_session_maker, settings.default_org_id, "Google", created_at))
    booking_id = asyncio.run(_seed_booking(async_session_maker, settings.default_org_id, 1, lead_id, created_at))
    asyncio.run(_seed_invoice(async_session_maker, settings.default_org_id, booking_id, lead_id, created_at))

    spend_resp = client.put(
        "/v1/admin/marketing/spend",
        json={"source": "Google", "period": period, "amount_cents": 7500},
        headers=owner_headers,
    )
    assert spend_resp.status_code == 200

    analytics_resp = client.get(
        f"/v1/admin/marketing/analytics/lead-sources?period={period}",
        headers=owner_headers,
    )
    assert analytics_resp.status_code == 200
    payload = analytics_resp.json()
    entry = next(item for item in payload["sources"] if item["source"] == "Google")
    assert entry["leads_count"] == 1
    assert entry["bookings_count"] == 1
    assert entry["revenue_cents"] == 10000
    assert entry["spend_cents"] == 7500


def test_marketing_lead_source_org_scoping(client, async_session_maker):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    owner_headers = _auth_headers("owner", "secret")
    org_id = uuid.uuid4()
    team_id = asyncio.run(_seed_org(async_session_maker, org_id, "Scoped Org"))

    created_at = datetime(2026, 2, 12, tzinfo=timezone.utc)
    lead_id = asyncio.run(_seed_lead(async_session_maker, org_id, "Facebook", created_at))
    booking_id = asyncio.run(_seed_booking(async_session_maker, org_id, team_id, lead_id, created_at))
    asyncio.run(_seed_invoice(async_session_maker, org_id, booking_id, lead_id, created_at))

    default_resp = client.get(
        "/v1/admin/marketing/analytics/lead-sources?period=2026-02",
        headers=owner_headers,
    )
    assert default_resp.status_code == 200
    assert all(entry["source"] != "Facebook" for entry in default_resp.json()["sources"])

    scoped_headers = {**owner_headers, "X-Test-Org": str(org_id)}
    scoped_resp = client.get(
        "/v1/admin/marketing/analytics/lead-sources?period=2026-02",
        headers=scoped_headers,
    )
    assert scoped_resp.status_code == 200
    entry = next(item for item in scoped_resp.json()["sources"] if item["source"] == "Facebook")
    assert entry["leads_count"] == 1


def test_marketing_analytics_rbac(client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.dispatcher_basic_username = "dispatcher"
    settings.dispatcher_basic_password = "dispatch"
    settings.legacy_basic_auth_enabled = True

    dispatcher_headers = _auth_headers("dispatcher", "dispatch")

    analytics_resp = client.get(
        "/v1/admin/marketing/analytics/lead-sources?period=2026-01",
        headers=dispatcher_headers,
    )
    assert analytics_resp.status_code == 403

    spend_resp = client.put(
        "/v1/admin/marketing/spend",
        json={"source": "Google", "period": "2026-01", "amount_cents": 1000},
        headers=dispatcher_headers,
    )
    assert spend_resp.status_code == 403
