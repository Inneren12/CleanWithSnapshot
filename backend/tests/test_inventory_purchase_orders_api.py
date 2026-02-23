"""Tests for inventory purchase order API endpoints."""
import uuid
from decimal import Decimal

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory import service as inventory_service
from app.domain.inventory.db_models import (
    InventoryItem,
    InventorySupplier,
    PurchaseOrder,
    PurchaseOrderItem,
)
from app.domain.saas.db_models import Organization
from app.main import app
from app.settings import settings

client = TestClient(app)


@pytest.fixture
async def org_a(db_session: AsyncSession) -> Organization:
    org_id = settings.default_org_id
    org = await db_session.get(Organization, org_id)
    if org is None:
        org = Organization(org_id=org_id, name="Organization A")
        db_session.add(org)
    else:
        org.name = "Organization A"
    await db_session.commit()
    return org


@pytest.fixture
async def org_b(db_session: AsyncSession) -> Organization:
    org = Organization(org_id=uuid.uuid4(), name="Organization B")
    db_session.add(org)
    await db_session.commit()
    return org


@pytest.fixture
async def supplier_a(db_session: AsyncSession, org_a: Organization) -> InventorySupplier:
    supplier = InventorySupplier(
        supplier_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Supply Co",
    )
    db_session.add(supplier)
    await db_session.commit()
    return supplier


@pytest.fixture
async def item_a(db_session: AsyncSession, org_a: Organization) -> InventoryItem:
    item = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_a.org_id,
        category_id=None,
        sku="SKU-PO-1",
        name="Mop Heads",
        unit="each",
        current_qty=Decimal("10"),
        min_qty=Decimal("2"),
        location_label="Shelf A",
        active=True,
    )
    db_session.add(item)
    await db_session.commit()
    return item


