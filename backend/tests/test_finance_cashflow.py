"""Finance cashflow API tests for net movement, snapshots, and RBAC."""

import base64
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.finance.db_models import FinanceCashSnapshot, FinanceExpense, FinanceExpenseCategory
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
async def categories(
    db_session: AsyncSession,
    org_a: Organization,
) -> tuple[FinanceExpenseCategory, FinanceExpenseCategory]:
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
async def test_finance_cashflow_totals_and_snapshots(
    db_session: AsyncSession,
    org_a: Organization,
    org_b: Organization,
    categories: tuple[FinanceExpenseCategory, FinanceExpenseCategory],
) -> None:
    supplies, travel = categories

    db_session.add_all(
        [
            Payment(
                org_id=org_a.org_id,
                provider="manual",
                method="cash",
                amount_cents=12000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc),
            ),
            Payment(
                org_id=org_a.org_id,
                provider="manual",
                method="card",
                amount_cents=4000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=None,
                created_at=datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc),
            ),
            Payment(
                org_id=org_b.org_id,
                provider="manual",
                method="cash",
                amount_cents=9999,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.add_all(
        [
            FinanceExpense(
                expense_id=uuid.uuid4(),
                org_id=org_a.org_id,
                occurred_on=date(2026, 3, 3),
                category_id=supplies.category_id,
                vendor="Store",
                description="Supplies",
                amount_cents=3000,
                tax_cents=300,
            ),
            FinanceExpense(
                expense_id=uuid.uuid4(),
                org_id=org_a.org_id,
                occurred_on=date(2026, 3, 12),
                category_id=travel.category_id,
                vendor="Taxi",
                description="Travel",
                amount_cents=1500,
                tax_cents=0,
            ),
            FinanceExpense(
                expense_id=uuid.uuid4(),
                org_id=org_b.org_id,
                occurred_on=date(2026, 3, 4),
                category_id=travel.category_id,
                vendor="Other Org",
                description="Other Org",
                amount_cents=2000,
                tax_cents=0,
            ),
        ]
    )
    db_session.add_all(
        [
            FinanceCashSnapshot(
                snapshot_id=uuid.uuid4(),
                org_id=org_a.org_id,
                as_of_date=date(2026, 2, 28),
                cash_cents=45000,
                note="Month end",
            ),
            FinanceCashSnapshot(
                snapshot_id=uuid.uuid4(),
                org_id=org_a.org_id,
                as_of_date=date(2026, 3, 15),
                cash_cents=52000,
                note="Mid month",
            ),
            FinanceCashSnapshot(
                snapshot_id=uuid.uuid4(),
                org_id=org_b.org_id,
                as_of_date=date(2026, 3, 1),
                cash_cents=99999,
                note="Other org",
            ),
        ]
    )
    await db_session.commit()

    headers = {
        **_auth_header("admin", "admin123"),
        "X-Test-Org": str(org_a.org_id),
    }
    response = client.get(
        "/v1/admin/finance/cashflow?from=2026-03-01&to=2026-03-31",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["inflows_cents"] == 16000
    assert payload["outflows_cents"] == 4800
    assert payload["net_movement_cents"] == 11200

    inflows = {item["method"]: item["total_cents"] for item in payload["inflows_breakdown"]}
    assert inflows["cash"] == 12000
    assert inflows["card"] == 4000

    assert payload["start_cash_snapshot"]["cash_cents"] == 45000
    assert payload["start_cash_snapshot"]["as_of_date"] == "2026-02-28"
    assert payload["end_cash_snapshot"]["cash_cents"] == 52000


@pytest.mark.anyio
async def test_finance_cash_snapshots_validation_and_list(
    db_session: AsyncSession,
    org_a: Organization,
) -> None:
    headers = {
        **_auth_header("admin", "admin123"),
        "X-Test-Org": str(org_a.org_id),
    }

    create_resp = client.post(
        "/v1/admin/finance/cash_snapshots",
        headers=headers,
        json={"as_of_date": "2026-04-01", "cash_cents": 12345, "note": "Quarter start"},
    )
    assert create_resp.status_code == 201

    conflict_resp = client.post(
        "/v1/admin/finance/cash_snapshots",
        headers=headers,
        json={"as_of_date": "2026-04-01", "cash_cents": 999, "note": "Duplicate"},
    )
    assert conflict_resp.status_code == 409

    list_resp = client.get(
        "/v1/admin/finance/cash_snapshots?from=2026-04-01&to=2026-04-30",
        headers=headers,
    )
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload["items"][0]["cash_cents"] == 12345


@pytest.mark.anyio
async def test_finance_cashflow_requires_finance_view(org_a: Organization) -> None:
    headers = {
        **_auth_header("viewer", "viewer123"),
        "X-Test-Org": str(org_a.org_id),
    }
    response = client.get(
        "/v1/admin/finance/cashflow?from=2026-03-01&to=2026-03-31",
        headers=headers,
    )
    assert response.status_code == 403
