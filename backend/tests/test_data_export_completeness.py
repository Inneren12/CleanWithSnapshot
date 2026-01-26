import json
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.domain.bookings.db_models import Booking, OrderPhoto, Team
from app.domain.data_rights import service as data_rights_service
from app.domain.invoices.db_models import Invoice, Payment
from app.domain.leads.db_models import Lead
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import Organization
from app.infra.storage.backends import InMemoryStorageBackend
from app.jobs import data_export
from app.settings import settings

EXPORT_METADATA_KEYS = {
    "export_id",
    "org_id",
    "subject_id",
    "subject_type",
    "subject_email",
    "generated_at",
    "data",
}

EXPORT_CONTRACT = {
    "leads": {
        "lead_id",
        "name",
        "email",
        "phone",
        "status",
        "structured_inputs",
        "estimate_snapshot",
    },
    "bookings": {
        "booking_id",
        "lead_id",
        "status",
        "starts_at",
        "duration_minutes",
        "scheduled_date",
    },
    "invoices": {
        "invoice_id",
        "invoice_number",
        "status",
        "currency",
        "issue_date",
        "total_cents",
    },
    "payments": {
        "payment_id",
        "invoice_id",
        "amount_cents",
        "currency",
        "status",
        "provider",
    },
    "photos": {
        "photo_id",
        "order_id",
        "filename",
        "content_type",
        "size_bytes",
        "storage_key",
    },
}

SENSITIVE_TEST_VALUES = {
    "subject-access-token",
    "nested-refresh-token",
    "integration-secret",
    "signature-secret",
}


async def _get_or_create_team_id(session, org_id: uuid.UUID) -> int:
    result = await session.execute(select(Team).where(Team.org_id == org_id).order_by(Team.team_id))
    team = result.scalars().first()
    if team:
        return team.team_id
    team = Team(org_id=org_id, name=f"Team {org_id}")
    session.add(team)
    await session.flush()
    return team.team_id


async def _seed_subject_data(session, org_id: uuid.UUID, *, email: str, name: str) -> dict[str, str]:
    team_id = await _get_or_create_team_id(session, org_id)
    lead_id = str(uuid.uuid4())
    booking_id = str(uuid.uuid4())
    invoice_id = str(uuid.uuid4())
    payment_id = str(uuid.uuid4())
    photo_id = str(uuid.uuid4())
    lead = Lead(
        org_id=org_id,
        lead_id=lead_id,
        name=name,
        phone="555-0100",
        email=email,
        postal_code="90210",
        address="123 Privacy Ave",
        preferred_dates=["Mon"],
        structured_inputs={
            "beds": 2,
            "access_token": "subject-access-token",
            "nested": {"refresh_token": "nested-refresh-token"},
            "api_secret": "integration-secret",
        },
        estimate_snapshot={
            "total": 25000,
            "signature": "signature-secret",
        },
        pricing_config_version="v1",
        config_hash="config-hash",
    )
    lead.deleted_at = datetime.now(tz=timezone.utc)

    booking = Booking(
        org_id=org_id,
        booking_id=booking_id,
        team_id=team_id,
        lead_id=lead_id,
        starts_at=datetime.now(tz=timezone.utc),
        duration_minutes=120,
        status="CANCELLED",
        scheduled_date=date.today(),
        deposit_required=True,
        deposit_cents=5000,
        deposit_status="held",
        consent_photos=True,
    )
    booking.archived_at = datetime.now(tz=timezone.utc)

    invoice = Invoice(
        org_id=org_id,
        invoice_id=invoice_id,
        invoice_number=f"INV-{uuid.uuid4().hex[:8]}",
        order_id=booking_id,
        customer_id=lead_id,
        status="void",
        issue_date=date.today(),
        due_date=date.today(),
        currency="USD",
        subtotal_cents=20000,
        taxable_subtotal_cents=20000,
        tax_cents=500,
        total_cents=20500,
        notes="Test invoice",
        created_by="qa@example.com",
    )

    payment = Payment(
        org_id=org_id,
        payment_id=payment_id,
        invoice_id=invoice_id,
        booking_id=booking_id,
        provider="stripe",
        method="card",
        amount_cents=20500,
        currency="USD",
        status="failed",
        received_at=datetime.now(tz=timezone.utc),
        reference="payment-ref",
    )

    photo = OrderPhoto(
        org_id=org_id,
        photo_id=photo_id,
        order_id=booking_id,
        phase="AFTER",
        filename="after.jpg",
        original_filename="after_original.jpg",
        content_type="image/jpeg",
        size_bytes=12345,
        sha256="0" * 64,
        uploaded_by="admin",
        storage_provider="local",
        storage_key=f"org/{org_id}/bookings/{booking_id}/after.jpg",
        review_status="APPROVED",
        needs_retake=False,
    )

    session.add_all([lead, booking, invoice, payment, photo])
    await session.flush()
    return {
        "lead_id": lead_id,
        "booking_id": booking_id,
        "invoice_id": invoice_id,
        "payment_id": payment_id,
        "photo_id": photo_id,
    }


