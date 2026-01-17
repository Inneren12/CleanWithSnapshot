"""Inventory domain service layer."""

from __future__ import annotations

from decimal import Decimal
import uuid
from datetime import datetime

from sqlalchemy import case, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory import db_models, schemas
from app.domain.notifications_center import service as notifications_service


# ===== Category Service Functions =====

def _is_low_stock(current_qty: Decimal, min_qty: Decimal) -> bool:
    return current_qty < min_qty



async def list_categories(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[db_models.InventoryCategory], int]:
    """
    List inventory categories with optional search and pagination.

    Args:
        session: Database session
        org_id: Organization ID for scoping
        query: Optional search query for category name
        page: Page number (1-indexed)
        page_size: Number of items per page

    Returns:
        Tuple of (list of categories, total count)
    """
    # Build base query with org scoping
    stmt = select(db_models.InventoryCategory).where(
        db_models.InventoryCategory.org_id == org_id
    )

    # Apply search filter
    if query:
        search_term = f"%{query}%"
        stmt = stmt.where(
            db_models.InventoryCategory.name.ilike(search_term)
        )

    # Count total before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Apply sorting and pagination
    stmt = stmt.order_by(
        db_models.InventoryCategory.sort_order.asc(),
        db_models.InventoryCategory.name.asc(),
    )
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)

    # Execute query
    result = await session.execute(stmt)
    categories = list(result.scalars().all())

    return categories, total


async def get_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    category_id: uuid.UUID,
) -> db_models.InventoryCategory | None:
    """Get a single inventory category by ID."""
    stmt = select(db_models.InventoryCategory).where(
        db_models.InventoryCategory.org_id == org_id,
        db_models.InventoryCategory.category_id == category_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: schemas.InventoryCategoryCreate,
) -> db_models.InventoryCategory:
    """Create a new inventory category."""
    category = db_models.InventoryCategory(
        category_id=uuid.uuid4(),
        org_id=org_id,
        name=data.name,
        sort_order=data.sort_order,
        created_at=datetime.utcnow(),
    )
    session.add(category)
    await session.flush()
    return category


async def update_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    category_id: uuid.UUID,
    data: schemas.InventoryCategoryUpdate,
) -> db_models.InventoryCategory | None:
    """Update an existing inventory category."""
    category = await get_category(session, org_id, category_id)
    if not category:
        return None

    # Apply updates
    if data.name is not None:
        category.name = data.name
    if data.sort_order is not None:
        category.sort_order = data.sort_order

    await session.flush()
    return category


async def delete_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    category_id: uuid.UUID,
) -> bool:
    """
    Delete an inventory category.

    Note: Items in this category will have their category_id set to NULL
    due to the FK constraint with ondelete='SET NULL'.

    Returns:
        True if deleted, False if not found
    """
    category = await get_category(session, org_id, category_id)
    if not category:
        return False

    await session.delete(category)
    await session.flush()
    return True


# ===== Item Service Functions =====


async def list_items(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    query: str | None = None,
    category_id: uuid.UUID | None = None,
    active: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[db_models.InventoryItem], int]:
    """
    List inventory items with optional filters and pagination.

    Args:
        session: Database session
        org_id: Organization ID for scoping
        query: Optional search query for item name or SKU
        category_id: Optional category filter
        active: Optional active status filter
        page: Page number (1-indexed)
        page_size: Number of items per page

    Returns:
        Tuple of (list of items, total count)
    """
    # Build base query with org scoping
    stmt = select(db_models.InventoryItem).where(
        db_models.InventoryItem.org_id == org_id
    )

    # Apply search filter
    if query:
        search_term = f"%{query}%"
        stmt = stmt.where(
            or_(
                db_models.InventoryItem.name.ilike(search_term),
                db_models.InventoryItem.sku.ilike(search_term),
            )
        )

    # Apply category filter
    if category_id is not None:
        stmt = stmt.where(db_models.InventoryItem.category_id == category_id)

    # Apply active filter
    if active is not None:
        stmt = stmt.where(db_models.InventoryItem.active == active)

    # Count total before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Apply sorting and pagination
    stmt = stmt.order_by(
        db_models.InventoryItem.name.asc(),
    )
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)

    # Execute query
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    return items, total


async def list_low_stock_items(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    only_below_min: bool = True,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[tuple[db_models.InventoryItem, Decimal]], int]:
    """
    List inventory items with computed need quantities for low stock monitoring.

    Args:
        session: Database session
        org_id: Organization ID for scoping
        only_below_min: When true, only items with current_qty < min_qty are returned
        page: Page number (1-indexed)
        page_size: Number of items per page

    Returns:
        Tuple of (list of (item, need_qty), total count)
    """
    need_qty_expr = case(
        (
            db_models.InventoryItem.current_qty < db_models.InventoryItem.min_qty,
            db_models.InventoryItem.min_qty - db_models.InventoryItem.current_qty,
        ),
        else_=Decimal("0"),
    ).label("need_qty")

    stmt = select(db_models.InventoryItem, need_qty_expr).where(
        db_models.InventoryItem.org_id == org_id
    )

    if only_below_min:
        stmt = stmt.where(
            db_models.InventoryItem.current_qty < db_models.InventoryItem.min_qty
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(
        need_qty_expr.desc(),
        db_models.InventoryItem.name.asc(),
    )
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)

    result = await session.execute(stmt)
    items = [(row[0], row[1]) for row in result.all()]

    return items, total


