from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime

from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.domain.leads.statuses import default_lead_status
from app.infra.db import UUID_TYPE
from app.infra.db import Base
from app.settings import settings


CHARSET = string.ascii_uppercase + string.digits
CODE_LENGTH = 8


def generate_referral_code() -> str:
    return "".join(secrets.choice(CHARSET) for _ in range(CODE_LENGTH))


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    brand: Mapped[str] = mapped_column(String(32), nullable=False, default="economy")
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Lead(Base):
    __tablename__ = "leads"

    lead_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(255))
    preferred_dates: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    access_notes: Mapped[str | None] = mapped_column(String(255))
    parking: Mapped[str | None] = mapped_column(String(255))
    pets: Mapped[str | None] = mapped_column(String(255))
    allergies: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(String(500))
    loss_reason: Mapped[str | None] = mapped_column(String(255))
    structured_inputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    estimate_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    pricing_config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=default_lead_status)
    utm_source: Mapped[str | None] = mapped_column(String(100))
    utm_medium: Mapped[str | None] = mapped_column(String(100))
    utm_campaign: Mapped[str | None] = mapped_column(String(100))
    utm_term: Mapped[str | None] = mapped_column(String(100))
    utm_content: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(String(100))
    campaign: Mapped[str | None] = mapped_column(String(100))
    keyword: Mapped[str | None] = mapped_column(String(100))
    landing_page: Mapped[str | None] = mapped_column(String(255))
    referrer: Mapped[str | None] = mapped_column(String(255))
    referral_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        unique=True,
    )
    referred_by_code: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    pending_deletion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    referral_credits: Mapped[list["ReferralCredit"]] = relationship(
        "ReferralCredit",
        primaryjoin=(
            "and_(Lead.lead_id == foreign(ReferralCredit.referrer_lead_id), "
            "ReferralCredit.recipient_role == 'referrer')"
        ),
        viewonly=True,
    )
    referred_credit: Mapped[Optional["ReferralCredit"]] = relationship(
        "ReferralCredit",
        primaryjoin=(
            "and_(Lead.lead_id == foreign(ReferralCredit.referred_lead_id), "
            "ReferralCredit.recipient_role == 'referee')"
        ),
        viewonly=True,
        uselist=False,
    )
    referrals_sent: Mapped[list["Referral"]] = relationship(
        "Referral",
        back_populates="referrer",
        foreign_keys="Referral.referrer_lead_id",
    )
    referral_received: Mapped[Optional["Referral"]] = relationship(
        "Referral",
        back_populates="referred",
        foreign_keys="Referral.referred_lead_id",
        uselist=False,
    )
    quotes: Mapped[list["LeadQuote"]] = relationship(
        "LeadQuote",
        back_populates="lead",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_leads_org_id", "org_id"),
        Index("ix_leads_org_status", "org_id", "status"),
        Index("ix_leads_org_created_at", "org_id", "created_at"),
    )

    def __init__(self, **kwargs: object) -> None:
        if not kwargs.get("referral_code"):
            kwargs["referral_code"] = generate_referral_code()
        super().__init__(**kwargs)


class ReferralCredit(Base):
    __tablename__ = "referral_credits"
    __table_args__ = (
        UniqueConstraint(
            "referred_lead_id",
            "recipient_role",
            name="uq_referral_credits_referred_role",
        ),
        Index("ix_referral_credits_referrer_lead_id", "referrer_lead_id"),
        Index("ix_referral_credits_referred_lead_id", "referred_lead_id"),
        Index("ix_referral_credits_referral_id", "referral_id"),
    )

    credit_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    referrer_lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.lead_id"), nullable=False
    )
    referred_lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.lead_id"), nullable=False
    )
    referral_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE,
        ForeignKey("referrals.referral_id", ondelete="SET NULL"),
        nullable=True,
    )
    applied_code: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient_role: Mapped[str] = mapped_column(String(16), nullable=False, default="referrer")
    credit_cents: Mapped[int | None] = mapped_column(Integer)
    trigger_event: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    referrer: Mapped[Lead] = relationship(Lead, foreign_keys=[referrer_lead_id])
    referred: Mapped[Lead] = relationship(Lead, foreign_keys=[referred_lead_id])
    referral: Mapped[Optional["Referral"]] = relationship("Referral", back_populates="credits")


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referred_lead_id", name="uq_referrals_referred_lead"),
        Index("ix_referrals_org_id", "org_id"),
        Index("ix_referrals_referrer_lead_id", "referrer_lead_id"),
        Index("ix_referrals_referred_lead_id", "referred_lead_id"),
    )

    referral_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    referrer_lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.lead_id"), nullable=False
    )
    referred_lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.lead_id"), nullable=False
    )
    referral_code: Mapped[str] = mapped_column(String(16), nullable=False)
    booking_id: Mapped[str | None] = mapped_column(
        ForeignKey("bookings.booking_id", ondelete="SET NULL")
    )
    payment_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoice_payments.payment_id", ondelete="SET NULL")
    )
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    referrer: Mapped[Lead] = relationship(
        Lead,
        back_populates="referrals_sent",
        foreign_keys=[referrer_lead_id],
    )
    referred: Mapped[Lead] = relationship(
        Lead,
        back_populates="referral_received",
        foreign_keys=[referred_lead_id],
    )
    credits: Mapped[list[ReferralCredit]] = relationship(
        "ReferralCredit",
        back_populates="referral",
        cascade="all, delete-orphan",
    )


class LeadQuote(Base):
    __tablename__ = "lead_quotes"

    quote_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.lead_id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CAD")
    service_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    lead: Mapped[Lead] = relationship("Lead", back_populates="quotes")
    followups: Mapped[list["LeadQuoteFollowUp"]] = relationship(
        "LeadQuoteFollowUp",
        back_populates="quote",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_lead_quotes_org_id", "org_id"),
        Index("ix_lead_quotes_lead_id", "lead_id"),
    )


class LeadQuoteFollowUp(Base):
    __tablename__ = "lead_quote_followups"

    followup_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    quote_id: Mapped[str] = mapped_column(
        ForeignKey("lead_quotes.quote_id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    note: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    quote: Mapped[LeadQuote] = relationship("LeadQuote", back_populates="followups")

    __table_args__ = (
        Index("ix_lead_quote_followups_org_id", "org_id"),
        Index("ix_lead_quote_followups_quote_id", "quote_id"),
    )
