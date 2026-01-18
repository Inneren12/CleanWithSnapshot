from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.leads_nurture.statuses import (
    NurtureChannel,
    NurtureEnrollmentStatus,
    NurtureStepLogStatus,
)


class NurtureCampaignResponse(BaseModel):
    campaign_id: UUID
    org_id: UUID
    key: str
    name: str
    enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NurtureCampaignListResponse(BaseModel):
    items: list[NurtureCampaignResponse]


class NurtureCampaignCreateRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool = False


class NurtureCampaignUpdateRequest(BaseModel):
    key: str | None = Field(None, min_length=1, max_length=100)
    name: str | None = Field(None, min_length=1, max_length=255)
    enabled: bool | None = None


class NurtureStepResponse(BaseModel):
    step_id: UUID
    org_id: UUID
    campaign_id: UUID
    step_index: int
    delay_hours: int
    channel: NurtureChannel
    template_key: str | None
    payload_json: dict | None
    active: bool

    class Config:
        from_attributes = True


class NurtureStepListResponse(BaseModel):
    items: list[NurtureStepResponse]


class NurtureStepCreateRequest(BaseModel):
    step_index: int = Field(..., ge=0)
    delay_hours: int = Field(..., ge=0)
    channel: NurtureChannel
    template_key: str | None = Field(None, max_length=255)
    payload_json: dict | None = None
    active: bool = True


class NurtureStepUpdateRequest(BaseModel):
    step_index: int | None = Field(None, ge=0)
    delay_hours: int | None = Field(None, ge=0)
    channel: NurtureChannel | None = None
    template_key: str | None = Field(None, max_length=255)
    payload_json: dict | None = None
    active: bool | None = None


class NurtureEnrollmentResponse(BaseModel):
    enrollment_id: UUID
    org_id: UUID
    lead_id: str
    campaign_id: UUID
    campaign_key: str | None = None
    campaign_name: str | None = None
    enrolled_at: datetime
    status: NurtureEnrollmentStatus


class NurtureStepLogResponse(BaseModel):
    log_id: UUID
    org_id: UUID
    enrollment_id: UUID
    step_index: int
    planned_at: datetime
    sent_at: datetime | None
    status: NurtureStepLogStatus
    idempotency_key: str
    error: str | None


class NurtureEnrollmentCreateRequest(BaseModel):
    campaign_key: str = Field(..., min_length=1, max_length=100)


class NurtureEnrollmentCreateResponse(BaseModel):
    enrollment: NurtureEnrollmentResponse
    planned_logs: list[NurtureStepLogResponse]


class NurtureEnrollmentStatusResponse(BaseModel):
    enrollment: NurtureEnrollmentResponse
    logs: list[NurtureStepLogResponse]


class NurtureLeadStatusResponse(BaseModel):
    items: list[NurtureEnrollmentStatusResponse]


class NurturePlanStepResponse(BaseModel):
    log_id: UUID
    enrollment_id: UUID
    lead_id: str
    campaign_id: UUID
    campaign_key: str
    step_index: int
    planned_at: datetime
    channel: NurtureChannel
    template_key: str | None
    payload_json: dict | None
    status: NurtureStepLogStatus
    idempotency_key: str


class NurturePlanResponse(BaseModel):
    as_of: datetime
    items: list[NurturePlanStepResponse]
