import base64
from datetime import date, datetime, timezone

import pytest

from app.domain.finance.db_models import FinanceExpense, FinanceExpenseCategory
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, Payment
from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.anyio
async def test_finance_gst_summary(client, async_session_maker):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    async with async_session_maker() as session:
        category = FinanceExpenseCategory(
            name="Supplies",
            default=False,
            sort_order=0,
        )
        session.add(category)
        await session.flush()

        expense = FinanceExpense(
            occurred_on=date(2026, 1, 15),
            category_id=category.category_id,
            vendor="Vendor",
            description="Cleaning supplies",
            amount_cents=2000,
            tax_cents=100,
        )
        session.add(expense)

        invoice = Invoice(
            invoice_number="INV-2026-0001",
            order_id=None,
            customer_id=None,
            status=invoice_statuses.INVOICE_STATUS_PAID,
            issue_date=date(2026, 1, 10),
            currency="CAD",
            subtotal_cents=10000,
            taxable_subtotal_cents=10000,
            tax_cents=500,
            total_cents=10500,
        )
        session.add(invoice)
        await session.flush()

        payment = Payment(
            invoice_id=invoice.invoice_id,
            booking_id=None,
            provider="manual",
            method=invoice_statuses.PAYMENT_METHOD_CASH,
            amount_cents=10500,
            currency="CAD",
            status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            received_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
        )
        session.add(payment)
        await session.commit()

    headers = _auth_headers("admin", "secret")
    response = client.get(
        "/v1/admin/finance/taxes/gst_summary?from=2026-01-01&to=2026-01-31",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tax_collected_cents"] == 500
    assert payload["tax_paid_cents"] == 100
    assert payload["tax_owed_cents"] == 400


@pytest.mark.anyio
async def test_finance_tax_instalments_crud(client):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    headers = _auth_headers("admin", "secret")

    create_response = client.post(
        "/v1/admin/finance/taxes/instalments",
        headers=headers,
        json={
            "tax_type": "GST",
            "due_on": "2026-02-15",
            "amount_cents": 25000,
            "note": "Q1 instalment",
        },
    )
    assert create_response.status_code == 201
    instalment_id = create_response.json()["instalment_id"]

    update_response = client.patch(
        f"/v1/admin/finance/taxes/instalments/{instalment_id}",
        headers=headers,
        json={
            "paid_on": "2026-02-10",
            "note": "Paid early",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["paid_on"] == "2026-02-10"

    list_response = client.get(
        "/v1/admin/finance/taxes/instalments?from=2026-01-01&to=2026-12-31",
        headers=headers,
    )
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert any(item["instalment_id"] == instalment_id for item in items)


@pytest.mark.anyio
async def test_finance_tax_export_mime_type(client):
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    headers = _auth_headers("admin", "secret")

    response = client.get(
        "/v1/admin/finance/taxes/export?from=2026-01-01&to=2026-01-31",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
