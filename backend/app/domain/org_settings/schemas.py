from __future__ import annotations

import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


AllowedLanguage = Literal["en", "ru"]
AllowedCurrency = Literal["CAD", "USD"]
ReferralCreditTrigger = Literal["deposit_paid", "booking_confirmed", "booking_or_payment"]


class BusinessHourWindow(BaseModel):
    enabled: bool = True
    start: str = ""
    end: str = ""


class OrgSettingsResponse(BaseModel):
    org_id: uuid.UUID
    timezone: str
    currency: AllowedCurrency
    language: AllowedLanguage
    business_hours: dict[str, BusinessHourWindow] = Field(default_factory=dict)
    holidays: list[str] = Field(default_factory=list)
    legal_name: str | None = None
    legal_bn: str | None = None
    legal_gst_hst: str | None = None
    legal_address: str | None = None
    legal_phone: str | None = None
    legal_email: str | None = None
    legal_website: str | None = None
    branding: dict[str, str] = Field(default_factory=dict)
    referral_credit_trigger: ReferralCreditTrigger = "booking_confirmed"
    finance_ready: bool = False
    max_users: int | None = Field(default=None, ge=0)
    current_users_count: int = 0


class OrgSettingsUpdateRequest(BaseModel):
    timezone: str | None = None
    currency: AllowedCurrency | None = None
    language: AllowedLanguage | None = None
    business_hours: dict[str, BusinessHourWindow] | None = None
    holidays: list[str] | None = None
    legal_name: str | None = None
    legal_bn: str | None = None
    legal_gst_hst: str | None = None
    legal_address: str | None = None
    legal_phone: str | None = None
    legal_email: str | None = None
    legal_website: str | None = None
    branding: dict[str, str] | None = None
    referral_credit_trigger: ReferralCreditTrigger | None = None
    finance_ready: bool | None = None
    max_users: int | None = Field(default=None, ge=0)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Invalid timezone") from exc
        return value
