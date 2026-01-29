from __future__ import annotations

import uuid
from typing import Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.config_audit.db_models import ConfigAuditActor
from app.domain.feature_flag_audit import FeatureFlagAuditAction
from app.domain.feature_flag_audit import service as feature_flag_audit_service
from app.domain.feature_flags import FeatureFlagLifecycleState
from app.domain.feature_flags import service as feature_flag_service
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
    "dashboard.weather_traffic",
    "schedule.optimization_ai",
    "schedule.optimization",
    "quality.photo_evidence",
    "quality.nps",
    "finance.reports",
    "finance.cash_flow",
    "analytics.attribution_multitouch",
    "analytics.competitors",
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
    "integrations.accounting.quickbooks",
    "integrations.maps",
    "notifications.rules_builder",
    "leads.nurture",
    "leads.scoring",
]

FEATURE_KEYS = MODULE_KEYS + SUBFEATURE_KEYS

DEFAULT_DISABLED_KEYS = {
    "dashboard.weather_traffic",
    "training.library",
    "training.quizzes",
    "training.certs",
    "module.integrations",
    "module.leads",
    "quality.photo_evidence",
    "quality.nps",
    "integrations.google_calendar",
    "integrations.accounting.quickbooks",
    "integrations.maps",
    "notifications.rules_builder",
    "leads.nurture",
    "leads.scoring",
    "analytics.attribution_multitouch",
    "analytics.competitors",
    "schedule.optimization",
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
    session: AsyncSession,
    org_id: uuid.UUID,
    overrides: dict[str, bool],
    *,
    audit_actor: ConfigAuditActor,
    rollout_reason: str | None = None,
    allow_expired_override: bool = False,
    override_reason: str | None = None,
    request_id: str | None,
) -> OrgFeatureConfig:
    if allow_expired_override and not override_reason:
        raise ValueError("override_reason is required when allow_expired_override is true")
    record = await session.get(OrgFeatureConfig, org_id)
    before_overrides = normalize_feature_overrides(record.feature_overrides) if record else {}
    changed_keys = set(before_overrides.keys()) | set(overrides.keys())
    audits: list[tuple[str, dict | None, dict | None, FeatureFlagAuditAction, bool | None]] = []
    for key in sorted(changed_keys):
        before_override = before_overrides.get(key)
        after_override = overrides.get(key)
        if before_override == after_override:
            continue
        definition = await feature_flag_service.get_feature_flag_definition(session, key)
        if definition is None and before_override is None and after_override is not None:
            raise ValueError(f"Feature flag metadata is required for new flag '{key}'")
        if definition is not None:
            effective_state = feature_flag_service.resolve_effective_state(definition)
            if effective_state in {
                FeatureFlagLifecycleState.EXPIRED,
                FeatureFlagLifecycleState.RETIRED,
            }:
                if not allow_expired_override:
                    raise ValueError(
                        f"Feature flag '{key}' is {effective_state.value} and cannot be modified"
                    )
                before_state = snapshot_feature_flag_state(before_overrides, key)
                after_state = snapshot_feature_flag_state(overrides, key)
                await feature_flag_audit_service.audit_feature_flag_change(
                    session,
                    actor=audit_actor,
                    org_id=org_id,
                    flag_key=key,
                    action=FeatureFlagAuditAction.OVERRIDE,
                    before_state=before_state,
                    after_state=after_state,
                    rollout_context=feature_flag_audit_service.build_rollout_context(
                        enabled=after_state["enabled"],
                        targeting_rules=after_state.get("targeting_rules"),
                        reason=override_reason,
                    ),
                    request_id=request_id,
                )
        before_state = snapshot_feature_flag_state(before_overrides, key)
        after_state = snapshot_feature_flag_state(overrides, key)
        action = _derive_feature_flag_action(
            before_state=before_state,
            after_state=after_state,
            before_override=before_override,
            after_override=after_override,
        )
        audits.append((key, before_state, after_state, action, after_override))
    if record:
        record.feature_overrides = overrides
    else:
        record = OrgFeatureConfig(org_id=org_id, feature_overrides=overrides)
        session.add(record)
    await session.flush()
    for key, before_state, after_state, action, after_override in audits:
        enabled_value = after_override if after_override is not None else after_state["enabled"]
        if action == FeatureFlagAuditAction.ENABLE:
            enabled_value = True
        elif action == FeatureFlagAuditAction.DISABLE:
            enabled_value = False
        rollout_context = feature_flag_audit_service.build_rollout_context(
            enabled=enabled_value,
            targeting_rules=after_state.get("targeting_rules"),
            reason=rollout_reason,
        )
        await feature_flag_audit_service.audit_feature_flag_change(
            session,
            actor=audit_actor,
            org_id=org_id,
            flag_key=key,
            action=action,
            before_state=before_state,
            after_state=after_state,
            rollout_context=rollout_context,
            request_id=request_id,
        )
    return record


def snapshot_feature_flag_state(overrides: dict[str, bool], key: str) -> dict[str, object]:
    default_value = default_feature_value(key)
    override = overrides.get(key)
    enabled = effective_feature_enabled_from_overrides(overrides, key)
    return {
        "key": key,
        "enabled": enabled,
        "percentage": 100 if enabled else 0,
        "default": default_value,
        "override": override,
        "targeting_rules": [],
    }


def _derive_feature_flag_action(
    *,
    before_state: dict[str, object] | None,
    after_state: dict[str, object] | None,
    before_override: bool | None,
    after_override: bool | None,
) -> FeatureFlagAuditAction:
    if before_state and after_state:
        before_enabled = bool(before_state.get("enabled"))
        after_enabled = bool(after_state.get("enabled"))
        if before_enabled != after_enabled:
            return FeatureFlagAuditAction.ENABLE if after_enabled else FeatureFlagAuditAction.DISABLE
        if before_state.get("percentage") != after_state.get("percentage"):
            return FeatureFlagAuditAction.ROLLOUT_CHANGE
    if before_override is None and after_override is not None:
        return FeatureFlagAuditAction.CREATE
    if before_override is not None and after_override is None:
        return FeatureFlagAuditAction.DELETE
    return FeatureFlagAuditAction.UPDATE


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
    enabled = effective_feature_enabled_from_overrides(overrides, key)
    definition = await feature_flag_service.get_feature_flag_definition(session, key)
    if definition is not None:
        await feature_flag_service.record_feature_flag_evaluation(session, key)
    if definition and not feature_flag_service.is_flag_mutable(definition):
        return False
    return enabled


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
    await feature_flag_service.record_feature_flag_evaluation(session, key)
    return effective_visible(role=role, hidden_keys=hidden_keys, overrides=overrides, key=key)
