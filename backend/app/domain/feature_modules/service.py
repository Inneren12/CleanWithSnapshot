from __future__ import annotations

import uuid
from typing import Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feature_modules.db_models import OrgFeatureConfig, UserUiPreference
from app.domain.iam import permissions as iam_permissions

MODULE_KEYS = [
    "module.dashboard",
    "module.schedule",
    "module.invoices",
    "module.quality",
    "module.teams",
    "module.analytics",
    "module.finance",
    "module.pricing",
    "module.marketing",
    "module.leads",
    "module.inventory",
    "module.training",
    "module.notifications_center",
    "module.settings",
    "module.integrations",
    "module.api",
]

SUBFEATURE_KEYS = [
    "dashboard.weather",
    "schedule.optimization_ai",
    "finance.reports",
    "finance.cash_flow",
    "pricing.service_types",
    "pricing.booking_policies",
    "marketing.analytics",
    "marketing.email_campaigns",
    "marketing.email_segments",
    "inventory.usage_analytics",
    "training.library",
    "training.quizzes",
    "training.certs",
    "api.settings",
    "integrations.google_calendar",
]

FEATURE_KEYS = MODULE_KEYS + SUBFEATURE_KEYS

DEFAULT_DISABLED_KEYS = {
    "training.library",
    "training.quizzes",
    "training.certs",
    "module.integrations",
    "integrations.google_calendar",
}

MODULE_PERMISSIONS: dict[str, str] = {
    "dashboard": "core.view",
    "schedule": "bookings.view",
    "invoices": "invoices.view",
    "quality": "quality.view",
    "teams": "users.manage",
    "analytics": "finance.view",
    "finance": "finance.view",
    "pricing": "settings.manage",
    "marketing": "settings.manage",
    "leads": "contacts.view",
    "inventory": "core.view",
    "training": "core.view",
    "notifications_center": "core.view",
    "settings": "settings.manage",
    "integrations": "core.view",
    "api": "settings.manage",
}


def module_base_for_key(key: str) -> str:
    cleaned = key.strip()
    if cleaned.startswith("module."):
        return cleaned.split(".", 1)[1]
    return cleaned.split(".", 1)[0]


def module_key_for_base(base: str) -> str:
    return f"module.{base}"


def normalize_feature_overrides(overrides: dict[str, bool]) -> dict[str, bool]:
    normalized: dict[str, bool] = {}
    for raw_key, raw_value in (overrides or {}).items():
        if not raw_key:
            continue
        key = str(raw_key).strip()
        if not key:
            continue
        normalized[key] = bool(raw_value)
    return normalized


def normalize_hidden_keys(keys: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_key in keys or []:
        key = str(raw_key).strip()
        if not key or key in seen:
            continue
        normalized.append(key)
        seen.add(key)
    return normalized


def default_feature_value(key: str) -> bool:
    return key not in DEFAULT_DISABLED_KEYS


def default_feature_map(keys: Iterable[str] | None = None) -> dict[str, bool]:
    return {key: default_feature_value(key) for key in (keys or FEATURE_KEYS)}


def effective_feature_enabled_from_overrides(overrides: dict[str, bool], key: str) -> bool:
    normalized_key = key.strip()
    base = module_base_for_key(normalized_key)
    module_key = module_key_for_base(base)
    module_override = overrides.get(module_key)
    default_value = default_feature_value(normalized_key)
    if module_override is False:
        return False
    if normalized_key in overrides:
        return bool(overrides[normalized_key])
    if module_override is True:
        return default_value
    return default_value


def resolve_effective_features(
    overrides: dict[str, bool], keys: Iterable[str] | None = None
) -> dict[str, bool]:
    effective: dict[str, bool] = {}
    for key in keys or FEATURE_KEYS:
        effective[key] = effective_feature_enabled_from_overrides(overrides, key)
    return effective


def required_permission_for_key(key: str) -> str:
    base = module_base_for_key(key)
    return MODULE_PERMISSIONS.get(base, "core.view")


def role_allows_key(role: str | None, key: str) -> bool:
    if not role:
        return False
    permissions = iam_permissions.permissions_for_role(role)
    required = required_permission_for_key(key)
    return required in permissions


def is_key_hidden(hidden_keys: Iterable[str], key: str) -> bool:
    normalized = key.strip()
    base = module_base_for_key(normalized)
    module_key = module_key_for_base(base)
    hidden = {entry.strip() for entry in hidden_keys or [] if entry}
    return normalized in hidden or module_key in hidden


def effective_visible(
    *,
    role: str | None,
    hidden_keys: Iterable[str],
    overrides: dict[str, bool],
    key: str,
) -> bool:
    if not role_allows_key(role, key):
        return False
    if is_key_hidden(hidden_keys, key):
        return False
    return effective_feature_enabled_from_overrides(overrides, key)


async def get_org_feature_overrides(
    session: AsyncSession, org_id: uuid.UUID
) -> dict[str, bool]:
    record = await session.get(OrgFeatureConfig, org_id)
    if not record or not record.feature_overrides:
        return {}
    if isinstance(record.feature_overrides, dict):
        return normalize_feature_overrides(record.feature_overrides)
    return {}


async def upsert_org_feature_overrides(
    session: AsyncSession, org_id: uuid.UUID, overrides: dict[str, bool]
) -> OrgFeatureConfig:
    record = await session.get(OrgFeatureConfig, org_id)
    if record:
        record.feature_overrides = overrides
    else:
        record = OrgFeatureConfig(org_id=org_id, feature_overrides=overrides)
        session.add(record)
    await session.flush()
    return record


async def get_user_ui_prefs(
    session: AsyncSession, org_id: uuid.UUID, user_key: str
) -> list[str]:
    record = await session.scalar(
        sa.select(UserUiPreference).where(
            UserUiPreference.org_id == org_id,
            UserUiPreference.user_key == user_key,
        )
    )
    if not record:
        return []
    if isinstance(record.hidden_keys, list):
        return normalize_hidden_keys(record.hidden_keys)
    return []


async def upsert_user_ui_prefs(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_key: str,
    hidden_keys: list[str],
) -> UserUiPreference:
    record = await session.scalar(
        sa.select(UserUiPreference).where(
            UserUiPreference.org_id == org_id,
            UserUiPreference.user_key == user_key,
        )
    )
    if record:
        record.hidden_keys = hidden_keys
    else:
        record = UserUiPreference(org_id=org_id, user_key=user_key, hidden_keys=hidden_keys)
        session.add(record)
    await session.flush()
    return record


async def effective_feature_enabled(
    session: AsyncSession, org_id: uuid.UUID, key: str
) -> bool:
    overrides = await get_org_feature_overrides(session, org_id)
    return effective_feature_enabled_from_overrides(overrides, key)


async def effective_visible_for_user(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    role: str | None,
    user_key: str,
    key: str,
) -> bool:
    overrides = await get_org_feature_overrides(session, org_id)
    hidden_keys = await get_user_ui_prefs(session, org_id, user_key)
    return effective_visible(role=role, hidden_keys=hidden_keys, overrides=overrides, key=key)
