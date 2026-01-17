from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientUser
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice
from app.domain.leads.db_models import Lead, ReferralCredit
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


def _parse_period(period: str) -> date:
    try:
        year_str, month_str = period.split("-", 1)
        year = int(year_str)
        month = int(month_str)
        return date(year, month, 1)
    except ValueError as exc:
        raise DomainError(detail="Invalid period format, expected YYYY-MM") from exc


def _format_period(period: date) -> str:
    return f"{period.year:04d}-{period.month:02d}"


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


async def list_referral_leaderboard(
    session: AsyncSession, org_id: uuid.UUID, limit: int = 10
) -> schemas.ReferralLeaderboardResponse:
    result = await session.execute(
        select(
            Lead.lead_id,
            Lead.name,
            Lead.referral_code,
            func.count(ReferralCredit.credit_id).label("credits_awarded"),
            func.count(func.distinct(ReferralCredit.referred_lead_id)).label("referrals_count"),
        )
        .join(ReferralCredit, ReferralCredit.referrer_lead_id == Lead.lead_id)
        .where(Lead.org_id == org_id)
        .group_by(Lead.lead_id)
        .order_by(
            func.count(ReferralCredit.credit_id).desc(),
            func.count(func.distinct(ReferralCredit.referred_lead_id)).desc(),
            Lead.name.asc(),
        )
        .limit(limit)
    )
    entries = [
        schemas.ReferralLeaderboardEntry(
            referrer_lead_id=row.lead_id,
            referrer_name=row.name,
            referral_code=row.referral_code,
            credits_awarded=int(row.credits_awarded or 0),
            referrals_count=int(row.referrals_count or 0),
        )
        for row in result.all()
    ]
    return schemas.ReferralLeaderboardResponse(entries=entries)


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


