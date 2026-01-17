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
    "/v1/admin/marketing/analytics/lead-sources",
    response_model=schemas.LeadSourceAnalyticsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_lead_source_analytics(
    period: str,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.LeadSourceAnalyticsResponse:
    return await service.list_lead_source_analytics(session, org_id, period)


@router.get(
    "/v1/admin/marketing/spend",
    response_model=list[schemas.MarketingSpendResponse],
    status_code=status.HTTP_200_OK,
)
async def list_marketing_spend(
    period: str,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> list[schemas.MarketingSpendResponse]:
    return await service.list_marketing_spend(session, org_id, period)


@router.put(
    "/v1/admin/marketing/spend",
    response_model=schemas.MarketingSpendResponse,
    status_code=status.HTTP_200_OK,
)
async def upsert_marketing_spend(
    payload: schemas.MarketingSpendCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.MarketingSpendResponse:
    spend = await service.upsert_marketing_spend(session, org_id, payload)
    await session.commit()
    return spend


@router.get(
    "/v1/admin/marketing/email-segments",
    response_model=list[schemas.EmailSegmentResponse],
    status_code=status.HTTP_200_OK,
)
async def list_email_segments(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> list[schemas.EmailSegmentResponse]:
    return await service.list_email_segments(session, org_id)


@router.post(
    "/v1/admin/marketing/email-segments",
    response_model=schemas.EmailSegmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_email_segment(
    payload: schemas.EmailSegmentCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.EmailSegmentResponse:
    segment = await service.create_email_segment(session, org_id, payload)
    await session.commit()
    return segment


@router.get(
    "/v1/admin/marketing/email-segments/{segment_id}",
    response_model=schemas.EmailSegmentResponse,
    status_code=status.HTTP_200_OK,
)
async def get_email_segment(
    segment_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.EmailSegmentResponse:
    segment = await service.get_email_segment(session, org_id, segment_id)
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email segment not found")
    return service.serialize_email_segment(segment)


@router.patch(
    "/v1/admin/marketing/email-segments/{segment_id}",
    response_model=schemas.EmailSegmentResponse,
    status_code=status.HTTP_200_OK,
)
async def update_email_segment(
    segment_id: uuid.UUID,
    payload: schemas.EmailSegmentUpdate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.EmailSegmentResponse:
    segment = await service.update_email_segment(session, org_id, segment_id, payload)
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email segment not found")
    await session.commit()
    return segment


@router.delete(
    "/v1/admin/marketing/email-segments/{segment_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_email_segment(
    segment_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    deleted = await service.delete_email_segment(session, org_id, segment_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email segment not found")
    await session.commit()


@router.get(
    "/v1/admin/marketing/email-campaigns",
    response_model=list[schemas.EmailCampaignResponse],
    status_code=status.HTTP_200_OK,
)
async def list_email_campaigns(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> list[schemas.EmailCampaignResponse]:
    return await service.list_email_campaigns(session, org_id)


@router.post(
    "/v1/admin/marketing/email-campaigns",
    response_model=schemas.EmailCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_email_campaign(
    payload: schemas.EmailCampaignCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.EmailCampaignResponse:
    campaign = await service.create_email_campaign(session, org_id, payload)
    await session.commit()
    return campaign


@router.get(
    "/v1/admin/marketing/email-campaigns/{campaign_id}",
    response_model=schemas.EmailCampaignResponse,
    status_code=status.HTTP_200_OK,
)
async def get_email_campaign(
    campaign_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.EmailCampaignResponse:
    campaign = await service.get_email_campaign(session, org_id, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email campaign not found")
    return service.serialize_email_campaign(campaign)


@router.patch(
    "/v1/admin/marketing/email-campaigns/{campaign_id}",
    response_model=schemas.EmailCampaignResponse,
    status_code=status.HTTP_200_OK,
)
async def update_email_campaign(
    campaign_id: uuid.UUID,
    payload: schemas.EmailCampaignUpdate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.EmailCampaignResponse:
    campaign = await service.update_email_campaign(session, org_id, campaign_id, payload)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email campaign not found")
    await session.commit()
    return campaign


@router.delete(
    "/v1/admin/marketing/email-campaigns/{campaign_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_email_campaign(
    campaign_id: uuid.UUID,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    deleted = await service.delete_email_campaign(session, org_id, campaign_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email campaign not found")
    await session.commit()
