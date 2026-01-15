"""Tests for invoice list filters and bulk actions."""
import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.domain.bookings.db_models import Booking
from app.domain.invoices import service as invoice_service
from app.domain.invoices import statuses
from app.domain.invoices.db_models import Invoice
from app.domain.leads.db_models import Lead


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _lead_payload(name: str = "Test Client", email: str = "test@example.com") -> dict:
    return {
        "name": name,
        "phone": "780-555-1234",
        "email": email,
        "postal_code": "T5A",
        "address": "1 Test St",
        "preferred_dates": ["Mon"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": {
            "price_cents": 12000,
            "subtotal_cents": 12000,
            "tax_cents": 0,
            "pricing_config_version": "v1",
            "config_hash": "hash",
            "line_items": [],
        },
        "pricing_config_version": "v1",
        "config_hash": "hash",
    }


@pytest.mark.anyio
async def test_invoice_list_with_filters(client: AsyncClient, async_session_maker, admin_user_financeuser):
    """Test invoice list endpoint supports date range and amount filters."""
    async with async_session_maker() as session:
        # Create test leads
        lead1 = Lead(**_lead_payload(name="Alice Smith", email="alice@example.com"))
        lead2 = Lead(**_lead_payload(name="Bob Jones", email="bob@example.com"))
        session.add(lead1)
        session.add(lead2)
        await session.flush()

        # Create invoices with different dates and amounts
        today = date.today()
        last_week = today - timedelta(days=7)
        next_week = today + timedelta(days=7)

        # Invoice 1: Last week, $100
        invoice1_number = await invoice_service.generate_invoice_number(session, last_week)
        invoice1 = Invoice(
            invoice_number=invoice1_number,
            customer_id=lead1.lead_id,
            status=statuses.INVOICE_STATUS_SENT,
            issue_date=last_week,
            currency="CAD",
            subtotal_cents=10000,
            tax_cents=0,
            total_cents=10000,
        )
        session.add(invoice1)

        # Invoice 2: Today, $200
        invoice2_number = await invoice_service.generate_invoice_number(session, today)
        invoice2 = Invoice(
            invoice_number=invoice2_number,
            customer_id=lead2.lead_id,
            status=statuses.INVOICE_STATUS_OVERDUE,
            issue_date=today,
            currency="CAD",
            subtotal_cents=20000,
            tax_cents=0,
            total_cents=20000,
        )
        session.add(invoice2)

        # Invoice 3: Next week, $150
        invoice3_number = await invoice_service.generate_invoice_number(session, next_week)
        invoice3 = Invoice(
            invoice_number=invoice3_number,
            customer_id=lead1.lead_id,
            status=statuses.INVOICE_STATUS_DRAFT,
            issue_date=next_week,
            currency="CAD",
            subtotal_cents=15000,
            tax_cents=0,
            total_cents=15000,
        )
        session.add(invoice3)

        await session.commit()

    # Test date range filter
    headers = _auth_headers(admin_user_financeuser["username"], admin_user_financeuser["password"])
    response = await client.get(
        f"/v1/admin/invoices?from={last_week.isoformat()}&to={today.isoformat()}",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2  # Should only get invoice1 and invoice2

    # Test amount range filter (100-150 dollars = 10000-15000 cents)
    response = await client.get(
        "/v1/admin/invoices?amount_min=10000&amount_max=15000",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2  # Should get invoice1 and invoice3

    # Test search by client name
    response = await client.get(
        "/v1/admin/invoices?q=Alice",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2  # Alice has 2 invoices

    # Test search by client email
    response = await client.get(
        "/v1/admin/invoices?q=bob@example.com",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1  # Bob has 1 invoice


@pytest.mark.anyio
async def test_bulk_remind_requires_permission(client: AsyncClient, async_session_maker, admin_user_viewer):
    """Test bulk remind requires invoices.edit permission."""
    async with async_session_maker() as session:
        # Create a test invoice
        invoice_number = await invoice_service.generate_invoice_number(session, date.today())
        invoice = Invoice(
            invoice_number=invoice_number,
            status=statuses.INVOICE_STATUS_SENT,
            issue_date=date.today(),
            currency="CAD",
            subtotal_cents=10000,
            tax_cents=0,
            total_cents=10000,
        )
        session.add(invoice)
        await session.commit()
        invoice_id = invoice.invoice_id

    # Viewer role should not have invoices.edit permission
    headers = _auth_headers(admin_user_viewer["username"], admin_user_viewer["password"])
    response = await client.post(
        "/v1/admin/invoices/bulk/remind",
        headers=headers,
        json={"invoice_ids": [invoice_id]},
    )
    assert response.status_code == 403  # Forbidden


@pytest.mark.anyio
async def test_bulk_mark_paid_requires_permission(client: AsyncClient, async_session_maker, admin_user_viewer):
    """Test bulk mark paid requires payments.record permission."""
    async with async_session_maker() as session:
        # Create a test invoice
        invoice_number = await invoice_service.generate_invoice_number(session, date.today())
        invoice = Invoice(
            invoice_number=invoice_number,
            status=statuses.INVOICE_STATUS_SENT,
            issue_date=date.today(),
            currency="CAD",
            subtotal_cents=10000,
            tax_cents=0,
            total_cents=10000,
        )
        session.add(invoice)
        await session.commit()
        invoice_id = invoice.invoice_id

    # Viewer role should not have payments.record permission
    headers = _auth_headers(admin_user_viewer["username"], admin_user_viewer["password"])
    response = await client.post(
        "/v1/admin/invoices/bulk/mark_paid",
        headers=headers,
        json={"invoice_ids": [invoice_id], "method": "cash", "note": "Test payment"},
    )
    assert response.status_code == 403  # Forbidden


@pytest.mark.anyio
async def test_bulk_mark_paid_updates_invoice_status(client: AsyncClient, async_session_maker, admin_user_financeuser):
    """Test bulk mark paid correctly updates invoice status to PAID."""
    async with async_session_maker() as session:
        # Create test invoices
        invoice1_number = await invoice_service.generate_invoice_number(session, date.today())
        invoice1 = Invoice(
            invoice_number=invoice1_number,
            status=statuses.INVOICE_STATUS_SENT,
            issue_date=date.today(),
            currency="CAD",
            subtotal_cents=10000,
            tax_cents=0,
            total_cents=10000,
        )
        session.add(invoice1)

        invoice2_number = await invoice_service.generate_invoice_number(session, date.today())
        invoice2 = Invoice(
            invoice_number=invoice2_number,
            status=statuses.INVOICE_STATUS_OVERDUE,
            issue_date=date.today(),
            currency="CAD",
            subtotal_cents=15000,
            tax_cents=0,
            total_cents=15000,
        )
        session.add(invoice2)

        await session.commit()
        invoice1_id = invoice1.invoice_id
        invoice2_id = invoice2.invoice_id

    # Mark both as paid
    headers = _auth_headers(admin_user_financeuser["username"], admin_user_financeuser["password"])
    response = await client.post(
        "/v1/admin/invoices/bulk/mark_paid",
        headers=headers,
        json={"invoice_ids": [invoice1_id, invoice2_id], "method": "cash", "note": "Bulk payment test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["succeeded"]) == 2
    assert len(data["failed"]) == 0

    # Verify status updated
    async with async_session_maker() as session:
        updated_invoice1 = await session.get(Invoice, invoice1_id)
        updated_invoice2 = await session.get(Invoice, invoice2_id)
        assert updated_invoice1.status == statuses.INVOICE_STATUS_PAID
        assert updated_invoice2.status == statuses.INVOICE_STATUS_PAID


@pytest.mark.anyio
async def test_bulk_mark_paid_skips_already_paid(client: AsyncClient, async_session_maker, admin_user_financeuser):
    """Test bulk mark paid skips invoices that are already paid."""
    async with async_session_maker() as session:
        # Create a paid invoice
        invoice_number = await invoice_service.generate_invoice_number(session, date.today())
        invoice = Invoice(
            invoice_number=invoice_number,
            status=statuses.INVOICE_STATUS_PAID,
            issue_date=date.today(),
            currency="CAD",
            subtotal_cents=10000,
            tax_cents=0,
            total_cents=10000,
        )
        session.add(invoice)

        # Add a payment to make it fully paid
        payment = await invoice_service.record_manual_payment(
            session=session,
            invoice=invoice,
            amount_cents=10000,
            method="cash",
        )

        await session.commit()
        invoice_id = invoice.invoice_id

    # Try to mark as paid
    headers = _auth_headers(admin_user_financeuser["username"], admin_user_financeuser["password"])
    response = await client.post(
        "/v1/admin/invoices/bulk/mark_paid",
        headers=headers,
        json={"invoice_ids": [invoice_id], "method": "cash", "note": "Test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["succeeded"]) == 0
    assert len(data["failed"]) == 1
    assert "already paid" in data["failed"][0]["error"].lower()


@pytest.mark.anyio
async def test_bulk_mark_paid_rejects_void_invoices(client: AsyncClient, async_session_maker, admin_user_financeuser):
    """Test bulk mark paid rejects void invoices."""
    async with async_session_maker() as session:
        # Create a void invoice
        invoice_number = await invoice_service.generate_invoice_number(session, date.today())
        invoice = Invoice(
            invoice_number=invoice_number,
            status=statuses.INVOICE_STATUS_VOID,
            issue_date=date.today(),
            currency="CAD",
            subtotal_cents=10000,
            tax_cents=0,
            total_cents=10000,
        )
        session.add(invoice)
        await session.commit()
        invoice_id = invoice.invoice_id

    # Try to mark as paid
    headers = _auth_headers(admin_user_financeuser["username"], admin_user_financeuser["password"])
    response = await client.post(
        "/v1/admin/invoices/bulk/mark_paid",
        headers=headers,
        json={"invoice_ids": [invoice_id], "method": "cash", "note": "Test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["succeeded"]) == 0
    assert len(data["failed"]) == 1
    assert "void" in data["failed"][0]["error"].lower()
