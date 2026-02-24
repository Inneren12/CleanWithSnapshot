"""Inventory domain service layer."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import uuid
from datetime import datetime, timezone

from sqlalchemy import case, func, select, or_, desc, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.inventory import db_models, schemas
from app.domain.bookings.db_models import Booking
from app.domain.pricing_settings.db_models import ServiceType
from app.domain.notifications_center import service as notifications_service


# ===== Category Service Functions =====

def _is_low_stock(current_qty: Decimal, min_qty: Decimal) -> bool:
    return current_qty < min_qty


def _normalize_notes(notes: str | None) -> str | None:
    if notes is None:
        return None
    trimmed = notes.strip()
    return trimmed or None



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
        created_at=datetime.now(timezone.utc),
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
        created_at=datetime.now(timezone.utc),
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
        created_at=datetime.now(timezone.utc),
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


# ===== Purchase Order Service Functions =====


def _calculate_line_total(qty: Decimal, unit_cost_cents: int) -> int:
    total = (qty * Decimal(unit_cost_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(total)


def _calculate_po_totals(
    items: list[schemas.PurchaseOrderItemCreate],
    tax_cents: int,
    shipping_cents: int,
) -> tuple[int, int]:
    subtotal = sum(_calculate_line_total(item.qty, item.unit_cost_cents) for item in items)
    total = subtotal + tax_cents + shipping_cents
    return subtotal, total


async def _load_inventory_items(
    session: AsyncSession,
    org_id: uuid.UUID,
    item_ids: set[uuid.UUID],
) -> dict[uuid.UUID, db_models.InventoryItem]:
    if not item_ids:
        return {}
    stmt = select(db_models.InventoryItem).where(
        db_models.InventoryItem.org_id == org_id,
        db_models.InventoryItem.item_id.in_(item_ids),
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())
    return {item.item_id: item for item in items}


async def list_purchase_orders(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    status: schemas.PurchaseOrderStatus | None = None,
    supplier_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[db_models.PurchaseOrder], int]:
    """List purchase orders with optional status and supplier filters."""
    stmt = select(db_models.PurchaseOrder).where(db_models.PurchaseOrder.org_id == org_id)

    if status is not None:
        stmt = stmt.where(db_models.PurchaseOrder.status == status.value)
    if supplier_id is not None:
        stmt = stmt.where(db_models.PurchaseOrder.supplier_id == supplier_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(db_models.PurchaseOrder.po_id.desc())
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)

    result = await session.execute(stmt)
    purchase_orders = list(result.scalars().all())

    return purchase_orders, total


async def get_purchase_order(
    session: AsyncSession,
    org_id: uuid.UUID,
    po_id: uuid.UUID,
) -> db_models.PurchaseOrder | None:
    """Get a single purchase order by ID."""
    stmt = (
        select(db_models.PurchaseOrder)
        .where(
            db_models.PurchaseOrder.org_id == org_id,
            db_models.PurchaseOrder.po_id == po_id,
        )
        .options(selectinload(db_models.PurchaseOrder.items))
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_purchase_order(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: schemas.PurchaseOrderCreate,
) -> db_models.PurchaseOrder:
    """Create a new purchase order with line items."""
    supplier = await get_supplier(session, org_id, data.supplier_id)
    if not supplier:
        raise ValueError(f"Supplier {data.supplier_id} not found")

    item_ids = {item.item_id for item in data.items}
    item_map = await _load_inventory_items(session, org_id, item_ids)
    if len(item_map) != len(item_ids):
        raise ValueError("One or more inventory items not found")

    subtotal_cents, total_cents = _calculate_po_totals(
        data.items,
        data.tax_cents,
        data.shipping_cents,
    )

    purchase_order = db_models.PurchaseOrder(
        po_id=uuid.uuid4(),
        org_id=org_id,
        supplier_id=data.supplier_id,
        status=schemas.PurchaseOrderStatus.draft.value,
        ordered_at=None,
        received_at=None,
        notes=_normalize_notes(data.notes),
        subtotal_cents=subtotal_cents,
        tax_cents=data.tax_cents,
        shipping_cents=data.shipping_cents,
        total_cents=total_cents,
    )

    purchase_order.items = [
        db_models.PurchaseOrderItem(
            po_item_id=uuid.uuid4(),
            item_id=item.item_id,
            qty=item.qty,
            unit_cost_cents=item.unit_cost_cents,
            line_total_cents=_calculate_line_total(item.qty, item.unit_cost_cents),
        )
        for item in data.items
    ]

    session.add(purchase_order)
    await session.flush()
    return purchase_order


async def update_purchase_order(
    session: AsyncSession,
    org_id: uuid.UUID,
    po_id: uuid.UUID,
    data: schemas.PurchaseOrderUpdate,
) -> db_models.PurchaseOrder | None:
    """Update a draft purchase order."""
    stmt = (
        select(db_models.PurchaseOrder)
        .where(
            db_models.PurchaseOrder.org_id == org_id,
            db_models.PurchaseOrder.po_id == po_id,
        )
        .options(selectinload(db_models.PurchaseOrder.items))
    )
    result = await session.execute(stmt)
    purchase_order = result.scalar_one_or_none()
    if not purchase_order:
        return None

    if purchase_order.status != schemas.PurchaseOrderStatus.draft.value:
        raise ValueError("Only draft purchase orders can be updated")

    if data.supplier_id is not None:
        supplier = await get_supplier(session, org_id, data.supplier_id)
        if not supplier:
            raise ValueError(f"Supplier {data.supplier_id} not found")
        purchase_order.supplier_id = data.supplier_id

    if data.notes is not None:
        purchase_order.notes = _normalize_notes(data.notes)

    if data.tax_cents is not None:
        purchase_order.tax_cents = data.tax_cents
    if data.shipping_cents is not None:
        purchase_order.shipping_cents = data.shipping_cents

    if data.items is not None:
        item_ids = {item.item_id for item in data.items}
        item_map = await _load_inventory_items(session, org_id, item_ids)
        if len(item_map) != len(item_ids):
            raise ValueError("One or more inventory items not found")
        purchase_order.items = [
            db_models.PurchaseOrderItem(
                po_item_id=uuid.uuid4(),
                item_id=item.item_id,
                qty=item.qty,
                unit_cost_cents=item.unit_cost_cents,
                line_total_cents=_calculate_line_total(item.qty, item.unit_cost_cents),
            )
            for item in data.items
        ]

    current_items = (
        data.items if data.items is not None
        else [
            schemas.PurchaseOrderItemCreate(
                item_id=po_item.item_id,
                qty=po_item.qty,
                unit_cost_cents=po_item.unit_cost_cents,
            )
            for po_item in purchase_order.items
        ]
    )
    subtotal_cents, total_cents = _calculate_po_totals(
        current_items,
        purchase_order.tax_cents,
        purchase_order.shipping_cents,
    )
    purchase_order.subtotal_cents = subtotal_cents
    purchase_order.total_cents = total_cents

    await session.flush()
    return purchase_order


async def mark_purchase_order_ordered(
    session: AsyncSession,
    org_id: uuid.UUID,
    po_id: uuid.UUID,
) -> db_models.PurchaseOrder | None:
    """Mark a purchase order as ordered."""
    purchase_order = await get_purchase_order(session, org_id, po_id)
    if not purchase_order:
        return None

    if purchase_order.status != schemas.PurchaseOrderStatus.draft.value:
        raise ValueError("Only draft purchase orders can be marked as ordered")

    purchase_order.status = schemas.PurchaseOrderStatus.ordered.value
    purchase_order.ordered_at = datetime.now(timezone.utc)
    await session.flush()
    return purchase_order


async def mark_purchase_order_received(
    session: AsyncSession,
    org_id: uuid.UUID,
    po_id: uuid.UUID,
) -> db_models.PurchaseOrder | None:
    """Mark a purchase order as received and update inventory stock."""
    stmt = (
        select(db_models.PurchaseOrder)
        .where(
            db_models.PurchaseOrder.org_id == org_id,
            db_models.PurchaseOrder.po_id == po_id,
        )
        .with_for_update()
        .options(selectinload(db_models.PurchaseOrder.items))
    )
    result = await session.execute(stmt)
    purchase_order = result.scalar_one_or_none()
    if not purchase_order:
        return None

    if purchase_order.status == schemas.PurchaseOrderStatus.received.value:
        raise ValueError("Purchase order already received")
    if purchase_order.status != schemas.PurchaseOrderStatus.ordered.value:
        raise ValueError("Only ordered purchase orders can be marked as received")

    for po_item in purchase_order.items:
        # Use an atomic in-place increment to avoid the read-modify-write race
        # and reduce lock contention versus a separate SELECT ... FOR UPDATE on
        # inventory_items for each line item.
        update_stmt = (
            update(db_models.InventoryItem)
            .where(
                db_models.InventoryItem.org_id == org_id,
                db_models.InventoryItem.item_id == po_item.item_id,
            )
            .values(current_qty=db_models.InventoryItem.current_qty + po_item.qty)
        )
        update_result = await session.execute(update_stmt)
        if update_result.rowcount != 1:
            raise ValueError(
                f"Atomic inventory update expected 1 row, got {update_result.rowcount}"
            )

    purchase_order.status = schemas.PurchaseOrderStatus.received.value
    purchase_order.received_at = datetime.now(timezone.utc)
    await session.flush()
    return purchase_order


# ===== Consumption & Usage Analytics =====


def _calculate_cost_per_booking(total_cents: int, bookings: int) -> int:
    if bookings <= 0:
        return 0
    average = (Decimal(total_cents) / Decimal(bookings)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(average)


async def record_consumption(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: schemas.InventoryConsumptionCreate,
    *,
    recorded_by: str,
) -> db_models.InventoryConsumption:
    """Record a consumption entry for a booking."""
    item_map = await _load_inventory_items(session, org_id, {data.item_id})
    if data.item_id not in item_map:
        raise ValueError("Inventory item not found")

    booking = await session.scalar(
        select(Booking).where(
            Booking.org_id == org_id,
            Booking.booking_id == data.booking_id,
        )
    )
    if not booking:
        raise ValueError("Booking not found")

    service_type = await session.scalar(
        select(ServiceType).where(
            ServiceType.org_id == org_id,
            ServiceType.service_type_id == data.service_type_id,
        )
    )
    if not service_type:
        raise ValueError("Service type not found")

    total_cost_cents = _calculate_line_total(data.qty, data.unit_cost_cents)
    consumption = db_models.InventoryConsumption(
        consumption_id=uuid.uuid4(),
        org_id=org_id,
        booking_id=data.booking_id,
        service_type_id=data.service_type_id,
        item_id=data.item_id,
        qty=data.qty,
        unit_cost_cents=data.unit_cost_cents,
        total_cost_cents=total_cost_cents,
        consumed_at=data.consumed_at or datetime.now(timezone.utc),
        recorded_by=recorded_by,
    )
    session.add(consumption)
    await session.flush()
    return consumption


async def get_usage_analytics(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> schemas.InventoryUsageAnalyticsResponse:
    filters: list = [db_models.InventoryConsumption.org_id == org_id]
    if from_dt is not None:
        filters.append(db_models.InventoryConsumption.consumed_at >= from_dt)
    if to_dt is not None:
        filters.append(db_models.InventoryConsumption.consumed_at <= to_dt)

    totals_stmt = select(
        func.coalesce(func.sum(db_models.InventoryConsumption.total_cost_cents), 0).label(
            "total_consumption"
        ),
        func.count(func.distinct(db_models.InventoryConsumption.booking_id)).label("bookings"),
    ).where(*filters)
    totals_row = (await session.execute(totals_stmt)).one()
    total_consumption_cents = int(totals_row.total_consumption or 0)
    booking_count = int(totals_row.bookings or 0)
    cost_per_booking_avg_cents = _calculate_cost_per_booking(
        total_consumption_cents, booking_count
    )

    service_stmt = (
        select(
            db_models.InventoryConsumption.service_type_id,
            func.count(func.distinct(db_models.InventoryConsumption.booking_id)).label("bookings"),
            func.coalesce(func.sum(db_models.InventoryConsumption.total_cost_cents), 0).label(
                "consumption_cents"
            ),
        )
        .where(*filters)
        .group_by(db_models.InventoryConsumption.service_type_id)
        .order_by(db_models.InventoryConsumption.service_type_id)
    )
    service_rows = (await session.execute(service_stmt)).all()
    by_service_type: list[schemas.InventoryUsageServiceTypeMetric] = []
    for row in service_rows:
        consumption_cents = int(row.consumption_cents or 0)
        bookings = int(row.bookings or 0)
        by_service_type.append(
            schemas.InventoryUsageServiceTypeMetric(
                service_type_id=row.service_type_id,
                bookings=bookings,
                consumption_cents=consumption_cents,
                cost_per_booking_cents=_calculate_cost_per_booking(consumption_cents, bookings),
            )
        )

    top_items_stmt = (
        select(
            db_models.InventoryConsumption.item_id,
            func.coalesce(func.sum(db_models.InventoryConsumption.total_cost_cents), 0).label(
                "consumption_cents"
            ),
            func.coalesce(func.sum(db_models.InventoryConsumption.qty), 0).label("qty"),
        )
        .where(*filters)
        .group_by(db_models.InventoryConsumption.item_id)
        .order_by(desc("consumption_cents"))
    )
    top_items_rows = (await session.execute(top_items_stmt)).all()
    top_items: list[schemas.InventoryUsageTopItemMetric] = []
    for row in top_items_rows:
        qty_value = row.qty if row.qty is not None else Decimal("0")
        if not isinstance(qty_value, Decimal):
            qty_value = Decimal(str(qty_value))
        top_items.append(
            schemas.InventoryUsageTopItemMetric(
                item_id=row.item_id,
                consumption_cents=int(row.consumption_cents or 0),
                qty=qty_value,
            )
        )

    return schemas.InventoryUsageAnalyticsResponse(
        total_consumption_cents=total_consumption_cents,
        cost_per_booking_avg_cents=cost_per_booking_avg_cents,
        by_service_type=by_service_type,
        top_items=top_items,
    )
