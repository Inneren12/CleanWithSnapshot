from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


NotificationFilter = Literal["all", "urgent", "unread"]


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
