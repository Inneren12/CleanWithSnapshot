from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminPermission, AdminRole, require_permissions, require_viewer
from app.api.break_glass import BREAK_GLASS_HEADER
from app.api.org_context import require_org_context
from app.domain.config_audit import ConfigAuditAction, ConfigActorType, ConfigScope
from app.domain.config_audit import schemas as config_audit_schemas
from app.domain.config_audit import service as config_audit_service
from app.domain.feature_flag_audit import schemas as feature_flag_audit_schemas
from app.domain.feature_flag_audit import service as feature_flag_audit_service
from app.domain.feature_flag_audit.db_models import FeatureFlagAuditAction
from app.domain.feature_flags import schemas as feature_flag_schemas
from app.domain.feature_flags import service as feature_flag_service
from app.domain.feature_modules import schemas as feature_schemas
from app.domain.feature_modules import service as feature_service
from app.domain.integrations import schemas as integrations_schemas
from app.domain.invoices.db_models import StripeEvent
from app.domain.org_settings import schemas as org_settings_schemas
from app.domain.org_settings import service as org_settings_service
from app.domain.saas import service as saas_service
from app.domain.storage_quota import service as storage_quota_service
from app.infra.db import get_db_session
from app.settings import settings
from app.shared.pii_masking import mask_email, mask_phone

router = APIRouter(tags=["admin-settings"])


async def require_owner(
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
) -> AdminIdentity:
    if identity.role != AdminRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


def _resolve_user_key(request: Request, identity: AdminIdentity) -> str:
    saas_identity = getattr(request.state, "saas_identity", None)
    if saas_identity and getattr(saas_identity, "user_id", None):
        return f"saas:{saas_identity.user_id}"
    return f"basic:{identity.username}"


def _resolve_auth_method(request: Request) -> str:
    if getattr(request.state, "break_glass", False) or request.headers.get(BREAK_GLASS_HEADER):
        return "break_glass"
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return "token"
    return "basic"


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid timestamp") from exc


def _mask_secret(value: str | None, *, prefix: int = 2, suffix: int = 2) -> str | None:
    if not value:
        return None
    if prefix + suffix >= len(value):
        return "*" * len(value)
    return f"{value[:prefix]}***{value[-suffix:]}"


def _stripe_health(connected: bool, webhook_configured: bool) -> str:
    if connected and webhook_configured:
        return "connected"
    if connected:
        return "needs_webhook"
    return "missing_configuration"


def _twilio_health(connected: bool) -> str:
    return "connected" if connected else "missing_configuration"


def _email_health(connected: bool) -> str:
    return "connected" if connected else "missing_configuration"


def _usage_percent(used_bytes: int, max_bytes: int | None) -> float | None:
    if max_bytes is None or max_bytes <= 0:
        return None
    return round((used_bytes / max_bytes) * 100, 2)


