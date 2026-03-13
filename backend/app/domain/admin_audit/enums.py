from enum import Enum


class AdminAuditActionType(str, Enum):
    READ = "READ"
    WRITE = "WRITE"


class AdminAuditSensitivity(str, Enum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    CRITICAL = "critical"
