import asyncio
import base64
import uuid
from datetime import date, datetime, timezone

from app.domain.bookings.db_models import Booking, Team
from app.domain.invoices import service as invoice_service
from app.domain.invoices.schemas import InvoiceItemCreate
from app.domain.leads.db_models import Lead
from app.domain.saas.db_models import Organization
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _seed_invoice(async_session_maker, org_id: uuid.UUID, name_suffix: str):
    async def create():
        async with async_session_maker() as session:
            session.add(Organization(org_id=org_id, name=f"Org {name_suffix}"))
            await session.flush()

            team = Team(org_id=org_id, name=f"Team {name_suffix}")
            session.add(team)
            await session.flush()

            lead = Lead(
                org_id=org_id,
                name="PDF Test Lead",
                phone="+1 555-555-0100",
                email="pdf.test@example.com",
                postal_code="H0H0H0",
                address="123 Test St",
                preferred_dates=["Mon"],
                structured_inputs={"beds": 1, "baths": 1, "cleaning_type": "standard"},
                estimate_snapshot={
                    "price_cents": 15000,
                    "subtotal_cents": 15000,
                    "tax_cents": 0,
                    "pricing_config_version": "v1",
                    "config_hash": "seed-config",
                    "line_items": [],
                },
                pricing_config_version="v1",
                config_hash="seed-config",
                referral_code=uuid.uuid4().hex[:16],
            )
            session.add(lead)
            await session.flush()

            booking = Booking(
                org_id=org_id,
                team_id=team.team_id,
                lead_id=lead.lead_id,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=60,
                status="PENDING",
            )
            session.add(booking)
            await session.flush()

            invoice = await invoice_service.create_invoice_from_order(
                session=session,
                order=booking,
                items=[InvoiceItemCreate(description="PDF Seed", qty=1, unit_price_cents=15000)],
                issue_date=date.today(),
                due_date=date.today(),
                currency="CAD",
                notes="Seed invoice for PDF",
                created_by="admin",
            )
            token = await invoice_service.upsert_public_token(session, invoice)
            await session.commit()
            return invoice.invoice_id, token

    return asyncio.run(create())


def test_admin_invoice_pdf_org_scoped(client, async_session_maker):
    previous_username = settings.admin_basic_username
    previous_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    try:
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()
        invoice_a, _ = _seed_invoice(async_session_maker, org_a, "A")
        invoice_b, _ = _seed_invoice(async_session_maker, org_b, "B")

        headers_a = {**_basic_auth("admin", "secret"), "X-Test-Org": str(org_a)}

        ok_response = client.get(f"/v1/admin/invoices/{invoice_a}/pdf", headers=headers_a)
        assert ok_response.status_code == 200
        assert ok_response.headers["content-type"].startswith("application/pdf")
        assert ok_response.content

        blocked_response = client.get(f"/v1/admin/invoices/{invoice_b}/pdf", headers=headers_a)
        assert blocked_response.status_code == 404
    finally:
        settings.admin_basic_username = previous_username
        settings.admin_basic_password = previous_password


def test_public_invoice_pdf_token_validation(client, async_session_maker):
    org_id = uuid.uuid4()
    _invoice_id, token = _seed_invoice(async_session_maker, org_id, "Public")

    response = client.get(f"/i/{token}.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content

    api_response = client.get(f"/v1/public/invoices/{token}/pdf")
    assert api_response.status_code == 200
    assert api_response.headers["content-type"].startswith("application/pdf")
    assert api_response.content

    invalid_response = client.get("/v1/public/invoices/invalid-token/pdf")
    assert invalid_response.status_code == 404
