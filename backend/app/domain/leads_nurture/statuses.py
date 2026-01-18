from enum import Enum

NURTURE_CHANNEL_EMAIL = "email"
NURTURE_CHANNEL_SMS = "sms"
NURTURE_CHANNEL_LOG_ONLY = "log_only"

NURTURE_ENROLLMENT_ACTIVE = "active"
NURTURE_ENROLLMENT_PAUSED = "paused"
NURTURE_ENROLLMENT_COMPLETED = "completed"
NURTURE_ENROLLMENT_CANCELLED = "cancelled"

NURTURE_LOG_PLANNED = "planned"
NURTURE_LOG_SENT = "sent"
NURTURE_LOG_SKIPPED = "skipped"
NURTURE_LOG_FAILED = "failed"


class NurtureChannel(str, Enum):
    email = NURTURE_CHANNEL_EMAIL
    sms = NURTURE_CHANNEL_SMS
    log_only = NURTURE_CHANNEL_LOG_ONLY


class NurtureEnrollmentStatus(str, Enum):
    active = NURTURE_ENROLLMENT_ACTIVE
    paused = NURTURE_ENROLLMENT_PAUSED
    completed = NURTURE_ENROLLMENT_COMPLETED
    cancelled = NURTURE_ENROLLMENT_CANCELLED


class NurtureStepLogStatus(str, Enum):
    planned = NURTURE_LOG_PLANNED
    sent = NURTURE_LOG_SENT
    skipped = NURTURE_LOG_SKIPPED
    failed = NURTURE_LOG_FAILED
