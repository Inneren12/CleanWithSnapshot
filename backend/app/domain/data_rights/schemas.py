from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, model_validator

from app.infra.email_validation import E2EEmailStr


class DataExportRequest(BaseModel):
    lead_id: str | None = None
    email: E2EEmailStr | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> DataExportRequest:
        if not self.lead_id and not self.email:
            raise ValueError("lead_id_or_email_required")
        return self


class DataExportResponse(BaseModel):
    leads: list[dict]
    bookings: list[dict]
    invoices: list[dict]
    payments: list[dict]
    photos: list[dict]


class DataRightsExportRequestPayload(BaseModel):
    lead_id: str | None = None
    email: E2EEmailStr | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> DataRightsExportRequestPayload:
        if not self.lead_id and not self.email:
            raise ValueError("lead_id_or_email_required")
        return self


class DataRightsExportRequestResponse(BaseModel):
    export_id: str
    status: str
    created_at: datetime


class DataRightsExportListItem(BaseModel):
    export_id: str
    status: str
    subject_id: str
    subject_type: str
    created_at: datetime
    completed_at: datetime | None = None


class DataRightsExportListResponse(BaseModel):
    items: list[DataRightsExportListItem]
    total: int
    next_cursor: str | None = None
    prev_cursor: str | None = None


class DataDeletionRequestPayload(BaseModel):
    lead_id: str | None = None
    email: E2EEmailStr | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_target(self) -> DataDeletionRequestPayload:
        if not self.lead_id and not self.email:
            raise ValueError("lead_id_or_email_required")
        return self


class DataDeletionResponse(BaseModel):
    request_id: str
    status: str
    matched_leads: int
    pending_deletions: int
    requested_at: datetime


class DataDeletionCleanupResult(BaseModel):
    processed: int
    leads_anonymized: int
    photos_deleted: int
    invoices_detached: int
