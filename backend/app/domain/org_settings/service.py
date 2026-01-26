from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.config_audit import ConfigAuditAction, ConfigAuditActor, ConfigScope
from app.domain.config_audit import service as config_audit_service
from app.domain.org_settings.db_models import OrganizationSettings

DEFAULT_TIMEZONE = "America/Edmonton"
DEFAULT_CURRENCY = "CAD"
DEFAULT_LANGUAGE = "en"
DEFAULT_REFERRAL_CREDIT_TRIGGER = "booking_confirmed"

DEFAULT_BUSINESS_HOURS: dict[str, dict[str, str | bool]] = {
    "monday": {"enabled": True, "start": "08:00", "end": "18:00"},
    "tuesday": {"enabled": True, "start": "08:00", "end": "18:00"},
    "wednesday": {"enabled": True, "start": "08:00", "end": "18:00"},
    "thursday": {"enabled": True, "start": "08:00", "end": "18:00"},
    "friday": {"enabled": True, "start": "08:00", "end": "18:00"},
    "saturday": {"enabled": True, "start": "09:00", "end": "17:00"},
    "sunday": {"enabled": False, "start": "", "end": ""},
}

DEFAULT_HOLIDAYS = [
    "new_years_day",
    "family_day",
    "good_friday",
    "victoria_day",
    "canada_day",
    "labour_day",
    "thanksgiving",
    "remembrance_day",
    "christmas_day",
    "boxing_day",
]


async def get_or_create_org_settings(
    session: AsyncSession, org_id: uuid.UUID
) -> OrganizationSettings:
    record = await session.get(OrganizationSettings, org_id)
    if record:
        return record
    record = OrganizationSettings(
        org_id=org_id,
        timezone=DEFAULT_TIMEZONE,
        currency=DEFAULT_CURRENCY,
        language=DEFAULT_LANGUAGE,
        business_hours=DEFAULT_BUSINESS_HOURS,
        holidays=DEFAULT_HOLIDAYS,
        branding={},
        referral_credit_trigger=DEFAULT_REFERRAL_CREDIT_TRIGGER,
        finance_ready=False,
        storage_bytes_used=0,
    )
    session.add(record)
    await session.flush()
    return record


def resolve_timezone(record: OrganizationSettings) -> str:
    return record.timezone or DEFAULT_TIMEZONE


def resolve_currency(record: OrganizationSettings) -> str:
    return record.currency or DEFAULT_CURRENCY


def resolve_language(record: OrganizationSettings) -> str:
    return record.language or DEFAULT_LANGUAGE


def resolve_business_hours(record: OrganizationSettings) -> dict:
    if isinstance(record.business_hours, dict) and record.business_hours:
        return record.business_hours
    return DEFAULT_BUSINESS_HOURS


def resolve_holidays(record: OrganizationSettings) -> list[str]:
    if isinstance(record.holidays, list) and record.holidays:
        return record.holidays
    return DEFAULT_HOLIDAYS


def resolve_branding(record: OrganizationSettings) -> dict:
    if isinstance(record.branding, dict) and record.branding:
        return record.branding
    return {}


def resolve_referral_credit_trigger(record: OrganizationSettings) -> str:
    value = getattr(record, "referral_credit_trigger", None)
    return value or DEFAULT_REFERRAL_CREDIT_TRIGGER


def resolve_finance_ready(record: OrganizationSettings) -> bool:
    return bool(getattr(record, "finance_ready", False))


def resolve_data_export_request_rate_limit_per_minute(
    record: OrganizationSettings,
    fallback: int,
) -> int:
    value = getattr(record, "data_export_request_rate_limit_per_minute", None)
    return value if value is not None else fallback


def resolve_data_export_request_rate_limit_per_hour(
    record: OrganizationSettings,
    fallback: int,
) -> int:
    value = getattr(record, "data_export_request_rate_limit_per_hour", None)
    return value if value is not None else fallback


def resolve_data_export_download_rate_limit_per_minute(
    record: OrganizationSettings,
    fallback: int,
) -> int:
    value = getattr(record, "data_export_download_rate_limit_per_minute", None)
    return value if value is not None else fallback


def resolve_data_export_download_failure_limit_per_window(
    record: OrganizationSettings,
    fallback: int,
) -> int:
    value = getattr(record, "data_export_download_failure_limit_per_window", None)
    return value if value is not None else fallback


def resolve_data_export_download_lockout_limit_per_window(
    record: OrganizationSettings,
    fallback: int,
) -> int:
    value = getattr(record, "data_export_download_lockout_limit_per_window", None)
    return value if value is not None else fallback


def resolve_data_export_cooldown_minutes(
    record: OrganizationSettings,
    fallback: int,
) -> int:
    value = getattr(record, "data_export_cooldown_minutes", None)
    return value if value is not None else fallback