@router.get(
    "/v1/admin/settings/features",
    response_model=feature_schemas.FeatureConfigResponse,
    status_code=status.HTTP_200_OK,
)
async def get_feature_config(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> feature_schemas.FeatureConfigResponse:
    overrides = await feature_service.get_org_feature_overrides(session, org_id)
    defaults = feature_service.default_feature_map()
    effective = feature_service.resolve_effective_features(overrides)
    return feature_schemas.FeatureConfigResponse(
        org_id=org_id,
        overrides=overrides,
        defaults=defaults,
        effective=effective,
        keys=feature_service.FEATURE_KEYS,
    )


@router.patch(
    "/v1/admin/settings/features",
    response_model=feature_schemas.FeatureConfigResponse,
    status_code=status.HTTP_200_OK,
)
async def update_feature_config(
    payload: feature_schemas.FeatureConfigUpdateRequest,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> feature_schemas.FeatureConfigResponse:
    overrides = feature_service.normalize_feature_overrides(payload.overrides)
    try:
        await feature_service.upsert_org_feature_overrides(
            session,
            org_id,
            overrides,
            audit_actor=config_audit_service.admin_actor(identity, auth_method=_resolve_auth_method(request)),
            rollout_reason=payload.reason,
            allow_expired_override=payload.allow_expired_override,
            override_reason=payload.override_reason,
            request_id=getattr(request.state, "request_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    defaults = feature_service.default_feature_map()
    effective = feature_service.resolve_effective_features(overrides)
    return feature_schemas.FeatureConfigResponse(
        org_id=org_id,
        overrides=overrides,
        defaults=defaults,
        effective=effective,
        keys=feature_service.FEATURE_KEYS,
    )


@router.get(
    "/v1/admin/settings/feature-flags",
    response_model=feature_flag_schemas.FeatureFlagDefinitionListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_feature_flag_definitions(
    state: feature_flag_schemas.FeatureFlagLifecycleState | None = Query(default=None),
    expiring_within_days: int | None = Query(default=None, ge=1),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> feature_flag_schemas.FeatureFlagDefinitionListResponse:
    records = await feature_flag_service.list_feature_flag_definitions(
        session,
        state=state,
        expiring_within_days=expiring_within_days,
    )
    items = [
        feature_flag_schemas.FeatureFlagDefinitionBase(
            key=record.key,
            owner=record.owner,
            purpose=record.purpose,
            created_at=record.created_at,
            expires_at=record.expires_at,
            lifecycle_state=feature_flag_schemas.FeatureFlagLifecycleState(record.lifecycle_state),
            effective_state=feature_flag_service.resolve_effective_state(record),
        )
        for record in records
    ]
    return feature_flag_schemas.FeatureFlagDefinitionListResponse(items=items)


@router.post(
    "/v1/admin/settings/feature-flags",
    response_model=feature_flag_schemas.FeatureFlagDefinitionBase,
    status_code=status.HTTP_201_CREATED,
)
async def create_feature_flag_definition(
    payload: feature_flag_schemas.FeatureFlagDefinitionCreateRequest,
    request: Request,
    identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> feature_flag_schemas.FeatureFlagDefinitionBase:
    record = await feature_flag_service.create_feature_flag_definition(
        session,
        payload=payload,
        actor=config_audit_service.admin_actor(identity, auth_method=_resolve_auth_method(request)),
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return feature_flag_schemas.FeatureFlagDefinitionBase(
        key=record.key,
        owner=record.owner,
        purpose=record.purpose,
        created_at=record.created_at,
        expires_at=record.expires_at,
        lifecycle_state=feature_flag_schemas.FeatureFlagLifecycleState(record.lifecycle_state),
        effective_state=feature_flag_service.resolve_effective_state(record),
    )


@router.patch(
    "/v1/admin/settings/feature-flags/{flag_key}",
    response_model=feature_flag_schemas.FeatureFlagDefinitionBase,
    status_code=status.HTTP_200_OK,
)
async def update_feature_flag_definition(
    flag_key: str,
    payload: feature_flag_schemas.FeatureFlagDefinitionUpdateRequest,
    request: Request,
    identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> feature_flag_schemas.FeatureFlagDefinitionBase:
    record = await feature_flag_service.get_feature_flag_definition(session, flag_key)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found")
    record = await feature_flag_service.update_feature_flag_definition(
        session,
        record=record,
        payload=payload,
        actor=config_audit_service.admin_actor(identity, auth_method=_resolve_auth_method(request)),
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return feature_flag_schemas.FeatureFlagDefinitionBase(
        key=record.key,
        owner=record.owner,
        purpose=record.purpose,
        created_at=record.created_at,
        expires_at=record.expires_at,
        lifecycle_state=feature_flag_schemas.FeatureFlagLifecycleState(record.lifecycle_state),
        effective_state=feature_flag_service.resolve_effective_state(record),
    )


@router.get(
    "/v1/admin/settings/org",
    response_model=org_settings_schemas.OrgSettingsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_org_settings(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> org_settings_schemas.OrgSettingsResponse:
    record = await org_settings_service.get_or_create_org_settings(session, org_id)
    quota_snapshot = await saas_service.get_org_user_quota_snapshot(session, org_id)
    storage_snapshot = await storage_quota_service.get_org_storage_quota_snapshot(session, org_id)
    return org_settings_schemas.OrgSettingsResponse(
        org_id=org_id,
        timezone=org_settings_service.resolve_timezone(record),
        currency=org_settings_service.resolve_currency(record),
        language=org_settings_service.resolve_language(record),
        business_hours=org_settings_service.resolve_business_hours(record),
        holidays=org_settings_service.resolve_holidays(record),
        legal_name=record.legal_name,
        legal_bn=record.legal_bn,
        legal_gst_hst=record.legal_gst_hst,
        legal_address=record.legal_address,
        legal_phone=record.legal_phone,
        legal_email=record.legal_email,
        legal_website=record.legal_website,
        branding=org_settings_service.resolve_branding(record),
        referral_credit_trigger=org_settings_service.resolve_referral_credit_trigger(record),
        finance_ready=org_settings_service.resolve_finance_ready(record),
        max_users=record.max_users,
        current_users_count=quota_snapshot.current_users_count,
        max_storage_bytes=storage_snapshot.max_storage_bytes,
        storage_bytes_used=storage_snapshot.storage_bytes_used,
        storage_usage_percent=_usage_percent(storage_snapshot.storage_bytes_used, storage_snapshot.max_storage_bytes),
    )


@router.patch(
    "/v1/admin/settings/org",
    response_model=org_settings_schemas.OrgSettingsResponse,
    status_code=status.HTTP_200_OK,
)
async def update_org_settings(
    payload: org_settings_schemas.OrgSettingsUpdateRequest,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> org_settings_schemas.OrgSettingsResponse:
    record = await org_settings_service.apply_org_settings_update(
        session,
        org_id,
        payload=payload,
        audit_actor=config_audit_service.admin_actor(identity, auth_method=_resolve_auth_method(request)),
        request_id=getattr(request.state, "request_id", None),
    )
    quota_snapshot = await saas_service.get_org_user_quota_snapshot(session, org_id)
    storage_snapshot = await storage_quota_service.get_org_storage_quota_snapshot(session, org_id)
    await session.commit()
    return org_settings_schemas.OrgSettingsResponse(
        org_id=org_id,
        timezone=org_settings_service.resolve_timezone(record),
        currency=org_settings_service.resolve_currency(record),
        language=org_settings_service.resolve_language(record),
        business_hours=org_settings_service.resolve_business_hours(record),
        holidays=org_settings_service.resolve_holidays(record),
        legal_name=record.legal_name,
        legal_bn=record.legal_bn,
        legal_gst_hst=record.legal_gst_hst,
        legal_address=record.legal_address,
        legal_phone=record.legal_phone,
        legal_email=record.legal_email,
        legal_website=record.legal_website,
        branding=org_settings_service.resolve_branding(record),
        referral_credit_trigger=org_settings_service.resolve_referral_credit_trigger(record),
        finance_ready=org_settings_service.resolve_finance_ready(record),
        max_users=record.max_users,
        current_users_count=quota_snapshot.current_users_count,
        max_storage_bytes=storage_snapshot.max_storage_bytes,
        storage_bytes_used=storage_snapshot.storage_bytes_used,
        storage_usage_percent=_usage_percent(storage_snapshot.storage_bytes_used, storage_snapshot.max_storage_bytes),
    )


@router.get(
    "/v1/admin/settings/audit/config",
    response_model=config_audit_schemas.ConfigAuditLogListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_config_audit_logs(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
    org_id_filter: uuid.UUID | None = Query(None, alias="org_id"),
    config_scope: ConfigScope | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> config_audit_schemas.ConfigAuditLogListResponse:
    if org_id_filter is not None and org_id_filter != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    resolved_limit = max(1, min(limit, 200))
    resolved_offset = max(0, offset)
    start_ts = _parse_iso_timestamp(start)
    end_ts = _parse_iso_timestamp(end)
    logs = await config_audit_service.list_config_audit_logs(
        session,
        org_id=org_id_filter or org_id,
        config_scope=config_scope,
        from_ts=start_ts,
        to_ts=end_ts,
        limit=resolved_limit,
        offset=resolved_offset,
    )
    items = [
        config_audit_schemas.ConfigAuditLogEntry(
            audit_id=log.audit_id,
            occurred_at=log.occurred_at,
            actor_type=ConfigActorType(log.actor_type),
            actor_id=log.actor_id,
            actor_role=log.actor_role,
            auth_method=log.auth_method,
            actor_source=log.actor_source,
            org_id=log.org_id,
            config_scope=ConfigScope(log.config_scope),
            config_key=log.config_key,
            action=ConfigAuditAction(log.action),
            before_value=log.before_value,
            after_value=log.after_value,
            request_id=log.request_id,
        )
        for log in logs
    ]
    next_offset = resolved_offset + resolved_limit if len(items) == resolved_limit else None
    return config_audit_schemas.ConfigAuditLogListResponse(
        items=items,
        limit=resolved_limit,
        offset=resolved_offset,
        next_offset=next_offset,
    )


@router.get(
    "/v1/admin/settings/audit/feature-flags",
    response_model=feature_flag_audit_schemas.FeatureFlagAuditLogListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_feature_flag_audit_logs(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
    session: AsyncSession = Depends(get_db_session),
    org_id_filter: uuid.UUID | None = Query(None, alias="org_id"),
    flag_key: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> feature_flag_audit_schemas.FeatureFlagAuditLogListResponse:
    if org_id_filter is not None and org_id_filter != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    resolved_limit = max(1, min(limit, 200))
    resolved_offset = max(0, offset)
    start_ts = _parse_iso_timestamp(start)
    end_ts = _parse_iso_timestamp(end)
    logs = await feature_flag_audit_service.list_feature_flag_audit_logs(
        session,
        org_id=org_id_filter or org_id,
        flag_key=flag_key,
        from_ts=start_ts,
        to_ts=end_ts,
        limit=resolved_limit,
        offset=resolved_offset,
    )
    items = [
        feature_flag_audit_schemas.FeatureFlagAuditLogEntry(
            audit_id=log.audit_id,
            occurred_at=log.occurred_at,
            actor_type=ConfigActorType(log.actor_type),
            actor_id=log.actor_id,
            actor_role=log.actor_role,
            auth_method=log.auth_method,
            actor_source=log.actor_source,
            org_id=log.org_id,
            flag_key=log.flag_key,
            action=FeatureFlagAuditAction(log.action),
            before_state=log.before_state,
            after_state=log.after_state,
            rollout_context=log.rollout_context,
            request_id=log.request_id,
        )
        for log in logs
    ]
    next_offset = resolved_offset + resolved_limit if len(items) == resolved_limit else None
    return feature_flag_audit_schemas.FeatureFlagAuditLogListResponse(
        items=items,
        limit=resolved_limit,
        offset=resolved_offset,
        next_offset=next_offset,
    )


@router.get(
    "/v1/admin/users/me/ui_prefs",
    response_model=feature_schemas.UiPrefsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_ui_prefs(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> feature_schemas.UiPrefsResponse:
    user_key = _resolve_user_key(request, identity)
    hidden_keys = await feature_service.get_user_ui_prefs(session, org_id, user_key)
    return feature_schemas.UiPrefsResponse(hidden_keys=hidden_keys)


@router.patch(
    "/v1/admin/users/me/ui_prefs",
    response_model=feature_schemas.UiPrefsResponse,
    status_code=status.HTTP_200_OK,
)
async def update_ui_prefs(
    payload: feature_schemas.UiPrefsUpdateRequest,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> feature_schemas.UiPrefsResponse:
    user_key = _resolve_user_key(request, identity)
    hidden_keys = feature_service.normalize_hidden_keys(payload.hidden_keys)
    await feature_service.upsert_user_ui_prefs(session, org_id, user_key, hidden_keys)
    await session.commit()
    return feature_schemas.UiPrefsResponse(hidden_keys=hidden_keys)


@router.get(
    "/v1/admin/settings/integrations",
    response_model=integrations_schemas.IntegrationsStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_integrations_status(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.IntegrationsStatusResponse:
    enabled = await feature_service.effective_feature_enabled(session, org_id, "module.integrations")
    if not enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Disabled by org settings")

    stripe_connected = bool(settings.stripe_secret_key)
    stripe_webhook_configured = bool(settings.stripe_webhook_secret)
    stripe_last_webhook = await session.scalar(
        select(StripeEvent.processed_at)
        .where(StripeEvent.org_id == org_id)
        .order_by(StripeEvent.processed_at.desc())
        .limit(1)
    )

    sms_configured = bool(
        settings.sms_mode == "twilio"
        and settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_sms_from
    )
    call_configured = bool(
        settings.call_mode == "twilio"
        and settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_call_from
        and settings.twilio_call_url
    )
    twilio_connected = sms_configured or call_configured

    email_sender = settings.email_sender
    sendgrid_configured = bool(settings.email_mode == "sendgrid" and settings.sendgrid_api_key and email_sender)
    smtp_configured = bool(settings.email_mode == "smtp" and settings.smtp_host and email_sender)
    email_connected = sendgrid_configured or smtp_configured

    return integrations_schemas.IntegrationsStatusResponse(
        stripe=integrations_schemas.StripeIntegrationStatus(
            connected=stripe_connected,
            account=_mask_secret(settings.stripe_secret_key, prefix=4, suffix=4),
            webhook_configured=stripe_webhook_configured,
            last_webhook_at=stripe_last_webhook,
            capabilities=integrations_schemas.StripeCapabilities(
                card=True if stripe_connected else None,
                apple_pay=None,
                google_pay=None,
            ),
            health=_stripe_health(stripe_connected, stripe_webhook_configured),
        ),
        twilio=integrations_schemas.TwilioIntegrationStatus(
            connected=twilio_connected,
            account=_mask_secret(settings.twilio_account_sid, prefix=2, suffix=4),
            sms_from=mask_phone(settings.twilio_sms_from),
            call_from=mask_phone(settings.twilio_call_from),
            usage_summary="Usage tracking not enabled",
            health=_twilio_health(twilio_connected),
        ),
        email=integrations_schemas.EmailIntegrationStatus(
            connected=email_connected,
            mode=settings.email_mode,
            sender=mask_email(email_sender),
            deliverability="Deliverability monitoring not enabled",
            health=_email_health(email_connected),
        ),
    )
