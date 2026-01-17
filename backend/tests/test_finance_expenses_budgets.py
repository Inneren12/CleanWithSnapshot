"""Finance expense and budget API tests for org scoping, RBAC, and summaries."""

import base64
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.finance.db_models import FinanceBudget, FinanceExpense, FinanceExpenseCategory
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
async def category_a(db_session: AsyncSession, org_a: Organization) -> FinanceExpenseCategory:
    category = FinanceExpenseCategory(
        category_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Travel",
        default=False,
        sort_order=1,
    )
    db_session.add(category)
    await db_session.commit()
    return category


@pytest.fixture
async def category_b(db_session: AsyncSession, org_b: Organization) -> FinanceExpenseCategory:
    category = FinanceExpenseCategory(
        category_id=uuid.uuid4(),
        org_id=org_b.org_id,
        name="Supplies",
        default=False,
        sort_order=1,
    )
    db_session.add(category)
    await db_session.commit()
    return category


@pytest.mark.anyio
async def test_finance_expense_org_scoping(
    db_session: AsyncSession,
    org_a: Organization,
    org_b: Organization,
    category_a: FinanceExpenseCategory,
    category_b: FinanceExpenseCategory,
) -> None:
    expense_a = FinanceExpense(
        expense_id=uuid.uuid4(),
        org_id=org_a.org_id,
        occurred_on=date(2026, 1, 10),
        category_id=category_a.category_id,
        vendor="Taxi",
        description="Airport pickup",
        amount_cents=3500,
        tax_cents=0,
    )
    expense_b = FinanceExpense(
        expense_id=uuid.uuid4(),
        org_id=org_b.org_id,
        occurred_on=date(2026, 1, 11),
        category_id=category_b.category_id,
        vendor="Store",
        description="Supplies",
        amount_cents=1200,
        tax_cents=0,
    )
    db_session.add_all([expense_a, expense_b])
    await db_session.commit()

    headers = {
        **_auth_header("admin", "admin123"),
        "X-Test-Org": str(org_a.org_id),
    }
    response = client.get("/v1/admin/finance/expenses", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["expense_id"] == str(expense_a.expense_id)

    delete_response = client.delete(
        f"/v1/admin/finance/expenses/{expense_b.expense_id}",
        headers=headers,
    )
    assert delete_response.status_code == 404


@pytest.mark.anyio
async def test_finance_viewer_cannot_manage(category_a: FinanceExpenseCategory, org_a: Organization) -> None:
    headers = {
        **_auth_header("viewer", "viewer123"),
        "X-Test-Org": str(org_a.org_id),
    }

    create_response = client.post(
        "/v1/admin/finance/expenses",
        headers=headers,
        json={
            "occurred_on": "2026-01-05",
            "category_id": str(category_a.category_id),
            "description": "Office snacks",
            "amount_cents": 2500,
            "tax_cents": 0,
        },
    )
    assert create_response.status_code == 403

    patch_response = client.patch(
        f"/v1/admin/finance/expense-categories/{category_a.category_id}",
        headers=headers,
        json={"name": "Updated"},
    )
    assert patch_response.status_code == 403

    delete_response = client.delete(
        f"/v1/admin/finance/expense-categories/{category_a.category_id}",
        headers=headers,
    )
    assert delete_response.status_code == 403


@pytest.mark.anyio
async def test_finance_summary_math(db_session: AsyncSession, org_a: Organization) -> None:
    category_travel = FinanceExpenseCategory(
        category_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Travel",
        default=False,
        sort_order=1,
    )
    category_supplies = FinanceExpenseCategory(
        category_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Supplies",
        default=False,
        sort_order=2,
    )
    db_session.add_all([category_travel, category_supplies])
    await db_session.flush()

    expense_travel = FinanceExpense(
        expense_id=uuid.uuid4(),
        org_id=org_a.org_id,
        occurred_on=date(2026, 1, 3),
        category_id=category_travel.category_id,
        vendor="Airline",
        description="Flight",
        amount_cents=10000,
        tax_cents=1000,
    )
    expense_supplies = FinanceExpense(
        expense_id=uuid.uuid4(),
        org_id=org_a.org_id,
        occurred_on=date(2026, 1, 5),
        category_id=category_supplies.category_id,
        vendor="Store",
        description="Supplies",
        amount_cents=5000,
        tax_cents=500,
    )
    budget_travel = FinanceBudget(
        budget_id=uuid.uuid4(),
        org_id=org_a.org_id,
        month_yyyymm="2026-01",
        category_id=category_travel.category_id,
        amount_cents=20000,
    )
    budget_supplies = FinanceBudget(
        budget_id=uuid.uuid4(),
        org_id=org_a.org_id,
        month_yyyymm="2026-01",
        category_id=category_supplies.category_id,
        amount_cents=10000,
    )
    db_session.add_all([expense_travel, expense_supplies, budget_travel, budget_supplies])
    await db_session.commit()

    headers = {
        **_auth_header("admin", "admin123"),
        "X-Test-Org": str(org_a.org_id),
    }
    response = client.get(
        "/v1/admin/finance/expenses/summary?from=2026-01-01&to=2026-01-31",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_cents"] == 15000
    assert data["total_tax_cents"] == 1500
    assert data["total_budget_cents"] == 30000
    assert data["percent_of_budget"] == 0.5

    by_category = {entry["category_name"]: entry for entry in data["categories"]}
    assert by_category["Supplies"]["total_cents"] == 5000
    assert by_category["Supplies"]["budget_cents"] == 10000
    assert by_category["Supplies"]["percent_of_budget"] == 0.5
    assert by_category["Travel"]["total_cents"] == 10000
    assert by_category["Travel"]["budget_cents"] == 20000
    assert by_category["Travel"]["percent_of_budget"] == 0.5
