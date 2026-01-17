from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminRole, require_permission_keys
from app.api.org_context import require_org_context
from app.domain.errors import DomainError
from app.domain.marketing import schemas, service
from app.infra.db import get_db_session

router = APIRouter(tags=["admin-marketing"])


async def require_owner(
    identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
) -> AdminIdentity:
    if identity.role != AdminRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


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


@router.get(
    "/v1/admin/marketing/referrals",
    response_model=list[schemas.ReferralResponse],
    status_code=status.HTTP_200_OK,
)
async def list_referrals(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("core.view")),
    session: AsyncSession = Depends(get_db_session),
) -> list[schemas.ReferralResponse]:
    return await service.list_referrals(session, org_id)


@router.post(
    "/v1/admin/marketing/referrals",
    response_model=schemas.ReferralResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_referral(
    payload: schemas.ReferralCreateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.ReferralResponse:
    try:
        referral = await service.create_referral(session, org_id, payload)
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail) from exc
    await session.commit()
    return referral


@router.get(
    "/v1/admin/marketing/referrals/leaderboard",
    response_model=schemas.ReferralLeaderboardResponse,
    status_code=status.HTTP_200_OK,
)
async def get_referral_leaderboard(
    limit: int = 10,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("core.view")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.ReferralLeaderboardResponse:
    normalized_limit = max(1, min(limit, 50))
    return await service.list_referral_leaderboard(session, org_id, limit=normalized_limit)


@router.get(
    "/v1/admin/marketing/referrals/config",
    response_model=schemas.ReferralSettingsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_referral_config(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.ReferralSettingsResponse:
    settings_payload = await service.get_referral_settings(session, org_id)
    return schemas.ReferralSettingsResponse(org_id=org_id, settings=settings_payload)


@router.patch(
    "/v1/admin/marketing/referrals/config",
    response_model=schemas.ReferralSettingsResponse,
    status_code=status.HTTP_200_OK,
)
async def update_referral_config(
    payload: schemas.ReferralSettingsUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.ReferralSettingsResponse:
    settings_payload = await service.update_referral_settings(session, org_id, payload)
    await session.commit()
    return schemas.ReferralSettingsResponse(org_id=org_id, settings=settings_payload)
