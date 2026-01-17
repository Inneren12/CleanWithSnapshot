"""Admin API endpoints for inventory management (categories and items)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, get_admin_identity, permission_keys_for_request
from app.api.org_context import require_org_context
from app.domain.inventory import schemas, service
from app.infra.db import get_db_session

router = APIRouter(tags=["admin-inventory"])


def _require_inventory_view(request: Request, identity: AdminIdentity) -> None:
    """Require inventory.view or core.view permission."""
    permission_keys = permission_keys_for_request(request, identity)
    if "inventory.view" not in permission_keys and "core.view" not in permission_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: requires inventory.view or core.view permission",
        )


def _require_inventory_manage(request: Request, identity: AdminIdentity) -> None:
    """Require inventory.manage or admin.manage permission."""
    permission_keys = permission_keys_for_request(request, identity)
    if "inventory.manage" not in permission_keys and "admin.manage" not in permission_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: requires inventory.manage or admin.manage permission",
        )


# ===== Category Endpoints =====


@router.get(
    "/v1/admin/inventory/categories",
    response_model=schemas.InventoryCategoryListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_inventory_categories(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> schemas.InventoryCategoryListResponse:
    """
    List inventory categories with optional search and pagination.

    Query parameters:
    - query: Search by category name (optional)
    - page: Page number (default: 1)
    - page_size: Items per page (default: 50, max: 100)

    Requires: inventory.view or core.view permission
    """
    _require_inventory_view(request, identity)

    # Enforce max page size
    if page_size > 100:
        page_size = 100
    if page < 1:
        page = 1

    categories, total = await service.list_categories(
        session,
        org_id,
        query=query,
        page=page,
        page_size=page_size,
    )

    return schemas.InventoryCategoryListResponse(
        items=[schemas.InventoryCategoryResponse.model_validate(c) for c in categories],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/v1/admin/inventory/categories",
    response_model=schemas.InventoryCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_inventory_category(
    request: Request,
    data: schemas.InventoryCategoryCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.InventoryCategoryResponse:
    """
    Create a new inventory category.

    Requires: inventory.manage or admin.manage permission
    """
    _require_inventory_manage(request, identity)

    category = await service.create_category(session, org_id, data)
    await session.commit()

    return schemas.InventoryCategoryResponse.model_validate(category)


@router.patch(
    "/v1/admin/inventory/categories/{category_id}",
    response_model=schemas.InventoryCategoryResponse,
    status_code=status.HTTP_200_OK,
)
async def update_inventory_category(
    category_id: uuid.UUID,
    data: schemas.InventoryCategoryUpdate,
    request: Request = None,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.InventoryCategoryResponse:
    """
    Update an existing inventory category.

    Requires: inventory.manage or admin.manage permission
    """
    _require_inventory_manage(request, identity)

    category = await service.update_category(session, org_id, category_id, data)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category {category_id} not found",
        )

    await session.commit()
    return schemas.InventoryCategoryResponse.model_validate(category)


@router.delete(
    "/v1/admin/inventory/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_inventory_category(
    category_id: uuid.UUID,
    request: Request = None,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    Delete an inventory category.

    Note: Items in this category will have their category_id set to NULL.

    Requires: inventory.manage or admin.manage permission
    """
    _require_inventory_manage(request, identity)

    deleted = await service.delete_category(session, org_id, category_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category {category_id} not found",
        )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ===== Item Endpoints =====


@router.get(
    "/v1/admin/inventory/items",
    response_model=schemas.InventoryItemListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_inventory_items(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    query: str | None = None,
    category_id: uuid.UUID | None = None,
    active: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> schemas.InventoryItemListResponse:
    """
    List inventory items with optional filters and pagination.

    Query parameters:
    - query: Search by item name or SKU (optional)
    - category_id: Filter by category (optional)
    - active: Filter by active status (optional)
    - page: Page number (default: 1)
    - page_size: Items per page (default: 50, max: 100)

    Requires: inventory.view or core.view permission
    """
    _require_inventory_view(request, identity)

    # Enforce max page size
    if page_size > 100:
        page_size = 100
    if page < 1:
        page = 1

    items, total = await service.list_items(
        session,
        org_id,
        query=query,
        category_id=category_id,
        active=active,
        page=page,
        page_size=page_size,
    )

    return schemas.InventoryItemListResponse(
        items=[schemas.InventoryItemResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/v1/admin/inventory/items",
    response_model=schemas.InventoryItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_inventory_item(
    request: Request,
    data: schemas.InventoryItemCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.InventoryItemResponse:
    """
    Create a new inventory item.

    Requires: inventory.manage or admin.manage permission
    """
    _require_inventory_manage(request, identity)

    try:
        item = await service.create_item(session, org_id, data)
        await session.commit()
        return schemas.InventoryItemResponse.model_validate(item)
    except ValueError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.patch(
    "/v1/admin/inventory/items/{item_id}",
    response_model=schemas.InventoryItemResponse,
    status_code=status.HTTP_200_OK,
)
async def update_inventory_item(
    item_id: uuid.UUID,
    data: schemas.InventoryItemUpdate,
    request: Request = None,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.InventoryItemResponse:
    """
    Update an existing inventory item.

    Requires: inventory.manage or admin.manage permission
    """
    _require_inventory_manage(request, identity)

    try:
        item = await service.update_item(session, org_id, item_id, data)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Item {item_id} not found",
            )

        await session.commit()
        return schemas.InventoryItemResponse.model_validate(item)
    except ValueError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete(
    "/v1/admin/inventory/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_inventory_item(
    item_id: uuid.UUID,
    request: Request = None,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    Delete an inventory item.

    Requires: inventory.manage or admin.manage permission
    """
    _require_inventory_manage(request, identity)

    deleted = await service.delete_item(session, org_id, item_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found",
        )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
