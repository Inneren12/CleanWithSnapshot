"""Inventory domain schemas (Pydantic models for API request/response)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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
