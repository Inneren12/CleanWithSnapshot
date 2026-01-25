from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminPermission, AdminRole, require_permissions, require_viewer
from app.api.break_glass import BREAK_GLASS_HEADER
from app.api.org_context import require_org_context
from app.api.problem_details import PROBLEM_TYPE_DOMAIN, PROBLEM_TYPE_RATE_LIMIT, problem_details
from app.domain.config_audit import service as config_audit_service
from app.domain.feature_modules import service as feature_service
from app.domain.integrations import gcal_service, maps_service, qbo_service, schemas as integrations_schemas
from app.infra.db import get_db_session
from app.settings import settings

router = APIRouter(tags=["admin-integrations"])


async def require_owner(
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
) -> AdminIdentity:
    if identity.role != AdminRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


def _resolve_auth_method(request: Request) -> str:
    if getattr(request.state, "break_glass", False) or request.headers.get(BREAK_GLASS_HEADER):
        return "break_glass"
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return "token"
    return "basic"


async def _require_google_calendar_enabled(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    module_enabled = await feature_service.effective_feature_enabled(session, org_id, "module.integrations")
    gcal_enabled = await feature_service.effective_feature_enabled(
        session, org_id, "integrations.google_calendar"
    )
    if not (module_enabled and gcal_enabled):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Disabled by org settings")


async def _require_quickbooks_enabled(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    module_enabled = await feature_service.effective_feature_enabled(session, org_id, "module.integrations")
    qbo_enabled = await feature_service.effective_feature_enabled(
        session, org_id, "integrations.accounting.quickbooks"
    )
    if not (module_enabled and qbo_enabled):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Disabled by org settings")


async def _require_maps_enabled(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    module_enabled = await feature_service.effective_feature_enabled(session, org_id, "module.integrations")
    maps_enabled = await feature_service.effective_feature_enabled(session, org_id, "integrations.maps")
    if not (module_enabled and maps_enabled):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Disabled by org settings")


@router.get(
    "/v1/admin/integrations/accounting/quickbooks/status",
    response_model=integrations_schemas.QboIntegrationStatus,
    status_code=status.HTTP_200_OK,
)
async def get_quickbooks_status(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.QboIntegrationStatus:
    await _require_quickbooks_enabled(session, org_id)
    account = await qbo_service.get_account(session, org_id)
    sync_state = await qbo_service.get_sync_state(session, org_id)
    return integrations_schemas.QboIntegrationStatus(
        connected=bool(account),
        realm_id=account.realm_id if account else None,
        oauth_configured=qbo_service.oauth_configured(),
        last_sync_at=sync_state.last_sync_at if sync_state else None,
        last_error=sync_state.last_error if sync_state else None,
    )


@router.post(
    "/v1/admin/integrations/accounting/quickbooks/connect/start",
    response_model=integrations_schemas.QboConnectStartResponse,
    status_code=status.HTTP_200_OK,
)
async def start_quickbooks_connect(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.QboConnectStartResponse:
    await _require_quickbooks_enabled(session, org_id)
    if not qbo_service.oauth_configured():
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks OAuth Not Configured",
            detail="Missing QuickBooks OAuth configuration.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    auth_url = qbo_service.build_auth_url(state=str(org_id))
    return integrations_schemas.QboConnectStartResponse(authorization_url=auth_url)


@router.post(
    "/v1/admin/integrations/accounting/quickbooks/connect/callback",
    response_model=integrations_schemas.QboConnectCallbackResponse,
    status_code=status.HTTP_200_OK,
)
async def finish_quickbooks_connect(
    payload: integrations_schemas.QboConnectCallbackRequest,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.QboConnectCallbackResponse:
    await _require_quickbooks_enabled(session, org_id)
    if not qbo_service.oauth_configured():
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks OAuth Not Configured",
            detail="Missing QuickBooks OAuth configuration.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    if payload.state and payload.state != str(org_id):
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks OAuth State Mismatch",
            detail="OAuth state does not match organization.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    try:
        refresh_token = await qbo_service.exchange_code_for_refresh_token(payload.code)
    except ValueError:
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks OAuth Exchange Failed",
            detail="Unable to exchange authorization code.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await qbo_service.upsert_account(
        session,
        org_id,
        refresh_token,
        payload.realm_id,
        audit_actor=config_audit_service.admin_actor(identity, auth_method=_resolve_auth_method(request)),
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return integrations_schemas.QboConnectCallbackResponse(
        connected=True,
        realm_id=payload.realm_id,
    )


@router.post(
    "/v1/admin/integrations/accounting/quickbooks/disconnect",
    response_model=integrations_schemas.QboConnectCallbackResponse,
    status_code=status.HTTP_200_OK,
)
async def disconnect_quickbooks(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.QboConnectCallbackResponse:
    await _require_quickbooks_enabled(session, org_id)
    await qbo_service.disconnect_quickbooks(
        session,
        org_id,
        audit_actor=config_audit_service.admin_actor(identity, auth_method=_resolve_auth_method(request)),
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return integrations_schemas.QboConnectCallbackResponse(connected=False, realm_id=None)


@router.post(
    "/v1/admin/maps/distance_matrix",
    response_model=integrations_schemas.MapsDistanceMatrixResponse,
    status_code=status.HTTP_200_OK,
)
async def get_maps_distance_matrix(
    payload: integrations_schemas.MapsDistanceMatrixRequest,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permissions(AdminPermission.DISPATCH)),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.MapsDistanceMatrixResponse:
    await _require_maps_enabled(session, org_id)
    if not payload.origins or not payload.destinations:
        return problem_details(
            request=request,
            status=400,
            title="Invalid Distance Matrix Request",
            detail="Origins and destinations are required.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    allowed = await maps_service.allow_maps_request(org_id)
    if not allowed:
        return problem_details(
            request=request,
            status=429,
            title="Maps Rate Limit Exceeded",
            detail="Map request limit exceeded for this organization.",
            type_=PROBLEM_TYPE_RATE_LIMIT,
        )
    origins = [(origin.lat, origin.lng) for origin in payload.origins]
    destinations = [(dest.lat, dest.lng) for dest in payload.destinations]
    result, cache_hit, quota_applied = await maps_service.fetch_distance_matrix(
        session=session,
        org_id=org_id,
        origins=origins,
        destinations=destinations,
        depart_at=payload.depart_at,
        mode=payload.mode,
    )
    if quota_applied:
        await session.commit()
    return integrations_schemas.MapsDistanceMatrixResponse(
        origins=payload.origins,
        destinations=payload.destinations,
        matrix=[
            [integrations_schemas.MapsDistanceMatrixElement(**entry.as_payload()) for entry in row]
            for row in result.matrix
        ],
        provider=result.provider,
        warning=result.warning,
        cache_hit=cache_hit,
        quota_applied=quota_applied,
        elements_count=len(origins) * len(destinations),
    )


@router.get(
    "/v1/admin/maps/quota",
    response_model=integrations_schemas.MapsQuotaResponse,
    status_code=status.HTTP_200_OK,
)
async def get_maps_quota(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.MapsQuotaResponse:
    await _require_maps_enabled(session, org_id)
    used = await maps_service.get_month_usage(session, org_id)
    limit = maps_service.get_month_limit()
    remaining = max(limit - used, 0) if limit else 0
    percent_used = round((used / limit) * 100, 2) if limit else None
    return integrations_schemas.MapsQuotaResponse(
        used=used,
        limit=limit,
        remaining=remaining,
        month=maps_service.get_month_label(),
        key_configured=bool(settings.google_maps_api_key),
        percent_used=percent_used,
    )


@router.post(
    "/v1/admin/maps/test_key",
    response_model=integrations_schemas.MapsKeyTestResponse,
    status_code=status.HTTP_200_OK,
)
async def test_maps_key(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.MapsKeyTestResponse:
    await _require_maps_enabled(session, org_id)
    valid, message = await maps_service.test_api_key()
    return integrations_schemas.MapsKeyTestResponse(
        key_configured=bool(settings.google_maps_api_key),
        valid=valid,
        message=message,
    )


@router.post(
    "/v1/admin/integrations/accounting/quickbooks/push",
    response_model=integrations_schemas.QboInvoicePushResponse,
    status_code=status.HTTP_200_OK,
)
async def push_quickbooks_invoices(
    request: Request,
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permissions(AdminPermission.FINANCE)),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.QboInvoicePushResponse:
    await _require_quickbooks_enabled(session, org_id)
    if not qbo_service.oauth_configured():
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks OAuth Not Configured",
            detail="Missing QuickBooks OAuth configuration.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    if from_date.tzinfo is None:
        from_date = from_date.replace(tzinfo=timezone.utc)
    if to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=timezone.utc)
    try:
        result = await qbo_service.push_invoices_to_qbo(
            session,
            org_id,
            from_date=from_date.date(),
            to_date=to_date.date(),
        )
    except ValueError as exc:
        await qbo_service.record_sync_error(session, org_id, str(exc))
        await session.commit()
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks Invoice Push Failed",
            detail=str(exc),
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await session.commit()
    return integrations_schemas.QboInvoicePushResponse(
        from_utc=result.from_date,
        to_utc=result.to_date,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        total=result.total,
    )


@router.post(
    "/v1/admin/integrations/accounting/quickbooks/push/{invoice_id}",
    response_model=integrations_schemas.QboInvoicePushItemResponse,
    status_code=status.HTTP_200_OK,
)
async def push_quickbooks_invoice(
    invoice_id: str,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permissions(AdminPermission.FINANCE)),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.QboInvoicePushItemResponse:
    await _require_quickbooks_enabled(session, org_id)
    if not qbo_service.oauth_configured():
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks OAuth Not Configured",
            detail="Missing QuickBooks OAuth configuration.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    try:
        result = await qbo_service.push_invoice_to_qbo(
            session,
            org_id,
            invoice_id=invoice_id,
        )
    except ValueError as exc:
        await qbo_service.record_sync_error(session, org_id, str(exc))
        await session.commit()
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks Invoice Push Failed",
            detail=str(exc),
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await session.commit()
    return integrations_schemas.QboInvoicePushItemResponse(
        invoice_id=result.invoice_id,
        remote_invoice_id=result.remote_invoice_id,
        action=result.action,
    )


@router.post(
    "/v1/admin/integrations/accounting/quickbooks/pull_status",
    response_model=integrations_schemas.QboInvoicePullResponse,
    status_code=status.HTTP_200_OK,
)
async def pull_quickbooks_status(
    request: Request,
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permissions(AdminPermission.FINANCE)),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.QboInvoicePullResponse:
    await _require_quickbooks_enabled(session, org_id)
    if not qbo_service.oauth_configured():
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks OAuth Not Configured",
            detail="Missing QuickBooks OAuth configuration.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    if from_date.tzinfo is None:
        from_date = from_date.replace(tzinfo=timezone.utc)
    if to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=timezone.utc)
    try:
        result = await qbo_service.pull_invoice_status_from_qbo(
            session,
            org_id,
            from_date=from_date.date(),
            to_date=to_date.date(),
        )
    except ValueError as exc:
        await qbo_service.record_sync_error(session, org_id, str(exc))
        await session.commit()
        return problem_details(
            request=request,
            status=400,
            title="QuickBooks Status Pull Failed",
            detail=str(exc),
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await session.commit()
    return integrations_schemas.QboInvoicePullResponse(
        from_utc=result.from_date,
        to_utc=result.to_date,
        invoices_touched=result.invoices_touched,
        payments_recorded=result.payments_recorded,
        payments_skipped=result.payments_skipped,
        total=result.total,
    )


@router.get(
    "/v1/admin/integrations/google/status",
    response_model=integrations_schemas.GcalIntegrationStatus,
    status_code=status.HTTP_200_OK,
)
async def get_google_calendar_status(
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_viewer),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.GcalIntegrationStatus:
    module_enabled = await feature_service.effective_feature_enabled(session, org_id, "module.integrations")
    gcal_enabled = await feature_service.effective_feature_enabled(
        session, org_id, "integrations.google_calendar"
    )
    if not (module_enabled and gcal_enabled):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Disabled by org settings")

    account = await gcal_service.get_google_account(session, org_id)
    calendar_id = await gcal_service.get_primary_calendar_id(session, org_id)
    sync_state = None
    if account and calendar_id:
        sync_state = await gcal_service.get_sync_state(session, org_id, calendar_id)
    return integrations_schemas.GcalIntegrationStatus(
        connected=bool(account),
        calendar_id=calendar_id if account else None,
        oauth_configured=gcal_service.oauth_configured(),
        last_sync_at=sync_state.last_sync_at if sync_state else None,
        last_error=sync_state.last_error if sync_state else None,
    )


@router.post(
    "/v1/admin/integrations/google/connect/start",
    response_model=integrations_schemas.GcalConnectStartResponse,
    status_code=status.HTTP_200_OK,
)
async def start_google_calendar_connect(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.GcalConnectStartResponse:
    await _require_google_calendar_enabled(session, org_id)
    if not gcal_service.oauth_configured():
        return problem_details(
            request=request,
            status=400,
            title="Google OAuth Not Configured",
            detail="Missing Google OAuth configuration.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    auth_url = gcal_service.build_auth_url(state=str(org_id))
    return integrations_schemas.GcalConnectStartResponse(authorization_url=auth_url)


@router.post(
    "/v1/admin/integrations/google/connect/callback",
    response_model=integrations_schemas.GcalConnectCallbackResponse,
    status_code=status.HTTP_200_OK,
)
async def finish_google_calendar_connect(
    payload: integrations_schemas.GcalConnectCallbackRequest,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.GcalConnectCallbackResponse:
    await _require_google_calendar_enabled(session, org_id)
    if not gcal_service.oauth_configured():
        return problem_details(
            request=request,
            status=400,
            title="Google OAuth Not Configured",
            detail="Missing Google OAuth configuration.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    try:
        refresh_token, scopes = await gcal_service.exchange_code_for_refresh_token(payload.code)
    except ValueError:
        return problem_details(
            request=request,
            status=400,
            title="Google OAuth Exchange Failed",
            detail="Unable to exchange authorization code.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await gcal_service.upsert_google_account(
        session,
        org_id,
        refresh_token,
        scopes,
        audit_actor=config_audit_service.admin_actor(identity, auth_method=_resolve_auth_method(request)),
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    calendar_id = await gcal_service.get_primary_calendar_id(session, org_id)
    return integrations_schemas.GcalConnectCallbackResponse(
        connected=True,
        calendar_id=calendar_id,
    )


@router.post(
    "/v1/admin/integrations/google/disconnect",
    response_model=integrations_schemas.GcalConnectCallbackResponse,
    status_code=status.HTTP_200_OK,
)
async def disconnect_google_calendar(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.GcalConnectCallbackResponse:
    await _require_google_calendar_enabled(session, org_id)
    await gcal_service.disconnect_google_calendar(
        session,
        org_id,
        audit_actor=config_audit_service.admin_actor(identity, auth_method=_resolve_auth_method(request)),
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return integrations_schemas.GcalConnectCallbackResponse(connected=False, calendar_id=None)


@router.post(
    "/v1/admin/integrations/google/gcal/export_sync",
    response_model=integrations_schemas.GcalExportSyncResponse,
    status_code=status.HTTP_200_OK,
)
async def export_google_calendar_sync(
    request: Request,
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permissions(AdminPermission.DISPATCH)),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.GcalExportSyncResponse:
    await _require_google_calendar_enabled(session, org_id)
    if not gcal_service.oauth_configured():
        return problem_details(
            request=request,
            status=400,
            title="Google OAuth Not Configured",
            detail="Missing Google OAuth configuration.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    if from_date.tzinfo is None:
        from_date = from_date.replace(tzinfo=timezone.utc)
    if to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=timezone.utc)
    try:
        result = await gcal_service.export_bookings_to_gcal(
            session,
            org_id,
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        return problem_details(
            request=request,
            status=400,
            title="Google Calendar Export Failed",
            detail=str(exc),
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await session.commit()
    return integrations_schemas.GcalExportSyncResponse(
        calendar_id=result.calendar_id,
        from_utc=result.from_utc,
        to_utc=result.to_utc,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        total=result.total,
    )


@router.post(
    "/v1/admin/integrations/google/gcal/import_sync",
    response_model=integrations_schemas.GcalImportSyncResponse,
    status_code=status.HTTP_200_OK,
)
async def import_google_calendar_sync(
    request: Request,
    from_date: datetime = Query(..., alias="from"),
    to_date: datetime = Query(..., alias="to"),
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_permissions(AdminPermission.DISPATCH)),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.GcalImportSyncResponse:
    await _require_google_calendar_enabled(session, org_id)
    if not gcal_service.oauth_configured():
        return problem_details(
            request=request,
            status=400,
            title="Google OAuth Not Configured",
            detail="Missing Google OAuth configuration.",
            type_=PROBLEM_TYPE_DOMAIN,
        )
    if from_date.tzinfo is None:
        from_date = from_date.replace(tzinfo=timezone.utc)
    if to_date.tzinfo is None:
        to_date = to_date.replace(tzinfo=timezone.utc)
    try:
        result = await gcal_service.import_gcal_events_to_blocks(
            session,
            org_id,
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        return problem_details(
            request=request,
            status=400,
            title="Google Calendar Import Failed",
            detail=str(exc),
            type_=PROBLEM_TYPE_DOMAIN,
        )
    await session.commit()
    return integrations_schemas.GcalImportSyncResponse(
        calendar_id=result.calendar_id,
        from_utc=result.from_utc,
        to_utc=result.to_utc,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        total=result.total,
    )
