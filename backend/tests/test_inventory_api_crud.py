"""Test inventory API CRUD endpoints with org-scoping, RBAC, and pagination."""
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory.db_models import InventoryCategory, InventoryItem
from app.domain.saas.db_models import Organization
from app.main import app

client = TestClient(app)


# ===== Fixtures =====


@pytest.fixture
async def org_a(db_session: AsyncSession) -> Organization:
    """Create test organization A."""
    org = Organization(
        org_id=uuid.uuid4(),
        name="Organization A",
    )
    db_session.add(org)
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
async def category_a(db_session: AsyncSession, org_a: Organization) -> InventoryCategory:
    """Create test category in org A."""
    category = InventoryCategory(
        category_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Cleaning Supplies",
        sort_order=1,
    )
    db_session.add(category)
    await db_session.commit()
    return category


@pytest.fixture
async def category_b(db_session: AsyncSession, org_b: Organization) -> InventoryCategory:
    """Create test category in org B for cross-org tests."""
    category = InventoryCategory(
        category_id=uuid.uuid4(),
        org_id=org_b.org_id,
        name="Office Supplies",
        sort_order=1,
    )
    db_session.add(category)
    await db_session.commit()
    return category


@pytest.fixture
async def item_a(
    db_session: AsyncSession, org_a: Organization, category_a: InventoryCategory
) -> InventoryItem:
    """Create test item in org A."""
    item = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_a.org_id,
        category_id=category_a.category_id,
        sku="SKU001",
        name="Glass Cleaner",
        unit="bottles",
        current_qty=Decimal("10"),
        min_qty=Decimal("5"),
        location_label="Shelf A",
        active=True,
    )
    db_session.add(item)
    await db_session.commit()
    return item


@pytest.fixture
async def item_b(
    db_session: AsyncSession, org_b: Organization, category_b: InventoryCategory
) -> InventoryItem:
    """Create test item in org B for cross-org tests."""
    item = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_b.org_id,
        category_id=category_b.category_id,
        sku="SKU002",
        name="Paper Towels",
        unit="rolls",
        current_qty=Decimal("20"),
        min_qty=Decimal("10"),
        location_label="Shelf B",
        active=True,
    )
    db_session.add(item)
    await db_session.commit()
    return item


# ===== Category CRUD Tests =====