async def apply_org_settings_update(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    payload,
    audit_actor: ConfigAuditActor,
    request_id: str | None,
) -> OrganizationSettings:
    record = await get_or_create_org_settings(session, org_id)
    before_snapshot = snapshot_org_settings(record)
    if payload.timezone is not None:
        record.timezone = payload.timezone
    if payload.currency is not None:
        record.currency = payload.currency
    if payload.language is not None:
        record.language = payload.language
    if payload.business_hours is not None:
        normalized_hours: dict[str, dict] = {}
        for key, value in payload.business_hours.items():
            if hasattr(value, "model_dump"):
                normalized_hours[key] = value.model_dump()
            else:
                normalized_hours[key] = dict(value)
        record.business_hours = normalized_hours
    if payload.holidays is not None:
        record.holidays = payload.holidays
    if payload.legal_name is not None:
        record.legal_name = payload.legal_name
    if payload.legal_bn is not None:
        record.legal_bn = payload.legal_bn
    if payload.legal_gst_hst is not None:
        record.legal_gst_hst = payload.legal_gst_hst
    if payload.legal_address is not None:
        record.legal_address = payload.legal_address
    if payload.legal_phone is not None:
        record.legal_phone = payload.legal_phone
    if payload.legal_email is not None:
        record.legal_email = payload.legal_email
    if payload.legal_website is not None:
        record.legal_website = payload.legal_website
    if payload.branding is not None:
        record.branding = payload.branding
    if getattr(payload, "referral_credit_trigger", None) is not None:
        record.referral_credit_trigger = payload.referral_credit_trigger
    if getattr(payload, "finance_ready", None) is not None:
        record.finance_ready = payload.finance_ready
    if "max_users" in getattr(payload, "model_fields_set", set()):
        record.max_users = payload.max_users
    if "max_storage_bytes" in getattr(payload, "model_fields_set", set()):
        record.max_storage_bytes = payload.max_storage_bytes
    if "data_export_request_rate_limit_per_minute" in getattr(payload, "model_fields_set", set()):
        record.data_export_request_rate_limit_per_minute = payload.data_export_request_rate_limit_per_minute
    if "data_export_request_rate_limit_per_hour" in getattr(payload, "model_fields_set", set()):
        record.data_export_request_rate_limit_per_hour = payload.data_export_request_rate_limit_per_hour
    if "data_export_download_rate_limit_per_minute" in getattr(payload, "model_fields_set", set()):
        record.data_export_download_rate_limit_per_minute = payload.data_export_download_rate_limit_per_minute
    if "data_export_download_failure_limit_per_window" in getattr(payload, "model_fields_set", set()):
        record.data_export_download_failure_limit_per_window = (
            payload.data_export_download_failure_limit_per_window
        )
    if "data_export_download_lockout_limit_per_window" in getattr(payload, "model_fields_set", set()):
        record.data_export_download_lockout_limit_per_window = (
            payload.data_export_download_lockout_limit_per_window
        )
    if "data_export_cooldown_minutes" in getattr(payload, "model_fields_set", set()):
        record.data_export_cooldown_minutes = payload.data_export_cooldown_minutes
    await session.flush()
    after_snapshot = snapshot_org_settings(record)
    await config_audit_service.record_config_change(
        session,
        actor=audit_actor,
        org_id=org_id,
        config_scope=ConfigScope.ORG_SETTINGS,
        config_key="org_settings",
        action=ConfigAuditAction.UPDATE,
        before_value=before_snapshot,
        after_value=after_snapshot,
        request_id=request_id,
    )
    return record


def snapshot_org_settings(record: OrganizationSettings) -> dict[str, object | None]:
    return {
        "timezone": record.timezone,
        "currency": record.currency,
        "language": record.language,
        "business_hours": record.business_hours,
        "holidays": record.holidays,
        "legal_name": record.legal_name,
        "legal_bn": record.legal_bn,
        "legal_gst_hst": record.legal_gst_hst,
        "legal_address": record.legal_address,
        "legal_phone": record.legal_phone,
        "legal_email": record.legal_email,
        "legal_website": record.legal_website,
        "branding": record.branding,
        "referral_credit_trigger": record.referral_credit_trigger,
        "finance_ready": record.finance_ready,
        "max_users": record.max_users,
        "max_storage_bytes": record.max_storage_bytes,
        "storage_bytes_used": record.storage_bytes_used,
        "data_export_request_rate_limit_per_minute": record.data_export_request_rate_limit_per_minute,
        "data_export_request_rate_limit_per_hour": record.data_export_request_rate_limit_per_hour,
        "data_export_download_rate_limit_per_minute": record.data_export_download_rate_limit_per_minute,
        "data_export_download_failure_limit_per_window": record.data_export_download_failure_limit_per_window,
        "data_export_download_lockout_limit_per_window": record.data_export_download_lockout_limit_per_window,
        "data_export_cooldown_minutes": record.data_export_cooldown_minutes,
    }
