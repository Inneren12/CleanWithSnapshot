from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.entitlements import resolve_org_id
from app.domain.pricing_settings import schemas, service
from app.infra.db import get_db_session

router = APIRouter(tags=["public-settings"])


def _serialize_service_type(model) -> schemas.ServiceTypeResponse:
    return schemas.ServiceTypeResponse(
        service_type_id=model.service_type_id,
        name=model.name,
        description=model.description,
        active=model.active,
        default_duration_minutes=model.default_duration_minutes,
        pricing_model=model.pricing_model,
        base_price_cents=model.base_price_cents,
        hourly_rate_cents=model.hourly_rate_cents,
        currency=model.currency,
        addons=[
            schemas.ServiceAddonResponse(
                addon_id=addon.addon_id,
                service_type_id=addon.service_type_id,
                name=addon.name,
                price_cents=addon.price_cents,
                active=addon.active,
            )
            for addon in model.addons
            if addon.active
        ],
    )


@router.get(
    "/v1/settings/service-catalog",
    response_model=list[schemas.ServiceTypeResponse],
    status_code=status.HTTP_200_OK,
)
async def public_service_catalog(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> list[schemas.ServiceTypeResponse]:
    org_id: uuid.UUID = resolve_org_id(request)
    service_types = await service.list_service_types(session, org_id)
    return [_serialize_service_type(model) for model in service_types if model.active]


@router.get(
    "/v1/settings/pricing",
    response_model=schemas.PricingSettingsResponse,
    status_code=status.HTTP_200_OK,
)
async def public_pricing_settings(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> schemas.PricingSettingsResponse:
    org_id: uuid.UUID = resolve_org_id(request)
    return await service.get_pricing_settings(session, org_id)


@router.get(
    "/v1/settings/booking-policies",
    response_model=schemas.BookingPoliciesResponse,
    status_code=status.HTTP_200_OK,
)
async def public_booking_policies(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> schemas.BookingPoliciesResponse:
    org_id: uuid.UUID = resolve_org_id(request)
    return await service.get_booking_policies(session, org_id)
