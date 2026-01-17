from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, require_permission_keys
from app.api.org_context import require_org_context
from app.domain.marketing import schemas, service
from app.infra.db import get_db_session

router = APIRouter(tags=["admin-marketing"])


@router.get(
    "/v1/admin/marketing/promo-codes",
    response_model=list[schemas.PromoCodeResponse],
    status_code=status.HTTP_200_OK,
)
async def list_promo_codes(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> list[schemas.PromoCodeResponse]:
    return await service.list_promo_codes(session, org_id)


@router.post(
    "/v1/admin/marketing/promo-codes",
    response_model=schemas.PromoCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_promo_code(
    payload: schemas.PromoCodeCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.PromoCodeResponse:
    promo = await service.create_promo_code(session, org_id, payload)
    await session.commit()
    return promo


@router.get(
    "/v1/admin/marketing/promo-codes/{promo_code_id}",
    response_model=schemas.PromoCodeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_promo_code(
    promo_code_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.PromoCodeResponse:
    promo = await service.get_promo_code(session, org_id, promo_code_id)
    if promo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promo code not found")
    return service.serialize_promo_code(promo)


@router.patch(
    "/v1/admin/marketing/promo-codes/{promo_code_id}",
    response_model=schemas.PromoCodeResponse,
    status_code=status.HTTP_200_OK,
)
async def update_promo_code(
    promo_code_id: uuid.UUID,
    payload: schemas.PromoCodeUpdate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.PromoCodeResponse:
    promo = await service.update_promo_code(session, org_id, promo_code_id, payload)
    if promo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promo code not found")
    await session.commit()
    return promo


@router.delete(
    "/v1/admin/marketing/promo-codes/{promo_code_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_promo_code(
    promo_code_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    deleted = await service.delete_promo_code(session, org_id, promo_code_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promo code not found")
    await session.commit()


@router.post(
    "/v1/admin/marketing/promo-codes/validate",
    response_model=schemas.PromoCodeValidationResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_promo_code(
    payload: schemas.PromoCodeValidationRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.PromoCodeValidationResponse:
    promo = await service.get_promo_code_by_code(session, org_id, payload.code)
    if promo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promo code not found")
    return await service.validate_promo_code(session, org_id, promo, payload)
