from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


NotificationFilter = Literal["all", "urgent", "unread"]
NotificationPresetKey = Literal[
    "no_show",
    "payment_failed",
    "negative_review",
    "low_stock",
    "high_value_lead",
]


class NotificationEventResponse(BaseModel):
    id: str
    created_at: datetime
    priority: str
    type: str
    title: str
    body: str
    entity_type: str | None = None
    entity_id: str | None = None
    action_href: str | None = None
    action_kind: str | None = None
    is_read: bool = False
    read_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class NotificationFeedResponse(BaseModel):
    items: list[NotificationEventResponse] = Field(default_factory=list)
    next_cursor: str | None = None
    limit: int


class NotificationReadResponse(BaseModel):
    event_id: str
    read_at: datetime


class NotificationReadAllResponse(BaseModel):
    marked_count: int


class NotificationRulePresetResponse(BaseModel):
    preset_key: NotificationPresetKey
    enabled: bool
    notify_roles: list[str] = Field(default_factory=list)
    notify_user_ids: list[str] = Field(default_factory=list)
    escalation_delay_min: int | None = None


class NotificationRulesResponse(BaseModel):
    org_id: str
    presets: list[NotificationRulePresetResponse] = Field(default_factory=list)


class NotificationRulePresetUpdate(BaseModel):
    preset_key: NotificationPresetKey
    enabled: bool | None = None
    notify_roles: list[str] | None = None
    notify_user_ids: list[str] | None = None
    escalation_delay_min: int | None = None


class NotificationRulesUpdateRequest(BaseModel):
    presets: list[NotificationRulePresetUpdate] = Field(default_factory=list)
