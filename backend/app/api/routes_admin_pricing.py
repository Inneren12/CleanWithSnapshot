from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.api.admin_auth import AdminIdentity, AdminPermission, AdminRole, require_permissions, require_viewer
from app.api.org_context import require_org_context
from app.domain.pricing_settings import schemas, service
from app.infra.db import get_db_session

router = APIRouter(tags=["admin-pricing-settings"])


async def require_owner(
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
) -> AdminIdentity:
    if identity.role != AdminRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


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
        ],
    )


@router.get(
    "/v1/admin/service-types",
    response_model=list[schemas.ServiceTypeResponse],
    status_code=status.HTTP_200_OK,
)
async def list_service_types(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> list[schemas.ServiceTypeResponse]:
    service_types = await service.list_service_types(session, org_id)
    return [_serialize_service_type(model) for model in service_types]


@router.post(
    "/v1/admin/service-types",
    response_model=schemas.ServiceTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_service_type(
    payload: schemas.ServiceTypeCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.ServiceTypeResponse:
    try:
        model = await service.create_service_type(session, org_id, payload)
        await session.commit()
        model = await service.get_service_type(session, org_id, model.service_type_id)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Service type already exists") from exc
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service type not found")
    return _serialize_service_type(model)


@router.get(
    "/v1/admin/service-types/{service_type_id}",
    response_model=schemas.ServiceTypeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_service_type(
    service_type_id: int,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.ServiceTypeResponse:
    model = await service.get_service_type(session, org_id, service_type_id)
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service type not found")
    return _serialize_service_type(model)


@router.patch(
    "/v1/admin/service-types/{service_type_id}",
    response_model=schemas.ServiceTypeResponse,
    status_code=status.HTTP_200_OK,
)
async def update_service_type(
    service_type_id: int,
    payload: schemas.ServiceTypeUpdate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.ServiceTypeResponse:
    try:
        model = await service.update_service_type(session, org_id, service_type_id, payload)
        if not model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service type not found")
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Service type already exists") from exc
    return _serialize_service_type(model)


@router.delete(
    "/v1/admin/service-types/{service_type_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_service_type(
    service_type_id: int,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    deleted = await service.delete_service_type(session, org_id, service_type_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service type not found")
    await session.commit()


@router.post(
    "/v1/admin/service-types/{service_type_id}/addons",
    response_model=schemas.ServiceAddonResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_addon(
    service_type_id: int,
    payload: schemas.ServiceAddonCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.ServiceAddonResponse:
    try:
        model = await service.create_addon(session, org_id, service_type_id, payload)
        if not model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service type not found")
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Addon already exists") from exc
    return schemas.ServiceAddonResponse(
        addon_id=model.addon_id,
        service_type_id=model.service_type_id,
        name=model.name,
        price_cents=model.price_cents,
        active=model.active,
    )


@router.patch(
    "/v1/admin/service-addons/{addon_id}",
    response_model=schemas.ServiceAddonResponse,
    status_code=status.HTTP_200_OK,
)
async def update_addon(
    addon_id: int,
    payload: schemas.ServiceAddonUpdate,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.ServiceAddonResponse:
    try:
        model = await service.update_addon(session, org_id, addon_id, payload)
        if not model:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Addon not found")
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Addon already exists") from exc
    return schemas.ServiceAddonResponse(
        addon_id=model.addon_id,
        service_type_id=model.service_type_id,
        name=model.name,
        price_cents=model.price_cents,
        active=model.active,
    )


@router.delete(
    "/v1/admin/service-addons/{addon_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_addon(
    addon_id: int,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    deleted = await service.delete_addon(session, org_id, addon_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Addon not found")
    await session.commit()


@router.get(
    "/v1/admin/pricing-settings",
    response_model=schemas.PricingSettingsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_pricing_settings(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.PricingSettingsResponse:
    return await service.get_pricing_settings(session, org_id)


@router.patch(
    "/v1/admin/pricing-settings",
    response_model=schemas.PricingSettingsResponse,
    status_code=status.HTTP_200_OK,
)
async def update_pricing_settings(
    payload: schemas.PricingSettingsUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.PricingSettingsResponse:
    response = await service.upsert_pricing_settings(session, org_id, payload)
    await session.commit()
    return response


@router.get(
    "/v1/admin/booking-policies",
    response_model=schemas.BookingPoliciesResponse,
    status_code=status.HTTP_200_OK,
)
async def get_booking_policies(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.BookingPoliciesResponse:
    return await service.get_booking_policies(session, org_id)


@router.patch(
    "/v1/admin/booking-policies",
    response_model=schemas.BookingPoliciesResponse,
    status_code=status.HTTP_200_OK,
)
async def update_booking_policies(
    payload: schemas.BookingPoliciesUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.BookingPoliciesResponse:
    response = await service.upsert_booking_policies(session, org_id, payload)
    await session.commit()
    return response
