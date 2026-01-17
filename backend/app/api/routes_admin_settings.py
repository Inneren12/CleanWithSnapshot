from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminPermission, AdminRole, require_permissions, require_viewer
from app.api.org_context import require_org_context
from app.domain.feature_modules import schemas as feature_schemas
from app.domain.feature_modules import service as feature_service
from app.domain.integrations import schemas as integrations_schemas
from app.domain.invoices.db_models import StripeEvent
from app.domain.org_settings import schemas as org_settings_schemas
from app.domain.org_settings import service as org_settings_service
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
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> feature_schemas.FeatureConfigResponse:
    overrides = feature_service.normalize_feature_overrides(payload.overrides)
    await feature_service.upsert_org_feature_overrides(session, org_id, overrides)
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
    )


@router.patch(
    "/v1/admin/settings/org",
    response_model=org_settings_schemas.OrgSettingsResponse,
    status_code=status.HTTP_200_OK,
)
async def update_org_settings(
    payload: org_settings_schemas.OrgSettingsUpdateRequest,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> org_settings_schemas.OrgSettingsResponse:
    record = await org_settings_service.apply_org_settings_update(session, org_id, payload=payload)
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