def _segment_response(model: db_models.EmailSegment) -> schemas.EmailSegmentResponse:
    return schemas.EmailSegmentResponse(
        segment_id=model.segment_id,
        org_id=model.org_id,
        name=model.name,
        description=model.description,
        definition=schemas.EmailSegmentDefinition(**model.definition),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _campaign_response(model: db_models.EmailCampaign) -> schemas.EmailCampaignResponse:
    return schemas.EmailCampaignResponse(
        campaign_id=model.campaign_id,
        org_id=model.org_id,
        segment_id=model.segment_id,
        name=model.name,
        subject=model.subject,
        content=model.content,
        status=model.status,
        scheduled_for=model.scheduled_for,
        sent_at=model.sent_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _spend_response(model: db_models.MarketingSpend) -> schemas.MarketingSpendResponse:
    return schemas.MarketingSpendResponse(
        spend_id=model.spend_id,
        org_id=model.org_id,
        source=model.source,
        period=_format_period(model.period),
        amount_cents=model.amount_cents,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


async def list_marketing_spend(
    session: AsyncSession, org_id: uuid.UUID, period: str
) -> list[schemas.MarketingSpendResponse]:
    period_date = _parse_period(period)
    result = await session.execute(
        select(db_models.MarketingSpend)
        .where(
            db_models.MarketingSpend.org_id == org_id,
            db_models.MarketingSpend.period == period_date,
        )
        .order_by(db_models.MarketingSpend.source.asc())
    )
    return [_spend_response(model) for model in result.scalars().all()]


def serialize_email_segment(model: db_models.EmailSegment) -> schemas.EmailSegmentResponse:
    return _segment_response(model)


def serialize_email_campaign(model: db_models.EmailCampaign) -> schemas.EmailCampaignResponse:
    return _campaign_response(model)


async def upsert_marketing_spend(
    session: AsyncSession, org_id: uuid.UUID, payload: schemas.MarketingSpendCreate
) -> schemas.MarketingSpendResponse:
    period_date = _parse_period(payload.period)
    normalized_source = payload.source.strip()
    existing = await session.scalar(
        select(db_models.MarketingSpend).where(
            db_models.MarketingSpend.org_id == org_id,
            db_models.MarketingSpend.source == normalized_source,
            db_models.MarketingSpend.period == period_date,
        )
    )
    if existing:
        existing.amount_cents = payload.amount_cents
        await session.flush()
        await session.refresh(existing)
        return _spend_response(existing)
    model = db_models.MarketingSpend(
        org_id=org_id,
        source=normalized_source,
        period=period_date,
        amount_cents=payload.amount_cents,
    )
    session.add(model)
    await session.flush()
    await session.refresh(model)
    return _spend_response(model)


async def list_lead_source_analytics(
    session: AsyncSession, org_id: uuid.UUID, period: str
) -> schemas.LeadSourceAnalyticsResponse:
    period_date = _parse_period(period)
    if period_date.month == 12:
        next_period = date(period_date.year + 1, 1, 1)
    else:
        next_period = date(period_date.year, period_date.month + 1, 1)
    start_dt = datetime.combine(period_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_period, datetime.min.time(), tzinfo=timezone.utc)

    source_expr = func.coalesce(Lead.source, Lead.utm_source, sa.literal("Unknown"))

    lead_rows = await session.execute(
        select(source_expr.label("source"), func.count(Lead.lead_id).label("leads_count"))
        .where(Lead.org_id == org_id, Lead.created_at >= start_dt, Lead.created_at < end_dt)
        .group_by(source_expr)
    )
    leads_by_source = {row.source: int(row.leads_count or 0) for row in lead_rows.all()}

    booking_rows = await session.execute(
        select(source_expr.label("source"), func.count(Booking.booking_id).label("bookings_count"))
        .select_from(Booking)
        .join(Lead, Booking.lead_id == Lead.lead_id, isouter=True)
        .where(
            Booking.org_id == org_id,
            Booking.created_at >= start_dt,
            Booking.created_at < end_dt,
        )
        .group_by(source_expr)
    )
    bookings_by_source = {
        row.source: int(row.bookings_count or 0) for row in booking_rows.all()
    }

    revenue_rows = await session.execute(
        select(source_expr.label("source"), func.sum(Invoice.total_cents).label("revenue_cents"))
        .select_from(Invoice)
        .join(Booking, Invoice.order_id == Booking.booking_id)
        .join(Lead, Booking.lead_id == Lead.lead_id, isouter=True)
        .where(
            Invoice.org_id == org_id,
            Invoice.status.in_(
                {
                    invoice_statuses.INVOICE_STATUS_PAID,
                    invoice_statuses.INVOICE_STATUS_PARTIAL,
                }
            ),
            Invoice.created_at >= start_dt,
            Invoice.created_at < end_dt,
        )
        .group_by(source_expr)
    )
    revenue_by_source = {
        row.source: int(row.revenue_cents or 0) for row in revenue_rows.all()
    }

    spend_rows = await session.execute(
        select(
            db_models.MarketingSpend.source,
            db_models.MarketingSpend.amount_cents,
        ).where(
            db_models.MarketingSpend.org_id == org_id,
            db_models.MarketingSpend.period == period_date,
        )
    )
    spend_by_source = {
        row.source: int(row.amount_cents or 0) for row in spend_rows.all()
    }

    all_sources = set(leads_by_source) | set(bookings_by_source) | set(revenue_by_source) | set(
        spend_by_source
    )
    sources = [
        schemas.LeadSourceAnalyticsEntry(
            source=source,
            leads_count=leads_by_source.get(source, 0),
            bookings_count=bookings_by_source.get(source, 0),
            revenue_cents=revenue_by_source.get(source, 0),
            spend_cents=spend_by_source.get(source, 0),
        )
        for source in sorted(all_sources)
    ]
    sources.sort(key=lambda entry: (entry.leads_count, entry.bookings_count), reverse=True)
    return schemas.LeadSourceAnalyticsResponse(period=_format_period(period_date), sources=sources)


async def list_email_segments(
    session: AsyncSession, org_id: uuid.UUID
) -> list[schemas.EmailSegmentResponse]:
    result = await session.execute(
        select(db_models.EmailSegment)
        .where(db_models.EmailSegment.org_id == org_id)
        .order_by(db_models.EmailSegment.created_at.desc())
    )
    return [_segment_response(model) for model in result.scalars().all()]


async def get_email_segment(
    session: AsyncSession, org_id: uuid.UUID, segment_id: uuid.UUID
) -> db_models.EmailSegment | None:
    return await session.scalar(
        select(db_models.EmailSegment).where(
            db_models.EmailSegment.org_id == org_id,
            db_models.EmailSegment.segment_id == segment_id,
        )
    )


async def create_email_segment(
    session: AsyncSession, org_id: uuid.UUID, payload: schemas.EmailSegmentCreate
) -> schemas.EmailSegmentResponse:
    existing = await session.scalar(
        select(db_models.EmailSegment).where(
            db_models.EmailSegment.org_id == org_id,
            db_models.EmailSegment.name == payload.name,
        )
    )
    if existing:
        raise DomainError(detail="Segment name already exists")
    model = db_models.EmailSegment(
        org_id=org_id,
        name=payload.name,
        description=payload.description,
        definition=payload.definition.model_dump(),
    )
    session.add(model)
    await session.flush()
    await session.refresh(model)
    return _segment_response(model)


async def update_email_segment(
    session: AsyncSession,
    org_id: uuid.UUID,
    segment_id: uuid.UUID,
    payload: schemas.EmailSegmentUpdate,
) -> schemas.EmailSegmentResponse | None:
    model = await get_email_segment(session, org_id, segment_id)
    if model is None:
        return None
    if payload.name is not None and payload.name != model.name:
        existing = await session.scalar(
            select(db_models.EmailSegment).where(
                db_models.EmailSegment.org_id == org_id,
                db_models.EmailSegment.name == payload.name,
            )
        )
        if existing:
            raise DomainError(detail="Segment name already exists")
        model.name = payload.name
    if payload.description is not None:
        model.description = payload.description
    if payload.definition is not None:
        model.definition = payload.definition.model_dump()
    await session.flush()
    await session.refresh(model)
    return _segment_response(model)


async def delete_email_segment(
    session: AsyncSession, org_id: uuid.UUID, segment_id: uuid.UUID
) -> bool:
    model = await get_email_segment(session, org_id, segment_id)
    if model is None:
        return False
    await session.delete(model)
    return True


async def list_email_campaigns(
    session: AsyncSession, org_id: uuid.UUID
) -> list[schemas.EmailCampaignResponse]:
    result = await session.execute(
        select(db_models.EmailCampaign)
        .where(db_models.EmailCampaign.org_id == org_id)
        .order_by(db_models.EmailCampaign.created_at.desc())
    )
    return [_campaign_response(model) for model in result.scalars().all()]


async def get_email_campaign(
    session: AsyncSession, org_id: uuid.UUID, campaign_id: uuid.UUID
) -> db_models.EmailCampaign | None:
    return await session.scalar(
        select(db_models.EmailCampaign).where(
            db_models.EmailCampaign.org_id == org_id,
            db_models.EmailCampaign.campaign_id == campaign_id,
        )
    )


async def _assert_segment_belongs_to_org(
    session: AsyncSession, org_id: uuid.UUID, segment_id: uuid.UUID | None
) -> None:
    if segment_id is None:
        return
    segment = await session.scalar(
        select(db_models.EmailSegment).where(
            db_models.EmailSegment.org_id == org_id,
            db_models.EmailSegment.segment_id == segment_id,
        )
    )
    if segment is None:
        raise DomainError(detail="Segment not found for organization")


async def create_email_campaign(
    session: AsyncSession, org_id: uuid.UUID, payload: schemas.EmailCampaignCreate
) -> schemas.EmailCampaignResponse:
    await _assert_segment_belongs_to_org(session, org_id, payload.segment_id)
    model = db_models.EmailCampaign(
        org_id=org_id,
        segment_id=payload.segment_id,
        name=payload.name,
        subject=payload.subject,
        content=payload.content,
        status=payload.status,
        scheduled_for=payload.scheduled_for,
    )
    session.add(model)
    await session.flush()
    await session.refresh(model)
    return _campaign_response(model)


async def update_email_campaign(
    session: AsyncSession,
    org_id: uuid.UUID,
    campaign_id: uuid.UUID,
    payload: schemas.EmailCampaignUpdate,
) -> schemas.EmailCampaignResponse | None:
    model = await get_email_campaign(session, org_id, campaign_id)
    if model is None:
        return None
    if payload.segment_id is not None:
        await _assert_segment_belongs_to_org(session, org_id, payload.segment_id)
        model.segment_id = payload.segment_id
    for field in ("name", "subject", "content", "status", "scheduled_for"):
        value = getattr(payload, field)
        if value is not None:
            setattr(model, field, value)
    if model.status == "SCHEDULED" and model.scheduled_for is None:
        raise DomainError(detail="scheduled_for is required when status is SCHEDULED")
    await session.flush()
    await session.refresh(model)
    return _campaign_response(model)


async def delete_email_campaign(
    session: AsyncSession, org_id: uuid.UUID, campaign_id: uuid.UUID
) -> bool:
    model = await get_email_campaign(session, org_id, campaign_id)
    if model is None:
        return False
    await session.delete(model)
    return True
