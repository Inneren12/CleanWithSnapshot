from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.admin_audit.db_models import AdminAuditSensitivity


@dataclass(frozen=True)
class SensitiveReadRule:
    pattern: re.Pattern[str]
    resource_type: str
    sensitivity_level: AdminAuditSensitivity
    resource_id_group: str | None = None

    def match(self, path: str) -> tuple[str, str | None, AdminAuditSensitivity] | None:
        match = self.pattern.match(path)
        if not match:
            return None
        resource_id = match.group(self.resource_id_group) if self.resource_id_group else None
        return (self.resource_type, resource_id, self.sensitivity_level)


SENSITIVE_READ_RULES: tuple[SensitiveReadRule, ...] = (
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/users(?:/(?P<resource_id>[^/]+))?"),
        resource_type="user",
        sensitivity_level=AdminAuditSensitivity.SENSITIVE,
        resource_id_group="resource_id",
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/clients(?:/(?P<resource_id>[^/]+))?"),
        resource_type="client",
        sensitivity_level=AdminAuditSensitivity.SENSITIVE,
        resource_id_group="resource_id",
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/bookings(?:/(?P<resource_id>[^/]+))?"),
        resource_type="booking",
        sensitivity_level=AdminAuditSensitivity.SENSITIVE,
        resource_id_group="resource_id",
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/leads(?:/(?P<resource_id>[^/]+))?"),
        resource_type="lead",
        sensitivity_level=AdminAuditSensitivity.SENSITIVE,
        resource_id_group="resource_id",
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/invoices(?:/(?P<resource_id>[^/]+))?"),
        resource_type="invoice",
        sensitivity_level=AdminAuditSensitivity.SENSITIVE,
        resource_id_group="resource_id",
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/finance(?:/|$)"),
        resource_type="finance",
        sensitivity_level=AdminAuditSensitivity.SENSITIVE,
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/exports(?:/|$)"),
        resource_type="export",
        sensitivity_level=AdminAuditSensitivity.CRITICAL,
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/data/export(?:/|$)"),
        resource_type="export",
        sensitivity_level=AdminAuditSensitivity.CRITICAL,
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/ui/workers/(?:[^/]+/)?export"),
        resource_type="worker_export",
        sensitivity_level=AdminAuditSensitivity.CRITICAL,
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/integrations(?:/|$)"),
        resource_type="integration",
        sensitivity_level=AdminAuditSensitivity.CRITICAL,
    ),
    SensitiveReadRule(
        pattern=re.compile(r"^/v1/admin/audit/actions(?:/|$)"),
        resource_type="admin_audit",
        sensitivity_level=AdminAuditSensitivity.SENSITIVE,
    ),
)


def classify_sensitive_read(path: str) -> tuple[str, str | None, AdminAuditSensitivity] | None:
    for rule in SENSITIVE_READ_RULES:
        matched = rule.match(path)
        if matched:
            return matched
    return None
