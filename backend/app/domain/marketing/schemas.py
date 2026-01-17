from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

PromoDiscountType = Literal["percent", "amount", "free_addon"]
MarketingCampaignStatus = Literal["DRAFT", "SCHEDULED", "SENT", "CANCELLED"]


class PromoCodeBase(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    discount_type: PromoDiscountType
    percent_off: int | None = Field(default=None, ge=1, le=100)
    amount_cents: int | None = Field(default=None, ge=0)
    free_addon_id: int | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    first_time_only: bool = False
    min_order_cents: int | None = Field(default=None, ge=0)
    one_per_customer: bool = False
    usage_limit: int | None = Field(default=None, ge=1)
    active: bool = True

    @model_validator(mode="after")
    def validate_discount(self) -> "PromoCodeBase":
        if self.discount_type == "percent":
            if self.percent_off is None:
                raise ValueError("percent_off is required for percent promos")
            if self.amount_cents is not None or self.free_addon_id is not None:
                raise ValueError("percent promos cannot set amount_cents or free_addon_id")
        if self.discount_type == "amount":
            if self.amount_cents is None:
                raise ValueError("amount_cents is required for amount promos")
            if self.percent_off is not None or self.free_addon_id is not None:
                raise ValueError("amount promos cannot set percent_off or free_addon_id")
        if self.discount_type == "free_addon":
            if self.free_addon_id is None:
                raise ValueError("free_addon_id is required for free_addon promos")
            if self.percent_off is not None or self.amount_cents is not None:
                raise ValueError("free_addon promos cannot set percent_off or amount_cents")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class PromoCodeCreate(PromoCodeBase):
    pass


class PromoCodeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    discount_type: PromoDiscountType | None = None
    percent_off: int | None = Field(default=None, ge=1, le=100)
    amount_cents: int | None = Field(default=None, ge=0)
    free_addon_id: int | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    first_time_only: bool | None = None
    min_order_cents: int | None = Field(default=None, ge=0)
    one_per_customer: bool | None = None
    usage_limit: int | None = Field(default=None, ge=1)
    active: bool | None = None

    @model_validator(mode="after")
    def validate_discount(self) -> "PromoCodeUpdate":
        if self.discount_type is None:
            return self
        if self.discount_type == "percent":
            if self.percent_off is None:
                raise ValueError("percent_off is required for percent promos")
            if self.amount_cents is not None or self.free_addon_id is not None:
                raise ValueError("percent promos cannot set amount_cents or free_addon_id")
        if self.discount_type == "amount":
            if self.amount_cents is None:
                raise ValueError("amount_cents is required for amount promos")
            if self.percent_off is not None or self.free_addon_id is not None:
                raise ValueError("amount promos cannot set percent_off or free_addon_id")
        if self.discount_type == "free_addon":
            if self.free_addon_id is None:
                raise ValueError("free_addon_id is required for free_addon promos")
            if self.percent_off is not None or self.amount_cents is not None:
                raise ValueError("free_addon promos cannot set percent_off or amount_cents")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class PromoCodeResponse(PromoCodeBase):
    promo_code_id: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class PromoCodeValidationRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    order_total_cents: int = Field(ge=0)
    client_id: str | None = None
    booking_id: str | None = None


class PromoCodeValidationResponse(BaseModel):
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    promo_code: PromoCodeResponse | None = None


class ReferralLeaderboardEntry(BaseModel):
    referrer_lead_id: str
    referrer_name: str | None
    referral_code: str
    credits_awarded: int
    referrals_count: int


class ReferralLeaderboardResponse(BaseModel):
    entries: list[ReferralLeaderboardEntry]


class MarketingSpendBase(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    amount_cents: int = Field(ge=0)


class MarketingSpendCreate(MarketingSpendBase):
    pass


class MarketingSpendResponse(BaseModel):
    spend_id: uuid.UUID
    org_id: uuid.UUID
    source: str
    period: str
    amount_cents: int
    created_at: datetime
    updated_at: datetime


class LeadSourceAnalyticsEntry(BaseModel):
    source: str
    leads_count: int
    bookings_count: int
    revenue_cents: int
    spend_cents: int


class LeadSourceAnalyticsResponse(BaseModel):
    period: str
    sources: list[LeadSourceAnalyticsEntry]


class EmailSegmentDefinition(BaseModel):
    recipients: list[EmailStr] = Field(default_factory=list)


class EmailSegmentBase(BaseModel):
    name: str = Field(min_length=1, max_length=140)
    description: str | None = Field(default=None, max_length=1000)
    definition: EmailSegmentDefinition


class EmailSegmentCreate(EmailSegmentBase):
    pass


class EmailSegmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=140)
    description: str | None = Field(default=None, max_length=1000)
    definition: EmailSegmentDefinition | None = None


class EmailSegmentResponse(BaseModel):
    segment_id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    definition: EmailSegmentDefinition
    created_at: datetime
    updated_at: datetime


class EmailCampaignBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    status: MarketingCampaignStatus = "DRAFT"
    scheduled_for: datetime | None = None
    segment_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_schedule(self) -> "EmailCampaignBase":
        if self.status == "SCHEDULED" and self.scheduled_for is None:
            raise ValueError("scheduled_for is required when status is SCHEDULED")
        return self


class EmailCampaignCreate(EmailCampaignBase):
    pass


class EmailCampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    status: MarketingCampaignStatus | None = None
    scheduled_for: datetime | None = None
    segment_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_schedule(self) -> "EmailCampaignUpdate":
        if self.status == "SCHEDULED" and self.scheduled_for is None:
            raise ValueError("scheduled_for is required when status is SCHEDULED")
        return self


class EmailCampaignResponse(BaseModel):
    campaign_id: uuid.UUID
    org_id: uuid.UUID
    segment_id: uuid.UUID | None
    name: str
    subject: str
    content: str
    status: MarketingCampaignStatus
    scheduled_for: datetime | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
