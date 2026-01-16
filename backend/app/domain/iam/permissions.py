from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PermissionDefinition:
    key: str
    label: str
    description: str
    group: str | None = None


@dataclass(frozen=True)
class RoleDefinition:
    key: str
    name: str
    description: str
    permissions: set[str]
    builtin: bool = True


PERMISSION_CATALOG: list[PermissionDefinition] = [
    PermissionDefinition(
        key="core.view",
        label="Core view",
        description="Read-only access to admin modules and dashboards.",
        group="core",
    ),
    PermissionDefinition(
        key="bookings.view",
        label="View bookings",
        description="Read access to booking and schedule data.",
        group="bookings",
    ),
    PermissionDefinition(
        key="bookings.edit",
        label="Edit bookings",
        description="Update booking details and reschedule jobs.",
        group="bookings",
    ),
    PermissionDefinition(
        key="bookings.assign",
        label="Assign bookings",
        description="Assign teams and workers to bookings.",
        group="bookings",
    ),
    PermissionDefinition(
        key="schedule.blocking.manage",
        label="Manage availability blocks",
        description="Create, update, and delete availability blocks.",
        group="schedule",
    ),
    PermissionDefinition(
        key="bookings.status",
        label="Update booking status",
        description="Update booking status and job progress.",
        group="bookings",
    ),
    PermissionDefinition(
        key="contacts.view",
        label="View contacts",
        description="Read client contact details.",
        group="contacts",
    ),
    PermissionDefinition(
        key="contacts.edit",
        label="Edit contacts",
        description="Update client contact details and follow-ups.",
        group="contacts",
    ),
    PermissionDefinition(
        key="quality.view",
        label="View quality issues",
        description="Read quality issue triage and issue details.",
        group="quality",
    ),
    PermissionDefinition(
        key="quality.manage",
        label="Manage quality issues",
        description="Resolve and manage quality issues.",
        group="quality",
    ),
    PermissionDefinition(
        key="invoices.view",
        label="View invoices",
        description="Read invoice data and billing history.",
        group="finance",
    ),
    PermissionDefinition(
        key="invoices.edit",
        label="Edit invoices",
        description="Create and update invoices.",
        group="finance",
    ),
    PermissionDefinition(
        key="invoices.send",
        label="Send invoice reminders",
        description="Send invoice reminder emails.",
        group="finance",
    ),
    PermissionDefinition(
        key="payments.record",
        label="Record payments",
        description="Record and reconcile payments.",
        group="finance",
    ),
    PermissionDefinition(
        key="finance.view",
        label="View finance reports",
        description="Access finance analytics and reports.",
        group="finance",
    ),
    PermissionDefinition(
        key="pricing.manage",
        label="Manage pricing",
        description="Manage pricing configurations and reload pricing.",
        group="settings",
    ),
    PermissionDefinition(
        key="policies.manage",
        label="Manage policies",
        description="Manage booking, cancellation, and deposit policies.",
        group="settings",
    ),
    PermissionDefinition(
        key="settings.manage",
        label="Manage settings",
        description="Update organization settings and integrations.",
        group="settings",
    ),
    PermissionDefinition(
        key="users.manage",
        label="Manage users",
        description="Create, deactivate, and change user roles.",
        group="iam",
    ),
    PermissionDefinition(
        key="exports.run",
        label="Run exports",
        description="Run data exports and download CSVs.",
        group="ops",
    ),
    PermissionDefinition(
        key="reports.view",
        label="View operational reports",
        description="Access operational dashboards and summaries.",
        group="analytics",
    ),
    PermissionDefinition(
        key="admin.manage",
        label="Admin management",
        description="Access high-risk admin endpoints.",
        group="admin",
    ),
]

PERMISSION_KEYS: set[str] = {entry.key for entry in PERMISSION_CATALOG}

ROLE_DEFINITIONS: dict[str, RoleDefinition] = {
    "owner": RoleDefinition(
        key="owner",
        name="Owner",
        description="Full access across organization settings, finance, exports, and user management.",
        permissions=set(PERMISSION_KEYS),
    ),
    "admin": RoleDefinition(
        key="admin",
        name="Admin",
        description="Full operational access across admin modules and settings.",
        permissions=set(PERMISSION_KEYS),
    ),
    "dispatcher": RoleDefinition(
        key="dispatcher",
        name="Dispatcher",
        description="Manage bookings, schedules, and client follow-ups.",
        permissions={
            "core.view",
            "bookings.view",
            "bookings.edit",
            "bookings.assign",
            "contacts.view",
            "contacts.edit",
            "reports.view",
        },
    ),
    "accountant": RoleDefinition(
        key="accountant",
        name="Accountant",
        description="Manage invoices, payments, and finance reporting.",
        permissions={
            "core.view",
            "bookings.view",
            "invoices.view",
            "invoices.edit",
            "invoices.send",
            "payments.record",
            "finance.view",
            "exports.run",
        },
    ),
    "finance": RoleDefinition(
        key="finance",
        name="Finance",
        description="Manage invoices, payments, and finance reporting.",
        permissions={
            "core.view",
            "bookings.view",
            "invoices.view",
            "invoices.edit",
            "invoices.send",
            "payments.record",
            "finance.view",
            "exports.run",
        },
    ),
    "viewer": RoleDefinition(
        key="viewer",
        name="Viewer",
        description="Read-only access without contact or finance actions.",
        permissions={
            "core.view",
            "bookings.view",
            "invoices.view",
            "contacts.view",
            "reports.view",
        },
    ),
    "worker": RoleDefinition(
        key="worker",
        name="Worker",
        description="View assigned bookings and update job status.",
        permissions={
            "bookings.view",
            "bookings.status",
        },
    ),
}

LEGACY_ADMIN_PERMISSION_MAP: dict[str, set[str]] = {
    "view": {"core.view"},
    "dispatch": {"bookings.assign"},
    "finance": {"finance.view"},
    "admin": {"admin.manage"},
}


def normalize_permission_keys(keys: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in keys or []:
        if not raw:
            continue
        key = str(raw).strip()
        if not key or key in seen:
            continue
        normalized.append(key)
        seen.add(key)
    return normalized


def permissions_for_role(role_key: str | None) -> set[str]:
    if not role_key:
        return set()
    role = ROLE_DEFINITIONS.get(role_key.lower())
    if not role:
        return set()
    return set(role.permissions)


def effective_permissions(
    *,
    role_key: str | None,
    custom_permissions: Iterable[str] | None = None,
) -> set[str]:
    if custom_permissions is not None:
        return {key for key in normalize_permission_keys(custom_permissions) if key in PERMISSION_KEYS}
    return permissions_for_role(role_key)


def builtin_roles() -> list[RoleDefinition]:
    return list(ROLE_DEFINITIONS.values())
