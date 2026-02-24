import base64
import uuid
from datetime import date, datetime, timezone

import pytest
import sqlalchemy as sa

from app.domain.bookings.db_models import Booking, OrderPhoto
from app.domain.data_rights import service as data_rights_service
from app.domain.data_rights.db_models import DataExportRequest
from app.domain.invoices.db_models import Invoice, Payment
from app.domain.leads.db_models import Lead
from app.domain.saas.db_models import Organization
from app.infra.storage.backends import InMemoryStorageBackend
from app.settings import settings


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def _seed_lead(session, *, org_id: uuid.UUID, email: str | None = None) -> Lead:
    lead = Lead(
        org_id=org_id,
        name="Test Lead",
        phone="123",
        email=email,
        preferred_dates=[],
        structured_inputs={"beds": 1},
        estimate_snapshot={"total": 100},
        pricing_config_version="test",
        config_hash="hash",
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    return lead


async def _seed_booking_invoice_payment(session, lead: Lead) -> tuple[Booking, Invoice, Payment, OrderPhoto]:
    booking = Booking(
        org_id=lead.org_id,
        team_id=1,
        lead_id=lead.lead_id,
        starts_at=datetime.now(tz=timezone.utc),
        duration_minutes=60,
        status="CONFIRMED",
        consent_photos=True,
    )
    session.add(booking)
    await session.flush()

    invoice = Invoice(
        org_id=lead.org_id,
        invoice_number=f"INV-{uuid.uuid4()}",
        customer_id=lead.lead_id,
        order_id=booking.booking_id,
        status="SENT",
        issue_date=date.today(),
        due_date=date.today(),
        currency="USD",
        subtotal_cents=1000,
        taxable_subtotal_cents=1000,
        tax_cents=0,
        total_cents=1000,
    )
    session.add(invoice)
    await session.flush()

    payment = Payment(
        org_id=lead.org_id,
        invoice_id=invoice.invoice_id,
        booking_id=booking.booking_id,
        provider="manual",
        method="card",
        amount_cents=1000,
        currency="USD",
        status="succeeded",
        received_at=datetime.now(tz=timezone.utc),
    )
    session.add(payment)

    photo = OrderPhoto(
        org_id=lead.org_id,
        order_id=booking.booking_id,
        phase="before",
        filename="test.jpg",
        original_filename="test.jpg",
        content_type="image/jpeg",
        size_bytes=10,
        sha256="deadbeef",
        uploaded_by="admin",
        storage_provider="local",
        storage_key="orders/key",
    )
    session.add(photo)
    await session.commit()
    await session.refresh(booking)
    await session.refresh(invoice)
    await session.refresh(payment)
    await session.refresh(photo)
    return booking, invoice, payment, photo


@pytest.mark.anyio
async def test_export_is_org_scoped(async_session_maker, client):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    async with async_session_maker() as session:
        other_org = Organization(name="Other")
        session.add(other_org)
        await session.commit()
        await session.refresh(other_org)

        lead_one = await _seed_lead(session, org_id=settings.default_org_id, email="client@example.com")
        lead_two = await _seed_lead(session, org_id=other_org.org_id, email="client@example.com")
        await _seed_booking_invoice_payment(session, lead_one)
        await _seed_booking_invoice_payment(session, lead_two)

    headers = _basic_auth_header("admin", "secret")
    response = client.post(
        "/v1/admin/data/export",
        json={"email": "client@example.com"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["leads"]) == 1
    assert payload["leads"][0]["lead_id"] == lead_one.lead_id

    # Ensure cross-org data is gated when switching org context
    response_other = client.post(
        "/v1/admin/data/export",
        json={"email": "client@example.com"},
        headers={**headers, "X-Test-Org": str(other_org.org_id)},
    )
    assert response_other.status_code == 200
    payload_other = response_other.json()
    assert len(payload_other["leads"]) == 1
    assert payload_other["leads"][0]["lead_id"] == lead_two.lead_id


@pytest.mark.anyio
async def test_export_filters_sensitive_tokens(async_session_maker, client):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    async with async_session_maker() as session:
        lead = await _seed_lead(session, org_id=settings.default_org_id, email="safe@example.com")
        booking, invoice, payment, photo = await _seed_booking_invoice_payment(session, lead)

    headers = _basic_auth_header("admin", "secret")
    response = client.post(
        "/v1/admin/data/export",
        json={"lead_id": lead.lead_id},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()

    booking_payload = data["bookings"][0]
    assert "stripe_checkout_session_id" not in booking_payload
    assert "stripe_payment_intent_id" not in booking_payload

    invoice_payload = data["invoices"][0]
    assert "public_token" not in invoice_payload

    payment_payload = data["payments"][0]
    assert "payment_intent_id" not in payment_payload
    assert payment_payload["reference"] is None

    photo_payload = data["photos"][0]
    assert photo_payload["storage_key"] == "orders/key"


@pytest.mark.anyio
async def test_deletion_workflow_anonymizes_but_keeps_ledger(async_session_maker, client):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    async with async_session_maker() as session:
        lead = await _seed_lead(session, org_id=settings.default_org_id, email="erase@example.com")
        booking, invoice, payment, photo = await _seed_booking_invoice_payment(session, lead)

    headers = _basic_auth_header("admin", "secret")
    request_resp = client.post(
        "/v1/admin/data-deletion/requests",
        json={"lead_id": lead.lead_id, "reason": "requested"},
        headers=headers,
    )
    assert request_resp.status_code == 200

    cleanup_resp = client.post("/v1/admin/retention/cleanup", headers=headers)
    assert cleanup_resp.status_code == 200
    cleanup_payload = cleanup_resp.json()
    assert cleanup_payload["processed"] == 1

    async with async_session_maker() as session:
        updated_lead = await session.get(Lead, lead.lead_id)
        assert updated_lead.email is None
        assert updated_lead.pending_deletion is False
        assert updated_lead.deleted_at is not None

        updated_booking = await session.get(Booking, booking.booking_id)
        assert updated_booking.lead_id is None

        updated_invoice = await session.get(Invoice, invoice.invoice_id)
        assert updated_invoice is not None
        assert updated_invoice.customer_id is None
        assert updated_invoice.total_cents == 1000

        photos = (await session.execute(
            sa.select(OrderPhoto).where(OrderPhoto.order_id == booking.booking_id)
        )).scalars().all()
        assert len(photos) == 0


def test_build_chunked_query_parses_uuid_cursor_for_uuid_keys():
    cursor = str(uuid.uuid4())

    stmt = data_rights_service._build_chunked_query(
        DataExportRequest,
        DataExportRequest.export_id,
        [DataExportRequest.org_id == uuid.uuid4()],
        limit=10,
        cursor=cursor,
    )

    params = stmt.compile().params
    assert any(isinstance(value, uuid.UUID) for value in params.values())


def test_build_chunked_query_rejects_invalid_uuid_cursor_for_uuid_keys():
    with pytest.raises(ValueError):
        data_rights_service._build_chunked_query(
            DataExportRequest,
            DataExportRequest.export_id,
            [DataExportRequest.org_id == uuid.uuid4()],
            limit=10,
            cursor="not-a-uuid",
        )


def test_build_chunked_query_keeps_string_cursor_for_non_uuid_keys():
    stmt = data_rights_service._build_chunked_query(
        Booking,
        Booking.team_id,
        [Booking.org_id == uuid.uuid4()],
        limit=10,
        cursor="123",
    )

    params = stmt.compile().params
    assert "123" in params.values()


@pytest.mark.anyio
async def test_generate_data_export_bundle_marks_failed_on_invalid_cursor(async_session_maker, monkeypatch):
    async with async_session_maker() as session:
        lead = await _seed_lead(session, org_id=settings.default_org_id, email="invalid-job-cursor@example.com")
        await _seed_booking_invoice_payment(session, lead)

        record = await data_rights_service.create_data_export_request(
            session,
            org_id=settings.default_org_id,
            subject_id=lead.lead_id,
            subject_type="lead",
            subject_email=lead.email,
            requested_by="qa@example.com",
            requested_by_type="admin",
            request_id="req-invalid-cursor",
        )
        await session.commit()

        original_parse = data_rights_service._parse_chunk_cursor_value

        def _raise_on_followup_cursor(key_column, cursor):
            if cursor is not None:
                raise ValueError("invalid_cursor")
            return original_parse(key_column, cursor)

        monkeypatch.setattr(data_rights_service, "_EXPORT_QUERY_BATCH_SIZE", 1)
        monkeypatch.setattr(data_rights_service, "_parse_chunk_cursor_value", _raise_on_followup_cursor)

        updated = await data_rights_service.generate_data_export_bundle(
            session,
            export_request=record,
            storage_backend=InMemoryStorageBackend(),
        )

        assert updated.status == "failed"
        assert updated.error_code == "invalid_cursor"


@pytest.mark.anyio
async def test_generate_data_export_bundle_marks_failed_when_query_builder_raises_value_error(
    async_session_maker,
    monkeypatch,
):
    class _TrackingStorage(InMemoryStorageBackend):
        def __init__(self) -> None:
            super().__init__()
            self.called = False

        async def put(self, *, key: str, body, content_type: str):  # noqa: ANN001, ANN201
            self.called = True
            return await super().put(key=key, body=body, content_type=content_type)

    async with async_session_maker() as session:
        lead = await _seed_lead(session, org_id=settings.default_org_id, email="invalid-build-cursor@example.com")

        record = await data_rights_service.create_data_export_request(
            session,
            org_id=settings.default_org_id,
            subject_id=lead.lead_id,
            subject_type="lead",
            subject_email=lead.email,
            requested_by="qa@example.com",
            requested_by_type="admin",
            request_id="req-invalid-build-cursor",
        )
        await session.commit()

        def _raise_immediately(*_args, **_kwargs):
            raise ValueError("invalid_cursor")

        storage = _TrackingStorage()
        monkeypatch.setattr(data_rights_service, "_build_chunked_query", _raise_immediately)

        updated = await data_rights_service.generate_data_export_bundle(
            session,
            export_request=record,
            storage_backend=storage,
        )

        assert updated.status == "failed"
        assert updated.error_code == "invalid_cursor"
        assert storage.called is False
