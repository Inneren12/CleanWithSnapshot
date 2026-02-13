"""
Import all ORM model modules so SQLAlchemy can resolve relationship("WorkTimeEntry") etc.
Used by jobs process which doesn't import the full API router graph.
"""

from __future__ import annotations

import importlib

_DOMAINS: tuple[str, ...] = (
    "access_review",
    "addons",
    "admin_audit",
    "admin_idempotency",
    "analytics",
    "audit_retention",
    "bookings",
    "break_glass",
    "chat_threads",
    "checklists",
    "clients",
    "config_audit",
    "data_rights",
    "dispatcher",
    "disputes",
    "documents",
    "export_events",
    "feature_flag_audit",
    "feature_flags",
    "feature_modules",
    "finance",
    "iam",
    "integration_audit",
    "integrations",
    "inventory",
    "invoices",
    "leads",
    "leads_nurture",
    "leads_scoring",
    "marketing",
    "message_templates",
    "notifications",
    "notifications_center",
    "notifications_digests",
    "nps",
    "ops",
    "org_settings",
    "outbox",
    "policy_overrides",
    "pricing_settings",
    "quality",
    "reason_logs",
    "rules",
    "saas",
    "storage_quota",
    "subscriptions",
    "time_tracking",
    "training",
    "workers",
)

def import_all_db_models() -> None:
    for domain in _DOMAINS:
        importlib.import_module(f"app.domain.{domain}.db_models")

import_all_db_models()
