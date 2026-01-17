from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminPermission, AdminRole, require_permissions, require_viewer
from app.api.org_context import require_org_context
from app.api.problem_details import PROBLEM_TYPE_DOMAIN, problem_details
from app.domain.feature_modules import service as feature_service
from app.domain.integrations import gcal_service, schemas as integrations_schemas
from app.infra.db import get_db_session

router = APIRouter(tags=["admin-integrations"])


async def require_owner(
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
) -> AdminIdentity:
    if identity.role != AdminRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return identity


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
    return integrations_schemas.GcalIntegrationStatus(
        connected=bool(account),
        calendar_id=calendar_id if account else None,
        oauth_configured=gcal_service.oauth_configured(),
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
    _identity: AdminIdentity = Depends(require_owner),
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
    await gcal_service.upsert_google_account(session, org_id, refresh_token, scopes)
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
    org_id: uuid.UUID = Depends(require_org_context),
    _identity: AdminIdentity = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> integrations_schemas.GcalConnectCallbackResponse:
    await _require_google_calendar_enabled(session, org_id)
    await gcal_service.disconnect_google_calendar(session, org_id)
    await session.commit()
    return integrations_schemas.GcalConnectCallbackResponse(connected=False, calendar_id=None)