@pytest.mark.anyio
async def test_receiving_increases_stock(
    db_session: AsyncSession,
    org_a: Organization,
    supplier_a: InventorySupplier,
    item_a: InventoryItem,
):
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "supplier_id": str(supplier_a.supplier_id),
        "notes": "Restock essentials",
        "tax_cents": 50,
        "shipping_cents": 100,
        "items": [
            {
                "item_id": str(item_a.item_id),
                "qty": "5",
                "unit_cost_cents": 250,
            }
        ],
    }

    response = client.post(
        "/v1/admin/inventory/purchase-orders",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    po_id = response.json()["po_id"]

    response = client.post(
        f"/v1/admin/inventory/purchase-orders/{po_id}/mark_ordered",
        headers=headers,
    )
    assert response.status_code == 200

    response = client.post(
        f"/v1/admin/inventory/purchase-orders/{po_id}/mark_received",
        headers=headers,
    )
    assert response.status_code == 200

    await db_session.refresh(item_a)
    assert item_a.current_qty == Decimal("15")


@pytest.mark.anyio
async def test_purchase_order_notes_can_be_cleared(
    db_session: AsyncSession,
    org_a: Organization,
    supplier_a: InventorySupplier,
    item_a: InventoryItem,
):
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "supplier_id": str(supplier_a.supplier_id),
        "notes": "Initial notes",
        "items": [
            {
                "item_id": str(item_a.item_id),
                "qty": "2",
                "unit_cost_cents": 150,
            }
        ],
    }

    response = client.post(
        "/v1/admin/inventory/purchase-orders",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    po_id = response.json()["po_id"]
    assert response.json()["notes"] == "Initial notes"

    response = client.patch(
        f"/v1/admin/inventory/purchase-orders/{po_id}",
        json={"notes": ""},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["notes"] is None

    result = await db_session.execute(
        select(PurchaseOrder).where(PurchaseOrder.po_id == uuid.UUID(po_id))
    )
    purchase_order = result.scalar_one()
    assert purchase_order.notes is None


@pytest.mark.anyio
async def test_cannot_receive_twice(
    org_a: Organization,
    supplier_a: InventorySupplier,
    item_a: InventoryItem,
):
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "supplier_id": str(supplier_a.supplier_id),
        "items": [
            {
                "item_id": str(item_a.item_id),
                "qty": "1",
                "unit_cost_cents": 100,
            }
        ],
    }

    response = client.post(
        "/v1/admin/inventory/purchase-orders",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    po_id = response.json()["po_id"]

    client.post(
        f"/v1/admin/inventory/purchase-orders/{po_id}/mark_ordered",
        headers=headers,
    )
    response = client.post(
        f"/v1/admin/inventory/purchase-orders/{po_id}/mark_received",
        headers=headers,
    )
    assert response.status_code == 200

    response = client.post(
        f"/v1/admin/inventory/purchase-orders/{po_id}/mark_received",
        headers=headers,
    )
    assert response.status_code == 400
    assert "already" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_purchase_order_org_scoping(
    org_a: Organization,
    org_b: Organization,
    supplier_a: InventorySupplier,
    item_a: InventoryItem,
):
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "supplier_id": str(supplier_a.supplier_id),
        "items": [
            {
                "item_id": str(item_a.item_id),
                "qty": "1",
                "unit_cost_cents": 100,
            }
        ],
    }

    response = client.post(
        "/v1/admin/inventory/purchase-orders",
        json=payload,
        headers=headers,
    )
    po_id = response.json()["po_id"]

    response = client.get(
        f"/v1/admin/inventory/purchase-orders/{po_id}",
        headers={**headers, "X-Test-Org": str(org_b.org_id)},
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_viewer_cannot_create_or_receive_purchase_orders(
    org_a: Organization,
    supplier_a: InventorySupplier,
    item_a: InventoryItem,
    db_session: AsyncSession,
):
    viewer_headers = {"Authorization": "Basic dmlld2VyOnZpZXdlcjEyMw=="}
    admin_headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    payload = {
        "supplier_id": str(supplier_a.supplier_id),
        "items": [
            {
                "item_id": str(item_a.item_id),
                "qty": "1",
                "unit_cost_cents": 100,
            }
        ],
    }

    response = client.post(
        "/v1/admin/inventory/purchase-orders",
        json=payload,
        headers=viewer_headers,
    )
    assert response.status_code == 403

    response = client.post(
        "/v1/admin/inventory/purchase-orders",
        json=payload,
        headers=admin_headers,
    )
    po_id = response.json()["po_id"]

    client.post(
        f"/v1/admin/inventory/purchase-orders/{po_id}/mark_ordered",
        headers=admin_headers,
    )

    response = client.post(
        f"/v1/admin/inventory/purchase-orders/{po_id}/mark_received",
        headers=viewer_headers,
    )
    assert response.status_code == 403

    result = await db_session.execute(
        select(PurchaseOrder).where(PurchaseOrder.po_id == uuid.UUID(po_id))
    )
    purchase_order = result.scalar_one()
    assert purchase_order.status != "received"


@pytest.mark.anyio
async def test_concurrent_receiving_uses_atomic_inventory_updates(
    async_session_maker,
    org_a: Organization,
    supplier_a: InventorySupplier,
    item_a: InventoryItem,
):
    po_ids: list[uuid.UUID] = []

    async with async_session_maker() as session:
        for qty in (Decimal("2"), Decimal("3")):
            purchase_order = PurchaseOrder(
                po_id=uuid.uuid4(),
                org_id=org_a.org_id,
                supplier_id=supplier_a.supplier_id,
                status="ordered",
                subtotal_cents=100,
                total_cents=100,
            )
            purchase_order.items = [
                PurchaseOrderItem(
                    po_item_id=uuid.uuid4(),
                    item_id=item_a.item_id,
                    qty=qty,
                    unit_cost_cents=100,
                    line_total_cents=100,
                )
            ]
            session.add(purchase_order)
            po_ids.append(purchase_order.po_id)
        await session.commit()

    async def _receive(po_id: uuid.UUID) -> None:
        async with async_session_maker() as session:
            await inventory_service.mark_purchase_order_received(session, org_a.org_id, po_id)
            await session.commit()

    async with anyio.create_task_group() as task_group:
        for po_id in po_ids:
            task_group.start_soon(_receive, po_id)

    async with async_session_maker() as session:
        refreshed_item = await session.get(InventoryItem, item_a.item_id)
        assert refreshed_item is not None
        assert refreshed_item.current_qty == Decimal("15")


@pytest.mark.anyio
async def test_receiving_purchase_order_executes_sql_atomic_increment(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    org_a: Organization,
    supplier_a: InventorySupplier,
    item_a: InventoryItem,
):
    purchase_order = PurchaseOrder(
        po_id=uuid.uuid4(),
        org_id=org_a.org_id,
        supplier_id=supplier_a.supplier_id,
        status="ordered",
        subtotal_cents=100,
        total_cents=100,
    )
    purchase_order.items = [
        PurchaseOrderItem(
            po_item_id=uuid.uuid4(),
            item_id=item_a.item_id,
            qty=Decimal("4"),
            unit_cost_cents=100,
            line_total_cents=100,
        )
    ]
    db_session.add(purchase_order)
    await db_session.commit()

    real_update = inventory_service.update
    update_called = False

    def _spy_update(*args, **kwargs):
        nonlocal update_called
        update_called = True
        return real_update(*args, **kwargs)

    monkeypatch.setattr(inventory_service, "update", _spy_update)

    await inventory_service.mark_purchase_order_received(db_session, org_a.org_id, purchase_order.po_id)
    await db_session.commit()

    await db_session.refresh(item_a)
    assert update_called is True
    assert item_a.current_qty == Decimal("14")
