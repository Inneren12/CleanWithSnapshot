from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TicketStatus = Literal["OPEN", "IN_PROGRESS", "RESOLVED"]
NpsSegment = Literal["promoter", "passive", "detractor"]


class PublicNpsSubmitRequest(BaseModel):
    score: int = Field(..., ge=0, le=10, description="NPS score from 0 to 10")
    comment: str | None = Field(
        None, max_length=2000, description="Optional feedback comment"
    )


class PublicNpsSubmitResponse(BaseModel):
    status: Literal["submitted", "already_submitted"]
    token: str
    created_at: datetime


class NpsResponseItem(BaseModel):
    token: str
    booking_id: str
    client_id: str | None
    score: int
    comment: str | None
    created_at: datetime


class NpsResponseListResponse(BaseModel):
    responses: list[NpsResponseItem]


class TicketResponse(BaseModel):
    id: str
    order_id: str
    client_id: str | None
    status: TicketStatus
    priority: str
    subject: str
    body: str
    created_at: datetime
    updated_at: datetime


class TicketListResponse(BaseModel):
    tickets: list[TicketResponse]


class TicketUpdateRequest(BaseModel):
    status: TicketStatus = Field(..., description="New status for the ticket")