async def get_item(
    session: AsyncSession,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
) -> db_models.InventoryItem | None:
    """Get a single inventory item by ID."""
    stmt = select(db_models.InventoryItem).where(
        db_models.InventoryItem.org_id == org_id,
        db_models.InventoryItem.item_id == item_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_item(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: schemas.InventoryItemCreate,
) -> db_models.InventoryItem:
    """Create a new inventory item."""
    # Validate category exists if provided
    if data.category_id is not None:
        category = await get_category(session, org_id, data.category_id)
        if not category:
            raise ValueError(f"Category {data.category_id} not found")

    item = db_models.InventoryItem(
        item_id=uuid.uuid4(),
        org_id=org_id,
        category_id=data.category_id,
        sku=data.sku,
        name=data.name,
        unit=data.unit,
        current_qty=data.current_qty,
        min_qty=data.min_qty,
        location_label=data.location_label,
        active=data.active,
        created_at=datetime.utcnow(),
    )
    session.add(item)
    await session.flush()
    return item


async def update_item(
    session: AsyncSession,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
    data: schemas.InventoryItemUpdate,
) -> db_models.InventoryItem | None:
    """Update an existing inventory item."""
    item = await get_item(session, org_id, item_id)
    if not item:
        return None

    was_low = _is_low_stock(item.current_qty, item.min_qty)

    # Validate category exists if being updated
    if data.category_id is not None:
        category = await get_category(session, org_id, data.category_id)
        if not category:
            raise ValueError(f"Category {data.category_id} not found")

    # Apply updates
    if data.category_id is not None:
        item.category_id = data.category_id
    if data.sku is not None:
        item.sku = data.sku
    if data.name is not None:
        item.name = data.name
    if data.unit is not None:
        item.unit = data.unit
    if data.current_qty is not None:
        item.current_qty = data.current_qty
    if data.min_qty is not None:
        item.min_qty = data.min_qty
    if data.location_label is not None:
        item.location_label = data.location_label
    if data.active is not None:
        item.active = data.active

    is_low = _is_low_stock(item.current_qty, item.min_qty)
    if not was_low and is_low:
        await notifications_service.emit_preset_event(
            session,
            org_id=org_id,
            preset_key="low_stock",
            priority="HIGH",
            title="Low inventory",
            body=(
                f"{item.name} is below minimum stock "
                f"({item.current_qty} {item.unit} remaining, min {item.min_qty})."
            ),
            entity_type="inventory_item",
            entity_id=str(item.item_id),
            action_href=f"/admin/inventory?item_id={item.item_id}",
            action_kind="open_inventory",
        )

    await session.flush()
    return item


async def delete_item(
    session: AsyncSession,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
) -> bool:
    """
    Delete an inventory item.

    Returns:
        True if deleted, False if not found
    """
    item = await get_item(session, org_id, item_id)
    if not item:
        return False

    await session.delete(item)
    await session.flush()
    return True


# ===== Supplier Service Functions =====


async def list_suppliers(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[db_models.InventorySupplier], int]:
    """
    List inventory suppliers with optional search and pagination.

    Args:
        session: Database session
        org_id: Organization ID for scoping
        query: Optional search query for supplier name, email, or phone
        page: Page number (1-indexed)
        page_size: Number of items per page

    Returns:
        Tuple of (list of suppliers, total count)
    """
    stmt = select(db_models.InventorySupplier).where(
        db_models.InventorySupplier.org_id == org_id
    )

    if query:
        search_term = f"%{query}%"
        stmt = stmt.where(
            or_(
                db_models.InventorySupplier.name.ilike(search_term),
                db_models.InventorySupplier.email.ilike(search_term),
                db_models.InventorySupplier.phone.ilike(search_term),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(db_models.InventorySupplier.name.asc())
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)

    result = await session.execute(stmt)
    suppliers = list(result.scalars().all())

    return suppliers, total


async def get_supplier(
    session: AsyncSession,
    org_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> db_models.InventorySupplier | None:
    """Get a single inventory supplier by ID."""
    stmt = select(db_models.InventorySupplier).where(
        db_models.InventorySupplier.org_id == org_id,
        db_models.InventorySupplier.supplier_id == supplier_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_supplier(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: schemas.InventorySupplierCreate,
) -> db_models.InventorySupplier:
    """Create a new inventory supplier."""
    supplier = db_models.InventorySupplier(
        supplier_id=uuid.uuid4(),
        org_id=org_id,
        name=data.name,
        email=data.email,
        phone=data.phone,
        address=data.address,
        terms=data.terms,
        delivery_days=data.delivery_days,
        min_order_cents=data.min_order_cents,
        notes=data.notes,
        created_at=datetime.utcnow(),
    )
    session.add(supplier)
    await session.flush()
    return supplier


async def update_supplier(
    session: AsyncSession,
    org_id: uuid.UUID,
    supplier_id: uuid.UUID,
    data: schemas.InventorySupplierUpdate,
) -> db_models.InventorySupplier | None:
    """Update an existing inventory supplier."""
    supplier = await get_supplier(session, org_id, supplier_id)
    if not supplier:
        return None

    if data.name is not None:
        supplier.name = data.name
    if data.email is not None:
        supplier.email = data.email
    if data.phone is not None:
        supplier.phone = data.phone
    if data.address is not None:
        supplier.address = data.address
    if data.terms is not None:
        supplier.terms = data.terms
    if data.delivery_days is not None:
        supplier.delivery_days = data.delivery_days
    if data.min_order_cents is not None:
        supplier.min_order_cents = data.min_order_cents
    if data.notes is not None:
        supplier.notes = data.notes

    await session.flush()
    return supplier


async def delete_supplier(
    session: AsyncSession,
    org_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> bool:
    """
    Delete an inventory supplier.

    Returns:
        True if deleted, False if not found
    """
    supplier = await get_supplier(session, org_id, supplier_id)
    if not supplier:
        return False

    await session.delete(supplier)
    await session.flush()
    return True
