from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PromoDiscountType = Literal["percent", "amount", "free_addon"]


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


ReferralTrigger = Literal["booking_confirmed", "deposit_paid", "booking_or_payment"]
ReferralRecipientRole = Literal["referrer", "referee"]


class ReferralSettings(BaseModel):
    enabled: bool = True
    referrer_credit_cents: int = Field(default=2500, ge=0)
    referee_credit_cents: int = Field(default=1500, ge=0)
    credit_trigger: ReferralTrigger = "booking_or_payment"


class ReferralSettingsUpdateRequest(BaseModel):
    enabled: bool | None = None
    referrer_credit_cents: int | None = Field(default=None, ge=0)
    referee_credit_cents: int | None = Field(default=None, ge=0)
    credit_trigger: ReferralTrigger | None = None


class ReferralSettingsResponse(BaseModel):
    org_id: uuid.UUID
    settings: ReferralSettings


class ReferralCreateRequest(BaseModel):
    referred_lead_id: str = Field(min_length=1)
    referrer_code: str = Field(min_length=1, max_length=16)


class ReferralCreditSummary(BaseModel):
    credit_id: str
    recipient_role: ReferralRecipientRole
    credit_cents: int | None
    trigger_event: str | None
    created_at: datetime


class ReferralResponse(BaseModel):
    referral_id: uuid.UUID
    org_id: uuid.UUID
    referrer_lead_id: str
    referrer_name: str | None
    referred_lead_id: str
    referred_name: str | None
    referral_code: str
    status: Literal["pending", "booked", "paid"]
    booking_id: str | None
    payment_id: str | None
    created_at: datetime
    booked_at: datetime | None
    paid_at: datetime | None
    credits: list[ReferralCreditSummary]


class ReferralLeaderboardEntry(BaseModel):
    referrer_lead_id: str
    referrer_name: str | None
    referral_code: str
    credits_awarded: int
    credit_cents: int
    referrals_count: int


class ReferralLeaderboardResponse(BaseModel):
    entries: list[ReferralLeaderboardEntry]
