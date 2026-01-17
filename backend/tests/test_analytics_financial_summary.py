"""Analytics financial summary API tests for readiness and P&L alignment."""

import base64
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feature_modules.db_models import OrgFeatureConfig
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


@pytest.mark.anyio
async def test_financial_summary_not_ready_without_expenses(
    db_session: AsyncSession,
    org_a: Organization,
) -> None:
    db_session.add(
        OrgFeatureConfig(org_id=org_a.org_id, feature_overrides={"module.finance": False})
    )
    await db_session.commit()

    headers = {
        **_auth_header("admin", "admin123"),
        "X-Test-Org": str(org_a.org_id),
    }
    response = client.get(
        "/v1/admin/analytics/financial_summary?from=2026-01-01&to=2026-01-31",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "ready": False,
        "reason": "Finance data not ready — enable expense tracking.",
    }


@pytest.mark.anyio
async def test_financial_summary_matches_pnl(
    db_session: AsyncSession,
    org_a: Organization,
) -> None:
    db_session.add(
        OrgFeatureConfig(org_id=org_a.org_id, feature_overrides={"module.finance": False})
    )
    category = FinanceExpenseCategory(
        category_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Supplies",
        default=False,
        sort_order=1,
    )
    db_session.add(category)
    await db_session.flush()

    db_session.add_all(
        [
            Payment(
                org_id=org_a.org_id,
                provider="manual",
                method="cash",
                amount_cents=12000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
            ),
            Payment(
                org_id=org_a.org_id,
                provider="manual",
                method="card",
                amount_cents=8000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                received_at=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc),
            ),
            FinanceExpense(
                expense_id=uuid.uuid4(),
                org_id=org_a.org_id,
                occurred_on=date(2026, 1, 12),
                category_id=category.category_id,
                vendor="Store",
                description="Supplies",
                amount_cents=4000,
                tax_cents=200,
            ),
        ]
    )
    await db_session.commit()

    headers = {
        **_auth_header("admin", "admin123"),
        "X-Test-Org": str(org_a.org_id),
    }
    pnl_response = client.get(
        "/v1/admin/finance/pnl?from=2026-01-01&to=2026-01-31",
        headers=headers,
    )
    assert pnl_response.status_code == 200
    pnl_payload = pnl_response.json()

    summary_response = client.get(
        "/v1/admin/analytics/financial_summary?from=2026-01-01&to=2026-01-31",
        headers=headers,
    )
    assert summary_response.status_code == 200
    summary = summary_response.json()

    assert summary["ready"] is True
    assert summary["revenue_cents"] == pnl_payload["revenue_cents"]
    assert summary["expenses_cents"] == pnl_payload["expense_cents"]
    assert summary["profit_cents"] == pnl_payload["net_cents"]

    revenue_cents = pnl_payload["revenue_cents"]
    expected_margin = round((summary["profit_cents"] / revenue_cents) * 100, 2) if revenue_cents else 0.0
    assert summary["margin_pp"] == expected_margin
