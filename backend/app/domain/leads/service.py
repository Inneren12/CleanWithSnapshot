import logging
from datetime import datetime, timezone

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.leads.db_models import (
    Lead,
    LeadQuote,
    LeadQuoteFollowUp,
    ReferralCredit,
    generate_referral_code,
)
from app.domain.leads.statuses import (
    QUOTE_STATUS_DRAFT,
    QUOTE_STATUS_EXPIRED,
    QUOTE_STATUS_SENT,
    QUOTE_STATUSES,
)

logger = logging.getLogger(__name__)


async def ensure_unique_referral_code(
    session: AsyncSession, lead: Lead, max_attempts: int = 10
) -> None:
    attempts = 0
    while attempts < max_attempts:
        savepoint = await session.begin_nested()
        try:
            await session.flush()
        except IntegrityError as exc:
            await savepoint.rollback()
            message = str(getattr(exc.orig, "diag", None) or exc.orig or exc).lower()
            if "referral" not in message and "code" not in message:
                raise
            lead.referral_code = generate_referral_code()
            attempts += 1
            continue
        else:
            await savepoint.commit()
            return

    raise RuntimeError("Unable to allocate referral code")


async def grant_referral_credit(session: AsyncSession, referred_lead: Lead | None) -> None:
    """Grant a referral credit for the given lead if applicable.

    Idempotent: unique constraint on ``ReferralCredit.referred_lead_id``
    prevents duplicate credits when the booking is confirmed multiple times
    or the webhook is retried.
    """

    if referred_lead is None:
        return

    if not referred_lead.referred_by_code:
        return

    result = await session.execute(
        select(Lead).where(Lead.referral_code == referred_lead.referred_by_code)
    )
    referrer = result.scalar_one_or_none()
    if referrer is None:
        logger.warning(
            "referral_referrer_missing",
            extra={"extra": {"referred_lead_id": referred_lead.lead_id}},
        )
        return

    credit = ReferralCredit(
        referrer_lead_id=referrer.lead_id,
        referred_lead_id=referred_lead.lead_id,
        applied_code=referrer.referral_code,
    )

    savepoint = await session.begin_nested()
    try:
        session.add(credit)
        await session.flush()
    except IntegrityError:
        await savepoint.rollback()
        return
    else:
        await savepoint.commit()
    logger.info("referral_credit_granted", extra={"extra": {"credit_id": credit.credit_id}})
    logger.debug(
        "referral_credit_details",
        extra={
            "extra": {
                "referrer_lead_id": referrer.lead_id,
                "referred_lead_id": referred_lead.lead_id,
            }
        },
    )


def export_payload_from_lead(lead: Lead) -> dict[str, Any]:
    return {
        "lead_id": lead.lead_id,
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "postal_code": lead.postal_code,
        "address": lead.address,
        "preferred_dates": lead.preferred_dates,
        "access_notes": lead.access_notes,
        "parking": lead.parking,
        "pets": lead.pets,
        "allergies": lead.allergies,
        "notes": lead.notes,
        "loss_reason": getattr(lead, "loss_reason", None),
        "structured_inputs": lead.structured_inputs,
        "estimate_snapshot": lead.estimate_snapshot,
        "pricing_config_version": lead.pricing_config_version,
        "config_hash": lead.config_hash,
        "status": lead.status,
        "utm_source": lead.utm_source,
        "utm_medium": lead.utm_medium,
        "utm_campaign": lead.utm_campaign,
        "utm_term": lead.utm_term,
        "utm_content": lead.utm_content,
        "source": getattr(lead, "source", None),
        "campaign": getattr(lead, "campaign", None),
        "keyword": getattr(lead, "keyword", None),
        "landing_page": getattr(lead, "landing_page", None),
        "referrer": lead.referrer,
        "referral_code": lead.referral_code,
        "referred_by_code": lead.referred_by_code,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "org_id": str(getattr(lead, "org_id", "")),
    }


def resolve_quote_status(status: str, expires_at: datetime | None) -> str:
    if status not in QUOTE_STATUSES:
        raise ValueError(f"Unknown quote status: {status}")
    if expires_at and status in {QUOTE_STATUS_SENT, QUOTE_STATUS_DRAFT}:
        normalized_expires_at = expires_at
        if normalized_expires_at.tzinfo is None:
            normalized_expires_at = normalized_expires_at.replace(tzinfo=timezone.utc)
        if normalized_expires_at <= datetime.now(tz=timezone.utc):
            return QUOTE_STATUS_EXPIRED
    return status


async def create_quote_followup(
    session: AsyncSession,
    *,
    quote: LeadQuote,
    note: str,
    created_by: str | None = None,
) -> LeadQuoteFollowUp:
    now = datetime.now(tz=timezone.utc)
    followup = LeadQuoteFollowUp(
        quote_id=quote.quote_id,
        org_id=quote.org_id,
        note=note,
        created_by=created_by,
        created_at=now,
    )
    session.add(followup)
    await session.flush()
    return followup


async def list_lead_quotes(session: AsyncSession, *, org_id, lead_id: str) -> list[LeadQuote]:
    result = await session.execute(
        select(LeadQuote)
        .options(selectinload(LeadQuote.followups))
        .where(LeadQuote.org_id == org_id, LeadQuote.lead_id == lead_id)
        .order_by(LeadQuote.created_at.desc())
    )
    return list(result.scalars().all())
