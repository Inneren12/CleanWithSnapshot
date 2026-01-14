from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DispatcherBoardClient(BaseModel):
    id: str | None
    name: str | None
    phone: str | None = None


class DispatcherBoardAddress(BaseModel):
    id: int | None
    formatted: str | None
    lat: float | None = None
    lng: float | None = None
    zone: str | None = None


class DispatcherBoardWorker(BaseModel):
    id: int | None
    display_name: str | None
    phone: str | None = None


class DispatcherBoardBooking(BaseModel):
    booking_id: str
    status: str
    starts_at: datetime
    ends_at: datetime
    duration_min: int
    client: DispatcherBoardClient
    address: DispatcherBoardAddress
    assigned_worker: DispatcherBoardWorker | None = None
    team_id: int | None
    updated_at: datetime


class DispatcherBoardWorkerSummary(BaseModel):
    worker_id: int
    display_name: str


class DispatcherBoardResponse(BaseModel):
    bookings: list[DispatcherBoardBooking] = Field(default_factory=list)
    workers: list[DispatcherBoardWorkerSummary] = Field(default_factory=list)
    server_time: datetime
    data_version: int
