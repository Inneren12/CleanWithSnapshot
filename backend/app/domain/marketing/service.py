from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientUser
from app.domain.errors import DomainError
from app.domain.invoices.db_models import Payment
from app.domain.leads.db_models import Lead, Referral, ReferralCredit
from app.domain.marketing import db_models, schemas
from app.domain.pricing_settings import db_models as pricing_db_models
from app.domain.org_settings import service as org_settings_service


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


DEFAULT_REFERRAL_SETTINGS = schemas.ReferralSettings()


def _merge_referral_settings(raw: dict | None) -> schemas.ReferralSettings:
    merged = DEFAULT_REFERRAL_SETTINGS.model_dump()
    if raw:
        merged.update(raw)
    return schemas.ReferralSettings(**merged)


async def get_referral_settings(
    session: AsyncSession, org_id: uuid.UUID
) -> schemas.ReferralSettings:
    record = await org_settings_service.get_or_create_org_settings(session, org_id)
    return _merge_referral_settings(record.referral_settings if record else None)


async def update_referral_settings(
    session: AsyncSession,
    org_id: uuid.UUID,
    payload: schemas.ReferralSettingsUpdateRequest,
) -> schemas.ReferralSettings:
    record = await org_settings_service.get_or_create_org_settings(session, org_id)
    current = _merge_referral_settings(record.referral_settings if record else None)
    data = current.model_dump()
    updates = payload.model_dump(exclude_unset=True)
    data.update({key: value for key, value in updates.items() if value is not None})
    record.referral_settings = data
    await session.flush()
    return schemas.ReferralSettings(**data)


def _referral_status(referral: Referral) -> str:
    if referral.paid_at:
        return "paid"
    if referral.booked_at:
        return "booked"
    return "pending"


def _credit_summary(credit: ReferralCredit) -> schemas.ReferralCreditSummary:
    return schemas.ReferralCreditSummary(
        credit_id=credit.credit_id,
        recipient_role=credit.recipient_role,
        credit_cents=credit.credit_cents,
        trigger_event=credit.trigger_event,
        created_at=credit.created_at,
    )


def _referral_response(referral: Referral) -> schemas.ReferralResponse:
    return schemas.ReferralResponse(
        referral_id=referral.referral_id,
        org_id=referral.org_id,
        referrer_lead_id=referral.referrer_lead_id,
        referrer_name=referral.referrer.name if referral.referrer else None,
        referred_lead_id=referral.referred_lead_id,
        referred_name=referral.referred.name if referral.referred else None,
        referral_code=referral.referral_code,
        status=_referral_status(referral),
        booking_id=referral.booking_id,
        payment_id=referral.payment_id,
        created_at=referral.created_at,
        booked_at=referral.booked_at,
        paid_at=referral.paid_at,
        credits=[_credit_summary(credit) for credit in referral.credits],
    )


async def ensure_referral_record(
    session: AsyncSession,
    *,
    referrer: Lead,
    referred: Lead,
) -> Referral:
    existing = await session.scalar(
        select(Referral).where(Referral.referred_lead_id == referred.lead_id)
    )
    if existing:
        return existing
    referral = Referral(
        org_id=referred.org_id,
        referrer_lead_id=referrer.lead_id,
        referred_lead_id=referred.lead_id,
        referral_code=referrer.referral_code,
    )
    session.add(referral)
    await session.flush()
    return referral


async def create_referral(
    session: AsyncSession,
    org_id: uuid.UUID,
    payload: schemas.ReferralCreateRequest,
) -> schemas.ReferralResponse:
    referred = await session.scalar(
        select(Lead).where(Lead.org_id == org_id, Lead.lead_id == payload.referred_lead_id)
    )
    if referred is None:
        raise DomainError(detail="Referred lead not found")
    referrer = await session.scalar(
        select(Lead).where(
            Lead.org_id == org_id, Lead.referral_code == payload.referrer_code.strip().upper()
        )
    )
    if referrer is None:
        raise DomainError(detail="Referrer code not found")
    if referred.referred_by_code and referred.referred_by_code != referrer.referral_code:
        raise DomainError(detail="Referred lead already linked to another referral code")
    if not referred.referred_by_code:
        referred.referred_by_code = referrer.referral_code
    referral = await ensure_referral_record(session, referrer=referrer, referred=referred)
    await session.refresh(referral)
    return _referral_response(referral)


async def list_referrals(
    session: AsyncSession, org_id: uuid.UUID
) -> list[schemas.ReferralResponse]:
    result = await session.execute(
        select(Referral)
        .options(
            selectinload(Referral.referrer),
            selectinload(Referral.referred),
            selectinload(Referral.credits),
        )
        .where(Referral.org_id == org_id)
        .order_by(Referral.created_at.desc())
    )
    return [_referral_response(referral) for referral in result.scalars().all()]