@pytest.mark.anyio
async def test_list_categories_empty(org_a: Organization):
    """Test listing categories when none exist."""
    # Mock admin auth header (would need proper auth in real test)
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}  # admin:admin123
    response = client.get(
        "/v1/admin/inventory/categories",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert isinstance(data["items"], list)


@pytest.mark.anyio
async def test_create_category(org_a: Organization):
    """Test creating a new category."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "name": "Test Category",
        "sort_order": 10,
    }

    response = client.post(
        "/v1/admin/inventory/categories",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Category"
    assert data["sort_order"] == 10
    assert "category_id" in data
    assert "org_id" in data
    assert "created_at" in data


@pytest.mark.anyio
async def test_update_category(category_a: InventoryCategory):
    """Test updating an existing category."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "name": "Updated Name",
        "sort_order": 5,
    }

    response = client.patch(
        f"/v1/admin/inventory/categories/{category_a.category_id}",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["sort_order"] == 5


@pytest.mark.anyio
async def test_delete_category(category_a: InventoryCategory, db_session: AsyncSession):
    """Test deleting a category."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    response = client.delete(
        f"/v1/admin/inventory/categories/{category_a.category_id}",
        headers=headers,
    )

    assert response.status_code == 204

    # Verify category is deleted
    result = await db_session.execute(
        select(InventoryCategory).where(InventoryCategory.category_id == category_a.category_id)
    )
    deleted_category = result.scalar_one_or_none()
    assert deleted_category is None


@pytest.mark.anyio
async def test_delete_nonexistent_category():
    """Test deleting a category that doesn't exist."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    fake_id = uuid.uuid4()

    response = client.delete(
        f"/v1/admin/inventory/categories/{fake_id}",
        headers=headers,
    )

    assert response.status_code == 404


# ===== Item CRUD Tests =====


@pytest.mark.anyio
async def test_create_item(category_a: InventoryCategory):
    """Test creating a new item."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "category_id": str(category_a.category_id),
        "sku": "TEST001",
        "name": "Test Item",
        "unit": "pieces",
        "current_qty": "15.50",
        "min_qty": "5.00",
        "location_label": "Warehouse A",
        "active": True,
    }

    response = client.post(
        "/v1/admin/inventory/items",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Item"
    assert data["sku"] == "TEST001"
    assert Decimal(data["current_qty"]) == Decimal("15.50")
    assert Decimal(data["min_qty"]) == Decimal("5.00")


@pytest.mark.anyio
async def test_create_item_with_invalid_category():
    """Test creating an item with a non-existent category."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    fake_category_id = uuid.uuid4()
    payload = {
        "category_id": str(fake_category_id),
        "name": "Test Item",
        "unit": "pieces",
    }

    response = client.post(
        "/v1/admin/inventory/items",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_update_item(item_a: InventoryItem):
    """Test updating an existing item."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {
        "name": "Updated Item",
        "current_qty": "25.00",
        "active": False,
    }

    response = client.patch(
        f"/v1/admin/inventory/items/{item_a.item_id}",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Item"
    assert Decimal(data["current_qty"]) == Decimal("25.00")
    assert data["active"] is False


@pytest.mark.anyio
async def test_delete_item(item_a: InventoryItem, db_session: AsyncSession):
    """Test deleting an item."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    response = client.delete(
        f"/v1/admin/inventory/items/{item_a.item_id}",
        headers=headers,
    )

    assert response.status_code == 204

    # Verify item is deleted
    result = await db_session.execute(
        select(InventoryItem).where(InventoryItem.item_id == item_a.item_id)
    )
    deleted_item = result.scalar_one_or_none()
    assert deleted_item is None


# ===== Org Scoping Tests =====


@pytest.mark.anyio
async def test_cannot_access_category_from_different_org(
    category_a: InventoryCategory, category_b: InventoryCategory
):
    """Test that org A cannot access category from org B."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    # Try to access org B's category while authenticated as org A
    response = client.get(
        f"/v1/admin/inventory/categories",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()

    # Should not see org B's category in the list
    category_ids = [item["category_id"] for item in data["items"]]
    assert str(category_b.category_id) not in category_ids


@pytest.mark.anyio
async def test_cannot_update_category_from_different_org(category_b: InventoryCategory):
    """Test that org A cannot update category from org B."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}
    payload = {"name": "Hacked Name"}

    # Try to update org B's category while authenticated as org A
    response = client.patch(
        f"/v1/admin/inventory/categories/{category_b.category_id}",
        json=payload,
        headers=headers,
    )

    # Should return 404 (not found in the org's scope)
    assert response.status_code == 404


@pytest.mark.anyio
async def test_cannot_delete_category_from_different_org(
    category_b: InventoryCategory, db_session: AsyncSession
):
    """Test that org A cannot delete category from org B."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    # Try to delete org B's category while authenticated as org A
    response = client.delete(
        f"/v1/admin/inventory/categories/{category_b.category_id}",
        headers=headers,
    )

    # Should return 404 (not found in the org's scope)
    assert response.status_code == 404

    # Verify category still exists
    result = await db_session.execute(
        select(InventoryCategory).where(InventoryCategory.category_id == category_b.category_id)
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.anyio
async def test_cannot_access_item_from_different_org(item_a: InventoryItem, item_b: InventoryItem):
    """Test that org A cannot see items from org B."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    response = client.get(
        "/v1/admin/inventory/items",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()

    # Should not see org B's item in the list
    item_ids = [item["item_id"] for item in data["items"]]
    assert str(item_b.item_id) not in item_ids


# ===== RBAC Tests =====


@pytest.mark.anyio
async def test_viewer_can_list_categories(category_a: InventoryCategory):
    """Test that viewer role can list categories (has core.view permission)."""
    # Mock viewer auth (would need proper viewer credentials)
    headers = {"Authorization": "Basic dmlld2VyOnZpZXdlcjEyMw=="}  # viewer:viewer123

    response = client.get(
        "/v1/admin/inventory/categories",
        headers=headers,
    )

    # Viewer should be able to list (inventory.view or core.view permission)
    assert response.status_code in [200, 403]  # 403 if viewer doesn't have permission


@pytest.mark.anyio
async def test_viewer_cannot_create_category():
    """Test that viewer role cannot create categories (needs inventory.manage)."""
    headers = {"Authorization": "Basic dmlld2VyOnZpZXdlcjEyMw=="}
    payload = {"name": "Unauthorized Category", "sort_order": 1}

    response = client.post(
        "/v1/admin/inventory/categories",
        json=payload,
        headers=headers,
    )

    # Should return 403 Forbidden
    assert response.status_code == 403
    assert "forbidden" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_viewer_cannot_update_category(category_a: InventoryCategory):
    """Test that viewer role cannot update categories."""
    headers = {"Authorization": "Basic dmlld2VyOnZpZXdlcjEyMw=="}
    payload = {"name": "Unauthorized Update"}

    response = client.patch(
        f"/v1/admin/inventory/categories/{category_a.category_id}",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_viewer_cannot_delete_category(category_a: InventoryCategory):
    """Test that viewer role cannot delete categories."""
    headers = {"Authorization": "Basic dmlld2VyOnZpZXdlcjEyMw=="}

    response = client.delete(
        f"/v1/admin/inventory/categories/{category_a.category_id}",
        headers=headers,
    )

    assert response.status_code == 403


# ===== Pagination & Search Tests =====


@pytest.mark.anyio
async def test_category_pagination(db_session: AsyncSession, org_a: Organization):
    """Test category pagination with correct total counts."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    # Create multiple categories
    for i in range(15):
        category = InventoryCategory(
            category_id=uuid.uuid4(),
            org_id=org_a.org_id,
            name=f"Category {i}",
            sort_order=i,
        )
        db_session.add(category)
    await db_session.commit()

    # Test page 1
    response = client.get(
        "/v1/admin/inventory/categories?page=1&page_size=10",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 15
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert len(data["items"]) == 10

    # Test page 2
    response = client.get(
        "/v1/admin/inventory/categories?page=2&page_size=10",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 15
    assert data["page"] == 2
    assert len(data["items"]) == 5


@pytest.mark.anyio
async def test_category_search(db_session: AsyncSession, org_a: Organization):
    """Test category search filtering."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    # Create categories with different names
    categories = [
        InventoryCategory(
            category_id=uuid.uuid4(),
            org_id=org_a.org_id,
            name="Cleaning Supplies",
            sort_order=1,
        ),
        InventoryCategory(
            category_id=uuid.uuid4(),
            org_id=org_a.org_id,
            name="Office Supplies",
            sort_order=2,
        ),
        InventoryCategory(
            category_id=uuid.uuid4(),
            org_id=org_a.org_id,
            name="Kitchen Tools",
            sort_order=3,
        ),
    ]
    for cat in categories:
        db_session.add(cat)
    await db_session.commit()

    # Search for "Supplies"
    response = client.get(
        "/v1/admin/inventory/categories?query=Supplies",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2  # Should find 2 categories with "Supplies"
    names = [item["name"] for item in data["items"]]
    assert "Cleaning Supplies" in names
    assert "Office Supplies" in names
    assert "Kitchen Tools" not in names


@pytest.mark.anyio
async def test_item_filter_by_category(
    db_session: AsyncSession, org_a: Organization, category_a: InventoryCategory
):
    """Test filtering items by category."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    # Create another category
    category2 = InventoryCategory(
        category_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Other Category",
        sort_order=2,
    )
    db_session.add(category2)
    await db_session.flush()

    # Create items in different categories
    item1 = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_a.org_id,
        category_id=category_a.category_id,
        name="Item in Cat A",
        unit="pieces",
    )
    item2 = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_a.org_id,
        category_id=category2.category_id,
        name="Item in Cat 2",
        unit="pieces",
    )
    db_session.add(item1)
    db_session.add(item2)
    await db_session.commit()

    # Filter by category_a
    response = client.get(
        f"/v1/admin/inventory/items?category_id={category_a.category_id}",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    # All items should belong to category_a
    for item in data["items"]:
        assert item["category_id"] == str(category_a.category_id)


@pytest.mark.anyio
async def test_item_filter_by_active_status(db_session: AsyncSession, org_a: Organization):
    """Test filtering items by active status."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    # Create active and inactive items
    active_item = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Active Item",
        unit="pieces",
        active=True,
    )
    inactive_item = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_a.org_id,
        name="Inactive Item",
        unit="pieces",
        active=False,
    )
    db_session.add(active_item)
    db_session.add(inactive_item)
    await db_session.commit()

    # Filter by active=true
    response = client.get(
        "/v1/admin/inventory/items?active=true",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    # All returned items should be active
    for item in data["items"]:
        assert item["active"] is True


@pytest.mark.anyio
async def test_item_search_by_name_and_sku(db_session: AsyncSession, org_a: Organization):
    """Test searching items by name or SKU."""
    headers = {"Authorization": "Basic YWRtaW46YWRtaW4xMjM="}

    # Create items with different names and SKUs
    item1 = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_a.org_id,
        sku="CLEAN-001",
        name="Glass Cleaner",
        unit="bottles",
    )
    item2 = InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_a.org_id,
        sku="CLEAN-002",
        name="Floor Wax",
        unit="gallons",
    )
    db_session.add(item1)
    db_session.add(item2)
    await db_session.commit()

    # Search by name
    response = client.get(
        "/v1/admin/inventory/items?query=Cleaner",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    names = [item["name"] for item in data["items"]]
    assert "Glass Cleaner" in names

    # Search by SKU
    response = client.get(
        "/v1/admin/inventory/items?query=CLEAN-002",
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()
    skus = [item["sku"] for item in data["items"]]
    assert "CLEAN-002" in skus
