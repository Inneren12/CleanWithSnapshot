"""Finance P&L API tests for deterministic totals, org scoping, and RBAC."""

import base64
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.finance.db_models import FinanceExpense, FinanceExpenseCategory
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Payment
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


@pytest.fixture
async def categories(db_session: AsyncSession, org_a: Organization) -> tuple[FinanceExpenseCategory, FinanceExpenseCategory]:
    supplies = FinanceExpenseCategory(
        category_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Supplies",
        default=False,
        sort_order=1,
    )
    travel = FinanceExpenseCategory(
        category_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Travel",
        default=False,
        sort_order=2,
    )
    db_session.add_all([supplies, travel])
    await db_session.commit()
    return supplies, travel


@pytest.mark.anyio
async def test_finance_pnl_totals_and_scoping(
    db_session: AsyncSession,
    org_a: Organization,
    org_b: Organization,
    categories: tuple[FinanceExpenseCategory, FinanceExpenseCategory],
) -> None:
    supplies, travel = categories

    other_category = FinanceExpenseCategory(
        category_id=uuid.uuid4(),
        org_id=org_b.org_id,
        name="Other Org",
        default=False,
        sort_order=1,
    )
    db_session.add(other_category)
    await db_session.flush()

    db_session.add_all(
        [
            Payment(
                org_id=org_a.org_id,
                provider="manual",
                method="cash",
                amount_cents=10000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc),
            ),
            Payment(
                org_id=org_a.org_id,
                provider="manual",
                method="card",
                amount_cents=5000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=None,
                created_at=datetime(2026, 1, 20, 9, 0, tzinfo=timezone.utc),
            ),
            Payment(
                org_id=org_a.org_id,
                provider="manual",
                method="cash",
                amount_cents=7000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 2, 5, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 2, 5, 9, 0, tzinfo=timezone.utc),
            ),
            Payment(
                org_id=org_b.org_id,
                provider="manual",
                method="cash",
                amount_cents=9000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.add_all(
        [
            FinanceExpense(
                expense_id=uuid.uuid4(),
                org_id=org_a.org_id,
                occurred_on=date(2026, 1, 12),
                category_id=supplies.category_id,
                vendor="Store",
                description="Supplies",
                amount_cents=3000,
                tax_cents=300,
            ),
            FinanceExpense(
                expense_id=uuid.uuid4(),
                org_id=org_a.org_id,
                occurred_on=date(2026, 1, 20),
                category_id=travel.category_id,
                vendor="Taxi",
                description="Travel",
                amount_cents=2000,
                tax_cents=0,
            ),
            FinanceExpense(
                expense_id=uuid.uuid4(),
                org_id=org_a.org_id,
                occurred_on=date(2026, 2, 2),
                category_id=travel.category_id,
                vendor="Taxi",
                description="Out of range",
                amount_cents=1500,
                tax_cents=0,
            ),
            FinanceExpense(
                expense_id=uuid.uuid4(),
                org_id=org_b.org_id,
                occurred_on=date(2026, 1, 15),
                category_id=other_category.category_id,
                vendor="Other Org",
                description="Other Org",
                amount_cents=999,
                tax_cents=0,
            ),
        ]
    )
    await db_session.commit()

    headers = {
        **_auth_header("admin", "admin123"),
        "X-Test-Org": str(org_a.org_id),
    }
    response = client.get(
        "/v1/admin/finance/pnl?from=2026-01-01&to=2026-01-31",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["revenue_cents"] == 15000
    assert payload["expense_cents"] == 5300
    assert payload["net_cents"] == 9700
    assert payload["data_sources"]["expenses"] == "finance_expenses"

    revenue_breakdown = {item["label"]: item["total_cents"] for item in payload["revenue_breakdown"]}
    assert revenue_breakdown["cash"] == 10000
    assert revenue_breakdown["card"] == 5000

    expense_breakdown = {
        item["category_name"]: (item["total_cents"], item["tax_cents"])
        for item in payload["expense_breakdown_by_category"]
    }
    assert expense_breakdown["Supplies"] == (3300, 300)
    assert expense_breakdown["Travel"] == (2000, 0)


@pytest.mark.anyio
async def test_finance_pnl_requires_finance_view(org_a: Organization) -> None:
    headers = {
        **_auth_header("viewer", "viewer123"),
        "X-Test-Org": str(org_a.org_id),
    }
    response = client.get(
        "/v1/admin/finance/pnl?from=2026-01-01&to=2026-01-31",
        headers=headers,
    )
    assert response.status_code == 403
