"""Inventory domain schemas (Pydantic models for API request/response)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


# ===== Category Schemas =====


class InventoryCategoryResponse(BaseModel):
    """Response model for inventory category."""

    category_id: UUID
    org_id: UUID
    name: str
    sort_order: int
    created_at: datetime

    class Config:
        from_attributes = True


class InventoryCategoryCreate(BaseModel):
    """Request model for creating an inventory category."""

    name: str = Field(..., min_length=1, max_length=255)
    sort_order: int = Field(default=0, ge=0)


class InventoryCategoryUpdate(BaseModel):
    """Request model for updating an inventory category."""

    name: str | None = Field(None, min_length=1, max_length=255)
    sort_order: int | None = Field(None, ge=0)


class InventoryCategoryListResponse(BaseModel):
    """Paginated list response for inventory categories."""

    items: list[InventoryCategoryResponse]
    total: int
    page: int
    page_size: int


# ===== Item Schemas =====


class InventoryItemResponse(BaseModel):
    """Response model for inventory item."""

    item_id: UUID
    org_id: UUID
    category_id: UUID | None
    sku: str | None
    name: str
    unit: str
    current_qty: Decimal
    min_qty: Decimal
    location_label: str | None
    active: bool
    created_at: datetime
    # Optional: include category name in response
    category_name: str | None = None

    class Config:
        from_attributes = True


class InventoryItemCreate(BaseModel):
    """Request model for creating an inventory item."""

    category_id: UUID | None = None
    sku: str | None = Field(None, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    unit: str = Field(..., min_length=1, max_length=50)
    current_qty: Decimal = Field(default=Decimal("0"), ge=0)
    min_qty: Decimal = Field(default=Decimal("0"), ge=0)
    location_label: str | None = Field(None, max_length=255)
    active: bool = True


class InventoryItemUpdate(BaseModel):
    """Request model for updating an inventory item."""

    category_id: UUID | None = None
    sku: str | None = Field(None, max_length=100)
    name: str | None = Field(None, min_length=1, max_length=255)
    unit: str | None = Field(None, min_length=1, max_length=50)
    current_qty: Decimal | None = Field(None, ge=0)
    min_qty: Decimal | None = Field(None, ge=0)
    location_label: str | None = Field(None, max_length=255)
    active: bool | None = None


class InventoryItemListResponse(BaseModel):
    """Paginated list response for inventory items."""

    items: list[InventoryItemResponse]
    total: int
    page: int
    page_size: int


class InventoryLowStockItemResponse(BaseModel):
    """Response model for low stock inventory item."""

    item_id: UUID
    org_id: UUID
    category_id: UUID | None
    sku: str | None
    name: str
    unit: str
    current_qty: Decimal
    min_qty: Decimal
    need_qty: Decimal
    location_label: str | None
    active: bool
    created_at: datetime
    category_name: str | None = None


class InventoryLowStockListResponse(BaseModel):
    """Paginated list response for low stock inventory items."""

    items: list[InventoryLowStockItemResponse]
    total: int
    page: int
    page_size: int


# ===== Supplier Schemas =====


class InventorySupplierResponse(BaseModel):
    """Response model for inventory supplier."""

    supplier_id: UUID
    org_id: UUID
    name: str
    email: str | None
    phone: str | None
    address: str | None
    terms: str | None
    delivery_days: str | None
    min_order_cents: int | None
    notes: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class InventorySupplierCreate(BaseModel):
    """Request model for creating an inventory supplier."""

    name: str = Field(..., min_length=1, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    address: str | None = None
    terms: str | None = None
    delivery_days: str | None = Field(None, max_length=100)
    min_order_cents: int | None = Field(None, ge=0)
    notes: str | None = None


class InventorySupplierUpdate(BaseModel):
    """Request model for updating an inventory supplier."""

    name: str | None = Field(None, min_length=1, max_length=255)
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    address: str | None = None
    terms: str | None = None
    delivery_days: str | None = Field(None, max_length=100)
    min_order_cents: int | None = Field(None, ge=0)
    notes: str | None = None


class InventorySupplierListResponse(BaseModel):
    """Paginated list response for inventory suppliers."""

    items: list[InventorySupplierResponse]
    total: int
    page: int
    page_size: int


# ===== Purchase Order Schemas =====


class PurchaseOrderStatus(str, Enum):
    draft = "draft"
    ordered = "ordered"
    received = "received"


class PurchaseOrderItemCreate(BaseModel):
    """Request model for creating a purchase order item."""

    item_id: UUID
    qty: Decimal = Field(..., gt=0)
    unit_cost_cents: int = Field(..., ge=0)


class PurchaseOrderItemResponse(BaseModel):
    """Response model for purchase order item."""

    po_item_id: UUID
    po_id: UUID
    item_id: UUID
    qty: Decimal
    unit_cost_cents: int
    line_total_cents: int

    class Config:
        from_attributes = True


class PurchaseOrderCreate(BaseModel):
    """Request model for creating a purchase order."""

    supplier_id: UUID
    notes: str | None = None
    tax_cents: int = Field(default=0, ge=0)
    shipping_cents: int = Field(default=0, ge=0)
    items: list[PurchaseOrderItemCreate] = Field(..., min_length=1)


class PurchaseOrderUpdate(BaseModel):
    """Request model for updating a purchase order."""

    supplier_id: UUID | None = None
    notes: str | None = None
    tax_cents: int | None = Field(None, ge=0)
    shipping_cents: int | None = Field(None, ge=0)
    items: list[PurchaseOrderItemCreate] | None = None


class PurchaseOrderSummaryResponse(BaseModel):
    """Summary response model for purchase orders."""

    po_id: UUID
    org_id: UUID
    supplier_id: UUID
    status: PurchaseOrderStatus
    ordered_at: datetime | None
    received_at: datetime | None
    notes: str | None
    subtotal_cents: int
    tax_cents: int
    shipping_cents: int
    total_cents: int

    class Config:
        from_attributes = True


class PurchaseOrderDetailResponse(PurchaseOrderSummaryResponse):
    """Detailed response model for a purchase order."""

    items: list[PurchaseOrderItemResponse]


class PurchaseOrderListResponse(BaseModel):
    """Paginated list response for purchase orders."""

    items: list[PurchaseOrderSummaryResponse]
    total: int
    page: int
    page_size: int
