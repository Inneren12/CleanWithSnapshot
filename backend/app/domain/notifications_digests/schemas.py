from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NotificationDigestKey = Literal[
    "daily_summary",
    "weekly_analytics",
    "monthly_report",
]

NotificationDigestSchedule = Literal["daily", "weekly", "monthly"]


class NotificationDigestSettingResponse(BaseModel):
    digest_key: NotificationDigestKey
    enabled: bool
    schedule: NotificationDigestSchedule
    recipients: list[str] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class NotificationDigestSettingsResponse(BaseModel):
    org_id: str
    digests: list[NotificationDigestSettingResponse] = Field(default_factory=list)


class NotificationDigestSettingUpdate(BaseModel):
    digest_key: NotificationDigestKey
    enabled: bool | None = None
    schedule: NotificationDigestSchedule | None = None
    recipients: list[str] | None = None


class NotificationDigestSettingsUpdateRequest(BaseModel):
    digests: list[NotificationDigestSettingUpdate] = Field(default_factory=list)
