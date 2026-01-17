"""Test inventory supplier API CRUD endpoints with org-scoping and RBAC."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory.db_models import InventorySupplier
from app.domain.saas.db_models import Organization
from app.main import app
from app.settings import settings

client = TestClient(app)


@pytest.fixture
async def org_a(db_session: AsyncSession) -> Organization:
    """Create test organization A."""
    org_id = settings.default_org_id
    org = await db_session.get(Organization, org_id)
    if org is None:
        org = Organization(
            org_id=org_id,
            name="Organization A",
        )
        db_session.add(org)
    else:
        org.name = "Organization A"
    await db_session.commit()
    return org


@pytest.fixture
async def org_b(db_session: AsyncSession) -> Organization:
    """Create test organization B for cross-org tests."""
    org = Organization(
        org_id=uuid.uuid4(),
        name="Organization B",
    )
    db_session.add(org)
    await db_session.commit()
    return org


@pytest.fixture
async def supplier_a(
    db_session: AsyncSession, org_a: Organization
) -> InventorySupplier:
    """Create test supplier in org A."""
    supplier = InventorySupplier(
        supplier_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Acme Supplies",
        email="orders@acme.test",
        phone="555-0100",
        delivery_days="Mon,Wed",
        min_order_cents=2500,
        notes="Primary vendor",
    )
    db_session.add(supplier)
    await db_session.commit()
    return supplier


@pytest.fixture
async def supplier_b(
    db_session: AsyncSession, org_b: Organization
) -> InventorySupplier:
    """Create test supplier in org B."""
    supplier = InventorySupplier(
        supplier_id=uuid.uuid4(),
        org_id=org_b.org_id,
        name="Bravo Supplies",
        email="hello@bravo.test",
    )
    db_session.add(supplier)
    await db_session.commit()
    return supplier


@pytest.mark.anyio
async def test_list_suppliers_empty(org_a: Organization):
    """Test listing suppliers when none exist."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    response = client.get(
        "/v1/admin/inventory/suppliers",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.anyio
async def test_create_supplier(org_a: Organization):
    """Test creating a new supplier."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "name": "Clean Co",
        "email": "support@clean.test",
        "phone": "555-0101",
        "address": "123 Main St",
        "terms": "Net 30",
        "delivery_days": "Tue,Fri",
        "min_order_cents": 5000,
        "notes": "Preferred",
    }

    response = client.post(
        "/v1/admin/inventory/suppliers",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Clean Co"
    assert data["email"] == "support@clean.test"
    assert data["min_order_cents"] == 5000
    assert "supplier_id" in data


@pytest.mark.anyio
async def test_update_supplier(supplier_a: InventorySupplier):
    """Test updating an existing supplier."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "phone": "555-9999",
        "terms": "Net 15",
    }

    response = client.patch(
        f"/v1/admin/inventory/suppliers/{supplier_a.supplier_id}",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["phone"] == "555-9999"
    assert data["terms"] == "Net 15"


@pytest.mark.anyio
async def test_delete_supplier(
    supplier_a: InventorySupplier, db_session: AsyncSession
):
    """Test deleting a supplier."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    response = client.delete(
        f"/v1/admin/inventory/suppliers/{supplier_a.supplier_id}",
        headers=headers,
    )

    assert response.status_code == 204

    result = await db_session.execute(
        select(InventorySupplier).where(
            InventorySupplier.supplier_id == supplier_a.supplier_id
        )
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.anyio
async def test_supplier_list_org_scoping(
    db_session: AsyncSession,
    org_a: Organization,
    supplier_a: InventorySupplier,
    supplier_b: InventorySupplier,
):
    """Test that supplier list is scoped to the current org."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    response = client.get(
        "/v1/admin/inventory/suppliers",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["supplier_id"] == str(supplier_a.supplier_id)


@pytest.mark.anyio
async def test_viewer_cannot_create_supplier():
    """Test that viewer role cannot create suppliers."""
    headers = {"Authorization": "Basic dmlld2VyOnZpZXdlcjEyMw=="}
    payload = {"name": "Unauthorized Supplier"}

    response = client.post(
        "/v1/admin/inventory/suppliers",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 403
    assert "forbidden" in response.json()["detail"].lower()