async def _seed_org_with_data(session, name: str, email: str) -> tuple[Organization, dict[str, str]]:
    org = await saas_service.create_organization(session, name)
    identifiers = await _seed_subject_data(session, org.org_id, email=email, name=f"{name} Lead")
    return org, identifiers


async def _run_export(session, org_id: uuid.UUID, lead_id: str, email: str) -> dict:
    storage = InMemoryStorageBackend()
    record = await data_rights_service.create_data_export_request(
        session,
        org_id=org_id,
        subject_id=lead_id,
        subject_type="lead",
        subject_email=email,
        requested_by="qa@example.com",
        requested_by_type="admin",
        request_id="req-export-completeness",
    )
    await session.commit()
    result = await data_export.run_pending_data_exports(session, storage_backend=storage)
    assert result["completed"] == 1
    await session.refresh(record)
    payload = await storage.read(key=record.storage_key)
    return json.loads(payload)


@pytest.mark.anyio
async def test_export_completeness_and_isolation(async_session_maker):
    async with async_session_maker() as session:
        org_a = await session.get(Organization, settings.default_org_id)
        if org_a is None:
            org_a = Organization(org_id=settings.default_org_id, name="Default Org")
            session.add(org_a)
            await session.flush()
        identifiers_a = await _seed_subject_data(
            session,
            org_a.org_id,
            email="subject-a@example.com",
            name="Subject A",
        )
        org_b, identifiers_b = await _seed_org_with_data(session, "Org B", "subject-b@example.com")
        await session.commit()

        payload = await _run_export(
            session, org_a.org_id, identifiers_a["lead_id"], "subject-a@example.com"
        )

    assert EXPORT_METADATA_KEYS.issubset(payload.keys())
    assert set(payload["data"].keys()) == set(EXPORT_CONTRACT.keys())

    data = payload["data"]
    for section, required_fields in EXPORT_CONTRACT.items():
        assert data[section], f"{section} section should not be empty"
        for record in data[section]:
            assert required_fields.issubset(record.keys())

    lead_ids = {lead["lead_id"] for lead in data["leads"]}
    booking_ids = {booking["booking_id"] for booking in data["bookings"]}
    invoice_ids = {invoice["invoice_id"] for invoice in data["invoices"]}
    payment_ids = {payment["payment_id"] for payment in data["payments"]}
    photo_ids = {photo["photo_id"] for photo in data["photos"]}

    assert identifiers_a["lead_id"] in lead_ids
    assert identifiers_a["booking_id"] in booking_ids
    assert identifiers_a["invoice_id"] in invoice_ids
    assert identifiers_a["payment_id"] in payment_ids
    assert identifiers_a["photo_id"] in photo_ids

    assert identifiers_b["lead_id"] not in lead_ids
    assert identifiers_b["booking_id"] not in booking_ids
    assert identifiers_b["invoice_id"] not in invoice_ids
    assert identifiers_b["payment_id"] not in payment_ids
    assert identifiers_b["photo_id"] not in photo_ids

    lead_payload = data["leads"][0]
    structured_inputs = lead_payload["structured_inputs"]
    assert structured_inputs["access_token"] == "[REDACTED]"
    assert structured_inputs["nested"]["refresh_token"] == "[REDACTED]"
    assert structured_inputs["api_secret"] == "[REDACTED]"
    assert lead_payload["estimate_snapshot"]["signature"] == "[REDACTED]"

    payload_text = json.dumps(payload)
    for value in SENSITIVE_TEST_VALUES:
        assert value not in payload_text
