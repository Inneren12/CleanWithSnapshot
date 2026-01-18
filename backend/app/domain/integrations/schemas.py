from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class StripeCapabilities(BaseModel):
    card: bool | None = None
    apple_pay: bool | None = None
    google_pay: bool | None = None


class StripeIntegrationStatus(BaseModel):
    connected: bool
    account: str | None = None
    webhook_configured: bool
    last_webhook_at: datetime | None = None
    capabilities: StripeCapabilities
    health: str


class TwilioIntegrationStatus(BaseModel):
    connected: bool
    account: str | None = None
    sms_from: str | None = None
    call_from: str | None = None
    usage_summary: str | None = None
    health: str


class EmailIntegrationStatus(BaseModel):
    connected: bool
    mode: str
    sender: str | None = None
    deliverability: str | None = None
    health: str


class IntegrationsStatusResponse(BaseModel):
    stripe: StripeIntegrationStatus
    twilio: TwilioIntegrationStatus
    email: EmailIntegrationStatus


class GcalIntegrationStatus(BaseModel):
    connected: bool
    calendar_id: str | None = None
    oauth_configured: bool
    last_sync_at: datetime | None = None
    last_error: str | None = None


class GcalConnectStartResponse(BaseModel):
    authorization_url: str


class GcalConnectCallbackRequest(BaseModel):
    code: str
    state: str | None = None


class GcalConnectCallbackResponse(BaseModel):
    connected: bool
    calendar_id: str | None = None


class GcalExportSyncResponse(BaseModel):
    model_config = {"populate_by_name": True}

    calendar_id: str
    from_utc: datetime = Field(alias="from")
    to_utc: datetime = Field(alias="to")
    created: int
    updated: int
    skipped: int
    total: int


class GcalImportSyncResponse(BaseModel):
    model_config = {"populate_by_name": True}

    calendar_id: str
    from_utc: datetime = Field(alias="from")
    to_utc: datetime = Field(alias="to")
    created: int
    updated: int
    skipped: int
    total: int


class ExternalBlockResponse(BaseModel):
    block_id: str
    source: str
    external_event_id: str
    starts_at: datetime
    ends_at: datetime
    summary: str | None = None
