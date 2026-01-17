from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientUser
from app.domain.errors import DomainError
from app.domain.marketing import db_models, schemas
from app.domain.pricing_settings import db_models as pricing_db_models


def normalize_code(code: str) -> str:
    return code.strip().upper()


def _promo_response(model: db_models.PromoCode) -> schemas.PromoCodeResponse:
    return schemas.PromoCodeResponse(
        promo_code_id=model.promo_code_id,
        org_id=model.org_id,
        code=model.code,
        name=model.name,
        description=model.description,
        discount_type=model.discount_type,
        percent_off=model.percent_off,
        amount_cents=model.amount_cents,
        free_addon_id=model.free_addon_id,
        valid_from=model.valid_from,
        valid_until=model.valid_until,
        first_time_only=model.first_time_only,
        min_order_cents=model.min_order_cents,
        one_per_customer=model.one_per_customer,
        usage_limit=model.usage_limit,
        active=model.active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def serialize_promo_code(model: db_models.PromoCode) -> schemas.PromoCodeResponse:
    return _promo_response(model)


async def _assert_addon_belongs_to_org(
    session: AsyncSession, org_id: uuid.UUID, addon_id: int | None
) -> None:
    if addon_id is None:
        return
    addon = await session.scalar(
        select(pricing_db_models.ServiceAddon)
        .join(pricing_db_models.ServiceType)
        .where(
            pricing_db_models.ServiceAddon.addon_id == addon_id,
            pricing_db_models.ServiceType.org_id == org_id,
        )
    )
    if addon is None:
        raise DomainError(detail="Addon not found for organization")


async def list_promo_codes(
    session: AsyncSession, org_id: uuid.UUID
) -> list[schemas.PromoCodeResponse]:
    result = await session.execute(
        select(db_models.PromoCode)
        .where(db_models.PromoCode.org_id == org_id)
        .order_by(db_models.PromoCode.created_at.desc())
    )
    return [_promo_response(model) for model in result.scalars().all()]


async def get_promo_code(
    session: AsyncSession, org_id: uuid.UUID, promo_code_id: uuid.UUID
) -> db_models.PromoCode | None:
    return await session.scalar(
        select(db_models.PromoCode).where(
            db_models.PromoCode.org_id == org_id,
            db_models.PromoCode.promo_code_id == promo_code_id,
        )
    )


async def get_promo_code_by_code(
    session: AsyncSession, org_id: uuid.UUID, code: str
) -> db_models.PromoCode | None:
    normalized = normalize_code(code)
    return await session.scalar(
        select(db_models.PromoCode).where(
            db_models.PromoCode.org_id == org_id,
            db_models.PromoCode.code == normalized,
        )
    )


async def create_promo_code(
    session: AsyncSession, org_id: uuid.UUID, payload: schemas.PromoCodeCreate
) -> schemas.PromoCodeResponse:
    normalized = normalize_code(payload.code)
    existing = await get_promo_code_by_code(session, org_id, normalized)
    if existing:
        raise DomainError(detail="Promo code already exists")
    await _assert_addon_belongs_to_org(session, org_id, payload.free_addon_id)
    model = db_models.PromoCode(
        org_id=org_id,
        code=normalized,
        name=payload.name,
        description=payload.description,
        discount_type=payload.discount_type,
        percent_off=payload.percent_off,
        amount_cents=payload.amount_cents,
        free_addon_id=payload.free_addon_id,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        first_time_only=payload.first_time_only,
        min_order_cents=payload.min_order_cents,
        one_per_customer=payload.one_per_customer,
        usage_limit=payload.usage_limit,
        active=payload.active,
    )
    session.add(model)
    await session.flush()
    await session.refresh(model)
    return _promo_response(model)


async def update_promo_code(
    session: AsyncSession,
    org_id: uuid.UUID,
    promo_code_id: uuid.UUID,
    payload: schemas.PromoCodeUpdate,
) -> schemas.PromoCodeResponse | None:
    model = await get_promo_code(session, org_id, promo_code_id)
    if model is None:
        return None

    if payload.code is not None:
        normalized = normalize_code(payload.code)
        if normalized != model.code:
            existing = await get_promo_code_by_code(session, org_id, normalized)
            if existing:
                raise DomainError(detail="Promo code already exists")
        model.code = normalized

    if payload.discount_type is not None:
        model.discount_type = payload.discount_type
        model.percent_off = payload.percent_off
        model.amount_cents = payload.amount_cents
        model.free_addon_id = payload.free_addon_id
    else:
        if payload.percent_off is not None:
            model.percent_off = payload.percent_off
        if payload.amount_cents is not None:
            model.amount_cents = payload.amount_cents
        if payload.free_addon_id is not None:
            model.free_addon_id = payload.free_addon_id

    for field in (
        "name",
        "description",
        "valid_from",
        "valid_until",
        "first_time_only",
        "min_order_cents",
        "one_per_customer",
        "usage_limit",
        "active",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(model, field, value)

    await _assert_addon_belongs_to_org(session, org_id, model.free_addon_id)
    await session.flush()
    await session.refresh(model)
    return _promo_response(model)


async def delete_promo_code(
    session: AsyncSession, org_id: uuid.UUID, promo_code_id: uuid.UUID
) -> bool:
    model = await get_promo_code(session, org_id, promo_code_id)
    if model is None:
        return False
    await session.delete(model)
    return True


async def validate_promo_code(
    session: AsyncSession,
    org_id: uuid.UUID,
    promo: db_models.PromoCode,
    payload: schemas.PromoCodeValidationRequest,
) -> schemas.PromoCodeValidationResponse:
    reasons: list[str] = []
    now = datetime.now(tz=timezone.utc)

    if not promo.active:
        reasons.append("inactive")
    if promo.valid_from and now < promo.valid_from:
        reasons.append("not_started")
    if promo.valid_until and now > promo.valid_until:
        reasons.append("expired")
    if promo.min_order_cents is not None and payload.order_total_cents < promo.min_order_cents:
        reasons.append("minimum_not_met")

    if promo.usage_limit is not None:
        usage = await session.scalar(
            select(func.count(db_models.PromoCodeRedemption.redemption_id)).where(
                db_models.PromoCodeRedemption.org_id == org_id,
                db_models.PromoCodeRedemption.promo_code_id == promo.promo_code_id,
            )
        )
        if usage and usage >= promo.usage_limit:
            reasons.append("usage_limit_reached")

    if promo.first_time_only or promo.one_per_customer:
        if not payload.client_id:
            reasons.append("client_required")
        else:
            client_exists = await session.scalar(
                select(ClientUser.client_id).where(
                    ClientUser.org_id == org_id,
                    ClientUser.client_id == payload.client_id,
                )
            )
            if client_exists is None:
                reasons.append("client_not_found")
            else:
                if promo.first_time_only:
                    bookings = await session.scalar(
                        select(func.count(Booking.booking_id)).where(
                            Booking.org_id == org_id,
                            Booking.client_id == payload.client_id,
                        )
                    )
                    if bookings and bookings > 0:
                        reasons.append("not_first_time")
                if promo.one_per_customer:
                    redemptions = await session.scalar(
                        select(func.count(db_models.PromoCodeRedemption.redemption_id)).where(
                            db_models.PromoCodeRedemption.org_id == org_id,
                            db_models.PromoCodeRedemption.promo_code_id == promo.promo_code_id,
                            db_models.PromoCodeRedemption.client_id == payload.client_id,
                        )
                    )
                    if redemptions and redemptions > 0:
                        reasons.append("already_redeemed")

    return schemas.PromoCodeValidationResponse(
        eligible=not reasons,
        reasons=reasons,
        promo_code=_promo_response(promo),
    )
