from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import entitlements, saas_auth
from app.api.admin_auth import AdminIdentity
from app.api.problem_details import PROBLEM_TYPE_RATE_LIMIT, problem_details
from app.domain.clients import schemas as client_schemas
from app.domain.clients import service as client_service
from app.domain.data_rights.audit import (
    DATA_EXPORT_DOWNLOAD_DENIED,
    DATA_EXPORT_DOWNLOADED,
    DATA_EXPORT_REQUESTED,
    audit_data_export_event,
)
from app.domain.data_rights import schemas as data_rights_schemas
from app.domain.data_rights import service as data_rights_service
from app.domain.data_rights.db_models import DataExportRequest
from app.domain.iam import permissions as iam_permissions
from app.domain.leads.db_models import Lead
from app.infra.db import get_db_session
from app.infra.org_context import set_current_org_id
from app.infra.storage import resolve_storage_backend
from app.settings import settings

router = APIRouter(tags=["data-rights"])
logger = logging.getLogger(__name__)

CLIENT_SESSION_COOKIE = "client_session"


def _resolve_request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    return request.headers.get("X-Request-ID")


def _storage_backend(request: Request):
    return resolve_storage_backend(request.app.state)


async def _enforce_data_rights_rate_limit(
    request: Request, *, key_hint: str | None = None
) -> Response | None:
    limiter = getattr(request.app.state, "rate_limiter", None)
    if not limiter:
        return None
    client_host = request.client.host if request.client else "unknown"
    key_parts = ["data-rights", client_host]
    if key_hint:
        key_parts.append(key_hint)
    allowed = await limiter.allow(":".join(key_parts))
    if allowed:
        return None
    return problem_details(
        request=request,
        status=status.HTTP_429_TOO_MANY_REQUESTS,
        title="Too Many Requests",
        detail="Data export rate limit exceeded",
        type_=PROBLEM_TYPE_RATE_LIMIT,
    )


def _client_token(request: Request) -> str | None:
    token = request.cookies.get(CLIENT_SESSION_COOKIE) or request.headers.get("Authorization")
    if token and token.startswith("Bearer "):
        token = token.split(" ", 1)[1]
    if token and token.count(".") == 1:
        return token
    return None


async def _get_client_identity(request: Request) -> client_schemas.ClientIdentity | None:
    token = _client_token(request)
    if not token:
        return None
    try:
        result = client_service.verify_magic_token(token, secret=settings.client_portal_secret)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    request.state.current_org_id = result.org_id
    set_current_org_id(result.org_id)
    return client_schemas.ClientIdentity(
        client_id=result.client_id,
        email=result.email,
        issued_at=result.issued_at,
        org_id=result.org_id,
    )


async def _get_saas_identity(request: Request) -> saas_auth.SaaSIdentity | None:
    cached = saas_auth._get_cached_identity(request)
    if cached:
        return cached
    token = saas_auth._get_saas_token(request)
    if not token or token.count(".") != 2:
        return None
    identity = await saas_auth._load_identity(request, token, strict=True)
    request.state.saas_identity = identity
    request.state.current_org_id = identity.org_id
    set_current_org_id(identity.org_id)
    if not getattr(request.state, "admin_identity", None):
        admin_role = saas_auth.ROLE_TO_ADMIN_ROLE.get(identity.role)
        if admin_role:
            request.state.admin_identity = AdminIdentity(
                username=identity.email or str(identity.user_id),
                role=admin_role,
                org_id=identity.org_id,
                admin_id=str(identity.user_id),
                auth_method="saas",
            )
    return identity


def _require_export_permission(identity: saas_auth.SaaSIdentity) -> None:
    role_key = identity.role_key or getattr(identity.role, "value", str(identity.role))
    granted = iam_permissions.effective_permissions(
        role_key=role_key,
        custom_permissions=identity.permission_keys,
    )
    if "exports.run" not in granted:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _resolve_admin_identity(
    request: Request, identity: saas_auth.SaaSIdentity
) -> AdminIdentity:
    existing = getattr(request.state, "admin_identity", None)
    if existing:
        return existing
    admin_role = saas_auth.ROLE_TO_ADMIN_ROLE.get(identity.role)
    if not admin_role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    resolved = AdminIdentity(
        username=identity.email or str(identity.user_id),
        role=admin_role,
        org_id=identity.org_id,
        admin_id=str(identity.user_id),
        auth_method="saas",
    )
    request.state.admin_identity = resolved
    return resolved


