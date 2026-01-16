from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SeriesStatus = Literal["active", "paused", "cancelled"]
SeriesFrequency = Literal["weekly", "monthly"]


class RecurringSeriesBase(BaseModel):
    client_id: str | None = None
    address_id: int | None = None
    service_type_id: int | None = None
    preferred_team_id: int | None = None
    preferred_worker_id: int | None = None
    status: SeriesStatus = "active"
    starts_on: date
    start_time: time
    frequency: SeriesFrequency = "weekly"
    interval: int = Field(default=1, ge=1)
    by_weekday: list[int] = Field(default_factory=list)
    by_monthday: list[int] = Field(default_factory=list)
    ends_on: date | None = None
    duration_minutes: int = Field(ge=1)
    horizon_days: int = Field(default=60, ge=1, le=365)

    @field_validator("by_weekday")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        invalid = [day for day in value if day < 0 or day > 6]
        if invalid:
            raise ValueError("Weekday values must be 0-6 (Mon-Sun)")
        return value

    @field_validator("by_monthday")
    @classmethod
    def validate_monthdays(cls, value: list[int]) -> list[int]:
        invalid = [day for day in value if day < 1 or day > 31]
        if invalid:
            raise ValueError("Monthday values must be 1-31")
        return value


class RecurringSeriesCreate(RecurringSeriesBase):
    pass


class RecurringSeriesUpdate(BaseModel):
    client_id: str | None = None
    address_id: int | None = None
    service_type_id: int | None = None
    preferred_team_id: int | None = None
    preferred_worker_id: int | None = None
    status: SeriesStatus | None = None
    starts_on: date | None = None
    start_time: time | None = None
    frequency: SeriesFrequency | None = None
    interval: int | None = Field(default=None, ge=1)
    by_weekday: list[int] | None = None
    by_monthday: list[int] | None = None
    ends_on: date | None = None
    duration_minutes: int | None = Field(default=None, ge=1)
    horizon_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("by_weekday")
    @classmethod
    def validate_weekdays(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return value
        invalid = [day for day in value if day < 0 or day > 6]
        if invalid:
            raise ValueError("Weekday values must be 0-6 (Mon-Sun)")
        return value

    @field_validator("by_monthday")
    @classmethod
    def validate_monthdays(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return value
        invalid = [day for day in value if day < 1 or day > 31]
        if invalid:
            raise ValueError("Monthday values must be 1-31")
        return value


class RecurringSeriesResponse(BaseModel):
    series_id: uuid.UUID
    org_id: uuid.UUID
    client_id: str | None = None
    address_id: int | None = None
    service_type_id: int | None = None
    preferred_team_id: int | None = None
    preferred_worker_id: int | None = None
    status: SeriesStatus
    starts_on: date
    start_time: time
    frequency: SeriesFrequency
    interval: int
    by_weekday: list[int]
    by_monthday: list[int]
    ends_on: date | None = None
    duration_minutes: int
    horizon_days: int
    next_run_at: datetime | None = None
    next_occurrence_local: datetime | None = None
    created_at: datetime
    updated_at: datetime
    created_count: int
    client_label: str | None = None
    address_label: str | None = None
    service_type_label: str | None = None
    team_label: str | None = None
    worker_label: str | None = None


class RecurringSeriesListResponse(BaseModel):
    org_timezone: str
    items: list[RecurringSeriesResponse]


class RecurringSeriesGenerateRequest(BaseModel):
    horizon_days: int | None = Field(default=None, ge=1, le=365)


class OccurrenceReport(BaseModel):
    scheduled_for: datetime
    booking_id: str | None = None
    reason: str | None = None


class RecurringSeriesGenerateResponse(BaseModel):
    org_timezone: str
    horizon_end: datetime
    next_run_at: datetime | None = None
    created: list[OccurrenceReport]
    needs_assignment: list[OccurrenceReport]
    skipped: list[OccurrenceReport]
    conflicted: list[OccurrenceReport]
