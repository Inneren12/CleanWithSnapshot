from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ServiceAddonBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_cents: int = Field(ge=0)
    active: bool = True


class ServiceAddonCreate(ServiceAddonBase):
    pass


class ServiceAddonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    price_cents: int | None = Field(default=None, ge=0)
    active: bool | None = None


class ServiceAddonResponse(ServiceAddonBase):
    addon_id: int
    service_type_id: int


class ServiceTypeBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    active: bool = True
    default_duration_minutes: int = Field(ge=15)
    pricing_model: Literal["flat", "hourly"] = "flat"
    base_price_cents: int = Field(ge=0, default=0)
    hourly_rate_cents: int = Field(ge=0, default=0)
    currency: str = Field(min_length=3, max_length=3)


class ServiceTypeCreate(ServiceTypeBase):
    pass


class ServiceTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None
    default_duration_minutes: int | None = Field(default=None, ge=15)
    pricing_model: Literal["flat", "hourly"] | None = None
    base_price_cents: int | None = Field(default=None, ge=0)
    hourly_rate_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class ServiceTypeResponse(ServiceTypeBase):
    service_type_id: int
    addons: list[ServiceAddonResponse] = Field(default_factory=list)


class PricingAdjustment(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["percent", "flat"]
    percent: float | None = Field(default=None, ge=0.0, le=1.0)
    amount_cents: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_amount(self) -> "PricingAdjustment":
        if self.kind == "percent":
            if self.percent is None:
                raise ValueError("percent adjustments require percent")
        if self.kind == "flat":
            if self.amount_cents is None:
                raise ValueError("flat adjustments require amount_cents")
        return self


class PricingSettingsResponse(BaseModel):
    org_id: uuid.UUID
    gst_rate: float = Field(ge=0.0, le=1.0)
    discounts: list[PricingAdjustment] = Field(default_factory=list)
    surcharges: list[PricingAdjustment] = Field(default_factory=list)
    promo_enabled: bool = False


class PricingSettingsUpdateRequest(BaseModel):
    gst_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    discounts: list[PricingAdjustment] | None = None
    surcharges: list[PricingAdjustment] | None = None
    promo_enabled: bool | None = None


class DepositPolicy(BaseModel):
    enabled: bool = True
    percent: float = Field(0.25, ge=0.0, le=1.0)
    minimum_cents: int | None = Field(default=None, ge=0)
    due_days: int = Field(0, ge=0)
    notes: str | None = Field(default=None, max_length=500)


class CancellationPolicy(BaseModel):
    window_hours: int = Field(24, ge=0)
    refund_percent: float = Field(0.0, ge=0.0, le=1.0)
    fee_cents: int = Field(0, ge=0)
    notes: str | None = Field(default=None, max_length=500)


class ReschedulePolicy(BaseModel):
    allowed: bool = True
    notice_hours: int = Field(24, ge=0)
    fee_cents: int = Field(0, ge=0)
    max_reschedules: int = Field(1, ge=0)


class PaymentTermsPolicy(BaseModel):
    due_days: int = Field(0, ge=0)
    accepted_methods: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=500)


class SchedulingPolicy(BaseModel):
    slot_duration_minutes: int = Field(30, ge=5)
    buffer_minutes: int = Field(0, ge=0)
    lead_time_hours: int = Field(0, ge=0)
    max_bookings_per_day: int | None = Field(default=None, ge=0)


class BookingPoliciesResponse(BaseModel):
    org_id: uuid.UUID
    deposit: DepositPolicy = Field(default_factory=DepositPolicy)
    cancellation: CancellationPolicy = Field(default_factory=CancellationPolicy)
    reschedule: ReschedulePolicy = Field(default_factory=ReschedulePolicy)
    payment_terms: PaymentTermsPolicy = Field(default_factory=PaymentTermsPolicy)
    scheduling: SchedulingPolicy = Field(default_factory=SchedulingPolicy)


class BookingPoliciesUpdateRequest(BaseModel):
    deposit: DepositPolicy | None = None
    cancellation: CancellationPolicy | None = None
    reschedule: ReschedulePolicy | None = None
    payment_terms: PaymentTermsPolicy | None = None
    scheduling: SchedulingPolicy | None = None
