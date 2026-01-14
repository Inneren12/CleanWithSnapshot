from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ChatMessageSummary(BaseModel):
    message_id: int
    sender_type: str
    body: str
    created_at: datetime


class ChatThreadSummary(BaseModel):
    thread_id: uuid.UUID
    thread_type: str
    worker_id: int | None = None
    admin_membership_id: int | None = None
    last_message: ChatMessageSummary | None = None
    unread_count: int


class ChatMessageResponse(BaseModel):
    message_id: int
    thread_id: uuid.UUID
    sender_type: str
    body: str
    created_at: datetime


class ChatMessageCreateRequest(BaseModel):
    body: str

