from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.pricing_settings import db_models, schemas


def _pricing_settings_from_record(
    org_id, record: db_models.PricingSettings | None
) -> schemas.PricingSettingsResponse:
    data = {
        "org_id": org_id,
        "gst_rate": float(record.gst_rate) if record else 0.0,
        "discounts": record.discounts if record and record.discounts else [],
        "surcharges": record.surcharges if record and record.surcharges else [],
        "promo_enabled": bool(record.promo_enabled) if record else False,
    }
    return schemas.PricingSettingsResponse.model_validate(data)


def _booking_policies_from_record(
    org_id, record: db_models.BookingPolicy | None
) -> schemas.BookingPoliciesResponse:
    data = {
        "org_id": org_id,
        "deposit": record.deposit_policy if record and record.deposit_policy else {},
        "cancellation": record.cancellation_policy if record and record.cancellation_policy else {},
        "reschedule": record.reschedule_policy if record and record.reschedule_policy else {},
        "payment_terms": record.payment_terms if record and record.payment_terms else {},
        "scheduling": record.scheduling if record and record.scheduling else {},
    }
    return schemas.BookingPoliciesResponse.model_validate(data)


async def list_service_types(
    session: AsyncSession, org_id
) -> list[db_models.ServiceType]:
    result = await session.scalars(
        sa.select(db_models.ServiceType)
        .where(db_models.ServiceType.org_id == org_id)
        .options(selectinload(db_models.ServiceType.addons))
        .order_by(db_models.ServiceType.service_type_id)
    )
    return list(result)


async def get_service_type(
    session: AsyncSession, org_id, service_type_id: int
) -> db_models.ServiceType | None:
    return await session.scalar(
        sa.select(db_models.ServiceType)
        .where(
            db_models.ServiceType.org_id == org_id,
            db_models.ServiceType.service_type_id == service_type_id,
        )
        .options(selectinload(db_models.ServiceType.addons))
    )


async def create_service_type(
    session: AsyncSession, org_id, payload: schemas.ServiceTypeCreate
) -> db_models.ServiceType:
    service_type = db_models.ServiceType(org_id=org_id, **payload.model_dump())
    session.add(service_type)
    await session.flush()
    await session.refresh(service_type)
    return service_type


async def update_service_type(
    session: AsyncSession,
    org_id,
    service_type_id: int,
    payload: schemas.ServiceTypeUpdate,
) -> db_models.ServiceType | None:
    service_type = await get_service_type(session, org_id, service_type_id)
    if not service_type:
        return None
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(service_type, field, value)
    await session.flush()
    await session.refresh(service_type)
    return service_type


async def delete_service_type(session: AsyncSession, org_id, service_type_id: int) -> bool:
    service_type = await session.scalar(
        sa.select(db_models.ServiceType).where(
            db_models.ServiceType.org_id == org_id,
            db_models.ServiceType.service_type_id == service_type_id,
        )
    )
    if not service_type:
        return False
    await session.delete(service_type)
    return True


async def create_addon(
    session: AsyncSession,
    org_id,
    service_type_id: int,
    payload: schemas.ServiceAddonCreate,
) -> db_models.ServiceAddon | None:
    service_type = await session.scalar(
        sa.select(db_models.ServiceType).where(
            db_models.ServiceType.org_id == org_id,
            db_models.ServiceType.service_type_id == service_type_id,
        )
    )
    if not service_type:
        return None
    addon = db_models.ServiceAddon(service_type_id=service_type_id, **payload.model_dump())
    session.add(addon)
    await session.flush()
    await session.refresh(addon)
    return addon


async def update_addon(
    session: AsyncSession,
    org_id,
    addon_id: int,
    payload: schemas.ServiceAddonUpdate,
) -> db_models.ServiceAddon | None:
    addon = await session.scalar(
        sa.select(db_models.ServiceAddon)
        .join(db_models.ServiceType)
        .where(
            db_models.ServiceAddon.addon_id == addon_id,
            db_models.ServiceType.org_id == org_id,
        )
    )
    if not addon:
        return None
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(addon, field, value)
    await session.flush()
    await session.refresh(addon)
    return addon


async def delete_addon(session: AsyncSession, org_id, addon_id: int) -> bool:
    addon = await session.scalar(
        sa.select(db_models.ServiceAddon)
        .join(db_models.ServiceType)
        .where(
            db_models.ServiceAddon.addon_id == addon_id,
            db_models.ServiceType.org_id == org_id,
        )
    )
    if not addon:
        return False
    await session.delete(addon)
    return True


async def get_pricing_settings(
    session: AsyncSession, org_id
) -> schemas.PricingSettingsResponse:
    record = await session.get(db_models.PricingSettings, org_id)
    return _pricing_settings_from_record(org_id, record)


async def upsert_pricing_settings(
    session: AsyncSession, org_id, payload: schemas.PricingSettingsUpdateRequest
) -> schemas.PricingSettingsResponse:
    record = await session.get(db_models.PricingSettings, org_id)
    current = _pricing_settings_from_record(org_id, record)
    payload_data = payload.model_dump(exclude_unset=True)
    updated = schemas.PricingSettingsResponse.model_validate(
        {**current.model_dump(mode="json"), **payload_data}
    )
    if record:
        record.gst_rate = Decimal(str(updated.gst_rate))
        record.discounts = [item.model_dump(mode="json") for item in updated.discounts]
        record.surcharges = [item.model_dump(mode="json") for item in updated.surcharges]
        record.promo_enabled = updated.promo_enabled
    else:
        record = db_models.PricingSettings(
            org_id=org_id,
            gst_rate=Decimal(str(updated.gst_rate)),
            discounts=[item.model_dump(mode="json") for item in updated.discounts],
            surcharges=[item.model_dump(mode="json") for item in updated.surcharges],
            promo_enabled=updated.promo_enabled,
        )
        session.add(record)
    await session.flush()
    return updated


async def get_booking_policies(
    session: AsyncSession, org_id
) -> schemas.BookingPoliciesResponse:
    record = await session.get(db_models.BookingPolicy, org_id)
    return _booking_policies_from_record(org_id, record)


async def upsert_booking_policies(
    session: AsyncSession, org_id, payload: schemas.BookingPoliciesUpdateRequest
) -> schemas.BookingPoliciesResponse:
    record = await session.get(db_models.BookingPolicy, org_id)
    current = _booking_policies_from_record(org_id, record)
    payload_data = payload.model_dump(exclude_unset=True)
    updated = schemas.BookingPoliciesResponse.model_validate(
        {**current.model_dump(mode="json"), **payload_data}
    )
    if record:
        record.deposit_policy = updated.deposit.model_dump(mode="json")
        record.cancellation_policy = updated.cancellation.model_dump(mode="json")
        record.reschedule_policy = updated.reschedule.model_dump(mode="json")
        record.payment_terms = updated.payment_terms.model_dump(mode="json")
        record.scheduling = updated.scheduling.model_dump(mode="json")
    else:
        record = db_models.BookingPolicy(
            org_id=org_id,
            deposit_policy=updated.deposit.model_dump(mode="json"),
            cancellation_policy=updated.cancellation.model_dump(mode="json"),
            reschedule_policy=updated.reschedule.model_dump(mode="json"),
            payment_terms=updated.payment_terms.model_dump(mode="json"),
            scheduling=updated.scheduling.model_dump(mode="json"),
        )
        session.add(record)
    await session.flush()
    return updated