async def list_referral_leaderboard(
    session: AsyncSession, org_id: uuid.UUID, limit: int = 10
) -> schemas.ReferralLeaderboardResponse:
    referrer = aliased(Lead)
    referrals_count_subquery = (
        select(
            Referral.referrer_lead_id.label("referrer_lead_id"),
            func.count(Referral.referral_id).label("referrals_count"),
        )
        .where(Referral.org_id == org_id)
        .group_by(Referral.referrer_lead_id)
        .subquery()
    )
    credits_subquery = (
        select(
            ReferralCredit.referrer_lead_id.label("referrer_lead_id"),
            func.count(ReferralCredit.credit_id).label("credits_awarded"),
            func.coalesce(func.sum(ReferralCredit.credit_cents), 0).label("credit_cents"),
        )
        .where(
            ReferralCredit.recipient_role == "referrer",
            ReferralCredit.referrer_lead_id.is_not(None),
        )
        .group_by(ReferralCredit.referrer_lead_id)
        .subquery()
    )
    result = await session.execute(
        select(
            referrer.lead_id,
            referrer.name,
            referrer.referral_code,
            func.coalesce(credits_subquery.c.credits_awarded, 0).label("credits_awarded"),
            func.coalesce(credits_subquery.c.credit_cents, 0).label("credit_cents"),
            func.coalesce(referrals_count_subquery.c.referrals_count, 0).label("referrals_count"),
        )
        .where(
            referrer.org_id == org_id,
            or_(
                credits_subquery.c.credits_awarded.is_not(None),
                referrals_count_subquery.c.referrals_count.is_not(None),
            ),
        )
        .join(credits_subquery, credits_subquery.c.referrer_lead_id == referrer.lead_id, isouter=True)
        .join(referrals_count_subquery, referrals_count_subquery.c.referrer_lead_id == referrer.lead_id, isouter=True)
        .order_by(
            func.coalesce(credits_subquery.c.credits_awarded, 0).desc(),
            func.coalesce(referrals_count_subquery.c.referrals_count, 0).desc(),
            referrer.created_at.asc(),
        )
        .limit(limit)
    )
    entries = [
        schemas.ReferralLeaderboardEntry(
            referrer_lead_id=row.lead_id,
            referrer_name=row.name,
            referral_code=row.referral_code,
            credits_awarded=int(row.credits_awarded or 0),
            credit_cents=int(row.credit_cents or 0),
            referrals_count=int(row.referrals_count or 0),
        )
        for row in result.all()
    ]
    return schemas.ReferralLeaderboardResponse(entries=entries)


async def apply_referral_conversion(
    session: AsyncSession,
    *,
    referred_lead: Lead | None,
    booking: Booking | None = None,
    payment: Payment | None = None,
    trigger_event: schemas.ReferralTrigger,
) -> None:
    if referred_lead is None or not referred_lead.referred_by_code:
        return

    referrer = await session.scalar(
        select(Lead).where(
            Lead.org_id == referred_lead.org_id,
            Lead.referral_code == referred_lead.referred_by_code,
        )
    )
    if referrer is None:
        return

    referral = await ensure_referral_record(session, referrer=referrer, referred=referred_lead)
    if booking and referral.booking_id is None:
        referral.booking_id = booking.booking_id
        referral.booked_at = datetime.now(tz=timezone.utc)
    if payment and referral.payment_id is None:
        referral.payment_id = payment.payment_id
        referral.paid_at = payment.received_at or payment.created_at

    settings_payload = await get_referral_settings(session, referred_lead.org_id)
    if not settings_payload.enabled:
        return

    should_credit = (
        settings_payload.credit_trigger == "booking_or_payment"
        or settings_payload.credit_trigger == trigger_event
    )
    if not should_credit:
        return

    credit_data = [
        ("referrer", settings_payload.referrer_credit_cents),
        ("referee", settings_payload.referee_credit_cents),
    ]
    for recipient_role, credit_cents in credit_data:
        if credit_cents <= 0:
            continue
        credit = ReferralCredit(
            referrer_lead_id=referrer.lead_id,
            referred_lead_id=referred_lead.lead_id,
            referral_id=referral.referral_id,
            applied_code=referrer.referral_code,
            recipient_role=recipient_role,
            credit_cents=credit_cents,
            trigger_event=trigger_event,
        )
        savepoint = await session.begin_nested()
        try:
            session.add(credit)
            await session.flush()
        except IntegrityError:
            await savepoint.rollback()
        else:
            await savepoint.commit()


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
