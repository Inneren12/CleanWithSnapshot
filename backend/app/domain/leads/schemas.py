from typing import List, Optional
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.domain.pricing.models import AddOns, CleaningType, EstimateRequest, EstimateResponse, Frequency
from app.domain.leads.statuses import (
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_LOST,
    LEAD_STATUS_NEW,
    LEAD_STATUS_QUOTED,
    LEAD_STATUS_WON,
)
from app.domain.timeline.schemas import TimelineEvent

LeadStatus = Literal[
    LEAD_STATUS_NEW,
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_QUOTED,
    LEAD_STATUS_WON,
    LEAD_STATUS_LOST,
]


class UTMParams(BaseModel):
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None


class LeadStructuredInputs(EstimateRequest):
    model_config = ConfigDict(extra="forbid")
    awaiting_field: Optional[str] = None

    @field_validator("cleaning_type", mode="before")
    @classmethod
    def default_cleaning_type(cls, value):
        return CleaningType.standard if value is None else value

    @field_validator("frequency", mode="before")
    @classmethod
    def default_frequency(cls, value):
        return Frequency.one_time if value is None else value

    @field_validator("heavy_grease", "multi_floor", mode="before")
    @classmethod
    def default_booleans(cls, value):
        return False if value is None else value

    @field_validator("add_ons", mode="before")
    @classmethod
    def default_add_ons(cls, value):
        return AddOns() if value is None else value


class LeadCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    email: Optional[EmailStr] = None
    postal_code: Optional[str] = None
    address: str = Field(..., min_length=1)
    preferred_dates: List[str] = Field(default_factory=list, min_length=1)
    access_notes: Optional[str] = None
    parking: Optional[str] = None
    pets: Optional[str] = None
    allergies: Optional[str] = None
    notes: Optional[str] = None
    structured_inputs: LeadStructuredInputs
    estimate_snapshot: EstimateResponse
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None
    utm: Optional[UTMParams] = None
    source: Optional[str] = None
    campaign: Optional[str] = None
    keyword: Optional[str] = None
    landing_page: Optional[str] = None
    referrer: Optional[str] = None
    referral_code: Optional[str] = Field(
        default=None, min_length=4, max_length=16, description="Referral code applied"
    )
    captcha_token: Optional[str] = Field(
        default=None,
        description="Captcha token when CAPTCHA_MODE is enabled",
        min_length=1,
    )

    @field_validator("name", "phone", "address", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("field cannot be empty")
            return trimmed
        return value

    @field_validator("preferred_dates")
    @classmethod
    def ensure_preferred_dates(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if not cleaned:
            raise ValueError("preferred_dates must include at least one time option")
        return cleaned


class LeadResponse(BaseModel):
    lead_id: str
    next_step_text: str
    referral_code: str


class AdminLeadResponse(BaseModel):
    lead_id: str
    name: str
    email: Optional[EmailStr] = None
    phone: str
    postal_code: Optional[str] = None
    preferred_dates: List[str]
    notes: Optional[str] = None
    source: Optional[str] = None
    campaign: Optional[str] = None
    keyword: Optional[str] = None
    landing_page: Optional[str] = None
    created_at: str
    updated_at: str
    referrer: Optional[str] = None
    status: LeadStatus
    referral_code: str
    referred_by_code: Optional[str] = None
    referral_credits: int


class AdminLeadStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LeadStatus


class AdminLeadUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[LeadStatus] = None
    notes: Optional[str] = None


class AdminLeadListResponse(BaseModel):
    items: List[AdminLeadResponse]
    total: int
    page: int
    page_size: int


class AdminLeadTimelineCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=500)


class AdminLeadDetailResponse(AdminLeadResponse):
    address: Optional[str] = None
    access_notes: Optional[str] = None
    parking: Optional[str] = None
    pets: Optional[str] = None
    allergies: Optional[str] = None
    structured_inputs: dict
    estimate_snapshot: dict
    pricing_config_version: str
    timeline: List[TimelineEvent]


def admin_lead_from_model(model, referral_credit_count: int | None = None) -> AdminLeadResponse:
    credits_attr = getattr(model, "__dict__", {}).get("referral_credits")
    credit_count = referral_credit_count
    if credit_count is None:
        credit_count = len(credits_attr) if credits_attr is not None else 0
    return AdminLeadResponse(
        lead_id=model.lead_id,
        name=model.name,
        email=model.email,
        phone=model.phone,
        postal_code=model.postal_code,
        preferred_dates=model.preferred_dates,
        notes=model.notes,
        source=getattr(model, "source", None),
        campaign=getattr(model, "campaign", None),
        keyword=getattr(model, "keyword", None),
        landing_page=getattr(model, "landing_page", None),
        created_at=model.created_at.isoformat(),
        updated_at=model.updated_at.isoformat(),
        referrer=model.referrer,
        status=model.status or LEAD_STATUS_NEW,
        referral_code=model.referral_code,
        referred_by_code=model.referred_by_code,
        referral_credits=credit_count,
    )


def admin_lead_detail_from_model(
    model, *, timeline: List[TimelineEvent], referral_credit_count: int | None = None
) -> AdminLeadDetailResponse:
    base = admin_lead_from_model(model, referral_credit_count=referral_credit_count)
    return AdminLeadDetailResponse(
        **base.model_dump(mode="json"),
        address=model.address,
        access_notes=model.access_notes,
        parking=model.parking,
        pets=model.pets,
        allergies=model.allergies,
        structured_inputs=model.structured_inputs or {},
        estimate_snapshot=model.estimate_snapshot or {},
        pricing_config_version=model.pricing_config_version,
        timeline=timeline,
    )