@router.post(
    "/v1/data-rights/export-request",
    response_model=data_rights_schemas.DataRightsExportRequestResponse,
)
async def request_data_export(
    request: Request,
    payload: data_rights_schemas.DataRightsExportRequestPayload | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> data_rights_schemas.DataRightsExportRequestResponse:
    rate_limited = await _enforce_data_rights_rate_limit(request)
    if rate_limited:
        return rate_limited  # type: ignore[return-value]

    client_identity = await _get_client_identity(request)
    saas_identity = await _get_saas_identity(request)
    if not client_identity and not saas_identity:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    org_id = entitlements.resolve_org_id(request)
    request_id = _resolve_request_id(request)

    if client_identity:
        subject_id = client_identity.client_id
        subject_type = "client"
        subject_email = client_identity.email.lower()
        requested_by = client_identity.email
        requested_by_type = "client"
    else:
        _require_export_permission(saas_identity)
        if not payload or not (payload.lead_id or payload.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="lead_id_or_email_required"
            )
        subject_email = payload.email.lower() if payload.email else None
        subject_type = "email" if payload.email and not payload.lead_id else "lead"
        subject_id = payload.lead_id or subject_email or "unknown"
        requested_by = saas_identity.email or str(saas_identity.user_id)
        requested_by_type = "admin"
        if payload.lead_id:
            lead = await session.scalar(
                select(Lead).where(Lead.lead_id == payload.lead_id, Lead.org_id == org_id)
            )
            if not lead:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead_not_found")
            if lead.email:
                subject_email = lead.email.lower()

    record = await data_rights_service.create_data_export_request(
        session,
        org_id=org_id,
        subject_id=subject_id,
        subject_type=subject_type,
        subject_email=subject_email,
        requested_by=requested_by,
        requested_by_type=requested_by_type,
        request_id=request_id,
    )

    if saas_identity:
        admin_identity = _resolve_admin_identity(request, saas_identity)
        request.state.explicit_admin_audit = True
        await audit_data_export_event(
            session,
            org_id=org_id,
            export_id=record.export_id,
            subject_id=subject_id,
            subject_type=subject_type,
            actor_type="admin",
            actor_id=None,
            admin_identity=admin_identity,
            request_id=request_id,
            status=record.status,
            on_behalf_of={"subject_id": subject_id, "subject_type": subject_type},
            event=DATA_EXPORT_REQUESTED,
        )
    else:
        await audit_data_export_event(
            session,
            org_id=org_id,
            export_id=record.export_id,
            subject_id=subject_id,
            subject_type=subject_type,
            actor_type="subject",
            actor_id=client_identity.client_id if client_identity else None,
            request_id=request_id,
            status=record.status,
            event=DATA_EXPORT_REQUESTED,
        )

    await session.commit()
    return data_rights_schemas.DataRightsExportRequestResponse(
        export_id=str(record.export_id),
        status=record.status,
        created_at=record.created_at,
    )


@router.get(
    "/v1/data-rights/exports",
    response_model=data_rights_schemas.DataRightsExportListResponse,
)
async def list_data_exports(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    lead_id: str | None = Query(None),
    email: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> data_rights_schemas.DataRightsExportListResponse:
    client_identity = await _get_client_identity(request)
    saas_identity = await _get_saas_identity(request)
    if not client_identity and not saas_identity:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    org_id = entitlements.resolve_org_id(request)

    subject_email = None
    subject_id = None
    if client_identity:
        subject_email = client_identity.email.lower()
        subject_id = client_identity.client_id
    else:
        _require_export_permission(saas_identity)
        subject_id = lead_id or None
        subject_email = email.lower() if email else None

    items, total = await data_rights_service.list_data_export_requests(
        session,
        org_id=org_id,
        subject_email=subject_email,
        subject_id=subject_id,
        limit=limit,
        offset=offset,
    )
    return data_rights_schemas.DataRightsExportListResponse(
        items=[
            data_rights_schemas.DataRightsExportListItem(
                export_id=str(item.export_id),
                status=item.status,
                created_at=item.created_at,
                completed_at=item.completed_at,
            )
            for item in items
        ],
        total=total,
    )


@router.get("/v1/data-rights/exports/{export_id}/download")
async def download_data_export(
    export_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    rate_limited = await _enforce_data_rights_rate_limit(request, key_hint=str(export_id))
    if rate_limited:
        return rate_limited

    client_identity = await _get_client_identity(request)
    saas_identity = await _get_saas_identity(request)
    if not client_identity and not saas_identity:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    org_id = entitlements.resolve_org_id(request)

    export_request = await session.scalar(
        select(DataExportRequest).where(
            DataExportRequest.export_id == export_id,
            DataExportRequest.org_id == org_id,
        )
    )
    if not export_request or export_request.status != "completed" or not export_request.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")

    request_id = _resolve_request_id(request)
    if client_identity:
        email_match = export_request.subject_email == client_identity.email.lower()
        id_match = export_request.subject_id == client_identity.client_id
        if not (email_match or id_match):
            await audit_data_export_event(
                session,
                org_id=org_id,
                export_id=export_request.export_id,
                subject_id=export_request.subject_id,
                subject_type=export_request.subject_type,
                actor_type="subject",
                actor_id=client_identity.client_id,
                request_id=request_id,
                event=DATA_EXPORT_DOWNLOAD_DENIED,
                reason_code="subject_mismatch",
            )
            await session.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    else:
        try:
            _require_export_permission(saas_identity)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                admin_identity = _resolve_admin_identity(request, saas_identity)
                request.state.explicit_admin_audit = True
                await audit_data_export_event(
                    session,
                    org_id=org_id,
                    export_id=export_request.export_id,
                    subject_id=export_request.subject_id,
                    subject_type=export_request.subject_type,
                    actor_type="admin",
                    actor_id=None,
                    admin_identity=admin_identity,
                    request_id=request_id,
                    event=DATA_EXPORT_DOWNLOAD_DENIED,
                    reason_code="missing_permission",
                    on_behalf_of={
                        "subject_id": export_request.subject_id,
                        "subject_type": export_request.subject_type,
                    },
                )
                await session.commit()
            raise

    if saas_identity:
        admin_identity = _resolve_admin_identity(request, saas_identity)
        request.state.explicit_admin_audit = True
        await audit_data_export_event(
            session,
            org_id=org_id,
            export_id=export_request.export_id,
            subject_id=export_request.subject_id,
            subject_type=export_request.subject_type,
            actor_type="admin",
            actor_id=None,
            admin_identity=admin_identity,
            request_id=request_id,
            event=DATA_EXPORT_DOWNLOADED,
            status=export_request.status,
            on_behalf_of={
                "subject_id": export_request.subject_id,
                "subject_type": export_request.subject_type,
            },
        )
    else:
        await audit_data_export_event(
            session,
            org_id=org_id,
            export_id=export_request.export_id,
            subject_id=export_request.subject_id,
            subject_type=export_request.subject_type,
            actor_type="subject",
            actor_id=client_identity.client_id if client_identity else None,
            request_id=request_id,
            event=DATA_EXPORT_DOWNLOADED,
            status=export_request.status,
        )
    await session.commit()

    storage = _storage_backend(request)
    ttl = settings.data_export_signed_url_ttl_seconds
    if storage.supports_direct_io():
        file_path = storage.path_for(export_request.storage_key) if hasattr(storage, "path_for") else None
        if not file_path or not file_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")
        response = FileResponse(
            path=file_path,
            media_type=export_request.content_type or "application/json",
            filename=f"data-export-{export_id}.json",
        )
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    download_url = str(request.url_for("download_data_export", export_id=export_id))
    signed_url = await storage.generate_signed_get_url(
        key=export_request.storage_key,
        expires_in=ttl,
        resource_url=download_url,
    )
    response = RedirectResponse(url=signed_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
