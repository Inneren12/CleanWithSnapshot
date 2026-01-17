"""Finance balance sheet API tests for receivable totals and org scoping."""

import base64
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, Payment
from app.domain.saas.db_models import Organization
from app.main import app
from app.settings import settings

client = TestClient(app)


def _auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
async def org_a(db_session: AsyncSession) -> Organization:
    org_id = settings.default_org_id
    org = await db_session.get(Organization, org_id)
    if org is None:
        org = Organization(org_id=org_id, name="Org A")
        db_session.add(org)
    else:
        org.name = "Org A"
    await db_session.commit()
    return org


@pytest.fixture
async def org_b(db_session: AsyncSession) -> Organization:
    org = Organization(org_id=uuid.uuid4(), name="Org B")
    db_session.add(org)
    await db_session.commit()
    return org


@pytest.mark.anyio
async def test_finance_balance_sheet_receivables_and_scoping(
    db_session: AsyncSession,
    org_a: Organization,
    org_b: Organization,
) -> None:
    invoice_a1 = Invoice(
        invoice_id=str(uuid.uuid4()),
        org_id=org_a.org_id,
        invoice_number=f"A-{uuid.uuid4().hex[:6]}",
        status=invoice_statuses.INVOICE_STATUS_SENT,
        issue_date=date(2026, 4, 1),
        due_date=date(2026, 4, 15),
        currency="CAD",
        subtotal_cents=10000,
        taxable_subtotal_cents=0,
        tax_cents=0,
        total_cents=10000,
        notes=None,
        created_by="system",
        created_at=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
    )
    invoice_a2 = Invoice(
        invoice_id=str(uuid.uuid4()),
        org_id=org_a.org_id,
        invoice_number=f"A-{uuid.uuid4().hex[:6]}",
        status=invoice_statuses.INVOICE_STATUS_OVERDUE,
        issue_date=date(2026, 4, 5),
        due_date=date(2026, 4, 12),
        currency="CAD",
        subtotal_cents=8000,
        taxable_subtotal_cents=0,
        tax_cents=0,
        total_cents=8000,
        notes=None,
        created_by="system",
        created_at=datetime(2026, 4, 5, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 5, 9, 0, tzinfo=timezone.utc),
    )
    invoice_b = Invoice(
        invoice_id=str(uuid.uuid4()),
        org_id=org_b.org_id,
        invoice_number=f"B-{uuid.uuid4().hex[:6]}",
        status=invoice_statuses.INVOICE_STATUS_SENT,
        issue_date=date(2026, 4, 1),
        due_date=date(2026, 4, 15),
        currency="CAD",
        subtotal_cents=20000,
        taxable_subtotal_cents=0,
        tax_cents=0,
        total_cents=20000,
        notes=None,
        created_by="system",
        created_at=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
    )

    db_session.add_all([invoice_a1, invoice_a2, invoice_b])
    db_session.add_all(
        [
            Payment(
                org_id=org_a.org_id,
                invoice_id=invoice_a1.invoice_id,
                provider="manual",
                method="card",
                amount_cents=4000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 4, 3, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 4, 3, 9, 0, tzinfo=timezone.utc),
            ),
            Payment(
                org_id=org_a.org_id,
                invoice_id=invoice_a2.invoice_id,
                provider="manual",
                method="card",
                amount_cents=8000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc),
            ),
            Payment(
                org_id=org_b.org_id,
                invoice_id=invoice_b.invoice_id,
                provider="manual",
                method="cash",
                amount_cents=5000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 4, 5, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 4, 5, 9, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    await db_session.commit()

    headers = {
        **_auth_header("admin", "admin123"),
        "X-Test-Org": str(org_a.org_id),
    }
    response = client.get(
        "/v1/admin/finance/balance_sheet?as_of=2026-04-10",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["assets"]["accounts_receivable_cents"] == 14000
    assert payload["assets"]["cash"]["cash_cents"] is None
    assert payload["assets"]["total_assets_cents"] is None
    assert payload["liabilities"]["total_liabilities_cents"] == 0
    assert payload["equity"]["simplified_equity_cents"] is None
    assert any("Cash is reported as unknown" in note for note in payload["data_coverage_notes"])
