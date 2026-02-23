from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

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
from app.domain.org_settings import service as org_settings_service
from app.infra.db import get_db_session
from app.infra.org_context import set_current_org_id
from app.infra.security import create_rate_limiter
from app.infra.storage import resolve_storage_backend
from app.settings import settings

router = APIRouter(tags=["data-rights"])
logger = logging.getLogger(__name__)

CLIENT_SESSION_COOKIE = "client_session"


@dataclass(frozen=True)
class DataExportRateLimitPolicy:
    request_per_minute: int
    request_per_hour: int
    download_per_minute: int
    download_failure_limit: int
    download_lockout_limit: int
    download_failure_window_seconds: int
    download_lockout_window_seconds: int
    cooldown_seconds: int


def _resolve_request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    return request.headers.get("X-Request-ID")


def _storage_backend(request: Request):
    return resolve_storage_backend(request.app.state)


def _resolve_metrics(request: Request):
    return getattr(request.app.state, "metrics", None)


def _export_rate_limit_response(
    request: Request,
    *,
    endpoint: str,
    retry_after_seconds: int,
    detail: str,
) -> Response:
    metrics_client = _resolve_metrics(request)
    if metrics_client is not None:
        metrics_client.record_data_export_rate_limited(endpoint)
    headers = {"Retry-After": str(max(1, int(retry_after_seconds)))}
    return problem_details(
        request=request,
        status=status.HTTP_429_TOO_MANY_REQUESTS,
        title="Too Many Requests",
        detail=detail,
        errors=[{"code": "DATA_EXPORT_RATE_LIMITED"}],
        headers=headers,
        type_=PROBLEM_TYPE_RATE_LIMIT,
    )


def _record_export_denied(request: Request, reason: str) -> None:
    metrics_client = _resolve_metrics(request)
    if metrics_client is not None:
        metrics_client.record_data_export_denied(reason)


def _get_export_rate_limiter(request: Request, *, limit: int, window_seconds: int):
    if limit <= 0 or window_seconds <= 0:
        return None
    app_state = request.app.state
    cache = getattr(app_state, "data_export_rate_limiters", None)
    if cache is None:
        cache = {}
        app_state.data_export_rate_limiters = cache
    cache_key = (limit, window_seconds)
    limiter = cache.get(cache_key)
    if limiter:
        return limiter
    app_settings = getattr(app_state, "app_settings", settings)
    limiter = create_rate_limiter(
        app_settings,
        requests_per_minute=limit,
        window_seconds=window_seconds,
    )
    cache[cache_key] = limiter
    return limiter


def _rate_limit_key(*parts: str) -> str:
    return ":".join(part for part in parts if part)


async def _resolve_export_policy(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> DataExportRateLimitPolicy:
    record = await org_settings_service.get_or_create_org_settings(session, org_id)
    return DataExportRateLimitPolicy(
        request_per_minute=org_settings_service.resolve_data_export_request_rate_limit_per_minute(
            record, settings.data_export_request_rate_limit_per_minute
        ),
        request_per_hour=org_settings_service.resolve_data_export_request_rate_limit_per_hour(
            record, settings.data_export_request_rate_limit_per_hour
        ),
        download_per_minute=org_settings_service.resolve_data_export_download_rate_limit_per_minute(
            record, settings.data_export_download_rate_limit_per_minute
        ),
        download_failure_limit=org_settings_service.resolve_data_export_download_failure_limit_per_window(
            record, settings.data_export_download_failure_limit_per_window
        ),
        download_lockout_limit=org_settings_service.resolve_data_export_download_lockout_limit_per_window(
            record, settings.data_export_download_lockout_limit_per_window
        ),
        download_failure_window_seconds=settings.data_export_download_failure_window_seconds,
        download_lockout_window_seconds=settings.data_export_download_lockout_window_seconds,
        cooldown_seconds=org_settings_service.resolve_data_export_cooldown_minutes(
            record, settings.data_export_cooldown_minutes
        )
        * 60,
    )


async def _enforce_export_request_limits(
    request: Request,
    *,
    subject_key: str,
    policy: DataExportRateLimitPolicy,
) -> Response | None:
    if policy.request_per_minute > 0:
        limiter = _get_export_rate_limiter(
            request,
            limit=policy.request_per_minute,
            window_seconds=60,
        )
        if limiter and not await limiter.allow(subject_key):
            return _export_rate_limit_response(
                request,
                endpoint="request",
                retry_after_seconds=60,
                detail="Data export request rate limit exceeded",
            )
    if policy.request_per_hour > 0:
        limiter = _get_export_rate_limiter(
            request,
            limit=policy.request_per_hour,
            window_seconds=3600,
        )
        if limiter and not await limiter.allow(subject_key):
            return _export_rate_limit_response(
                request,
                endpoint="request",
                retry_after_seconds=3600,
                detail="Data export request cooldown limit exceeded",
            )
    return None


async def _enforce_export_download_limit(
    request: Request,
    *,
    download_key: str,
    policy: DataExportRateLimitPolicy,
) -> Response | None:
    if policy.download_per_minute <= 0:
        return None
    limiter = _get_export_rate_limiter(
        request,
        limit=policy.download_per_minute,
        window_seconds=60,
    )
    if limiter and not await limiter.allow(download_key):
        return _export_rate_limit_response(
            request,
            endpoint="download",
            retry_after_seconds=60,
            detail="Data export download rate limit exceeded",
        )
    return None


async def _enforce_download_denied_limits(
    request: Request,
    *,
    denied_key: str,
    policy: DataExportRateLimitPolicy,
) -> Response | None:
    if policy.download_lockout_limit > 0:
        limiter = _get_export_rate_limiter(
            request,
            limit=policy.download_lockout_limit,
            window_seconds=policy.download_lockout_window_seconds,
        )
        if limiter and not await limiter.allow(denied_key):
            return _export_rate_limit_response(
                request,
                endpoint="download",
                retry_after_seconds=policy.download_lockout_window_seconds,
                detail="Data export download locked due to repeated denied attempts",
            )
    if policy.download_failure_limit > 0:
        limiter = _get_export_rate_limiter(
            request,
            limit=policy.download_failure_limit,
            window_seconds=policy.download_failure_window_seconds,
        )
        if limiter and not await limiter.allow(denied_key):
            return _export_rate_limit_response(
                request,
                endpoint="download",
                retry_after_seconds=policy.download_failure_window_seconds,
                detail="Data export download throttled due to repeated denied attempts",
            )
    return None


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
        result = client_service.verify_magic_token(
            token, secret=settings.client_portal_secret.get_secret_value()
        )
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


def _actor_key(
    *,
    client_identity: client_schemas.ClientIdentity | None,
    saas_identity: saas_auth.SaaSIdentity | None,
) -> str:
    if client_identity:
        return f"client:{client_identity.client_id}"
    if saas_identity:
        value = saas_identity.user_id or saas_identity.email or "unknown"
        return f"admin:{value}"
    return "unknown"


@router.post(
    "/v1/data-rights/export-request",
    response_model=data_rights_schemas.DataRightsExportRequestResponse,
)
async def request_data_export(
    request: Request,
    payload: data_rights_schemas.DataRightsExportRequestPayload | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> data_rights_schemas.DataRightsExportRequestResponse:
    client_identity = await _get_client_identity(request)
    saas_identity = await _get_saas_identity(request)
    if not client_identity and not saas_identity:
        _record_export_denied(request, "unauthenticated")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    org_id = entitlements.resolve_org_id(request)
    policy = await _resolve_export_policy(session, org_id)
    request_id = _resolve_request_id(request)

    if client_identity:
        subject_id = client_identity.client_id
        subject_type = "client"
        subject_email = client_identity.email.lower()
        requested_by = client_identity.email
        requested_by_type = "client"
    else:
        try:
            _require_export_permission(saas_identity)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                _record_export_denied(request, "missing_permission")
            raise
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

    subject_key = _rate_limit_key(
        "data-export:request",
        str(org_id),
        subject_type,
        str(subject_id),
    )
    rate_limited = await _enforce_export_request_limits(
        request,
        subject_key=subject_key,
        policy=policy,
    )
    if rate_limited:
        return rate_limited  # type: ignore[return-value]

    existing = await data_rights_service.find_recent_export_request(
        session,
        org_id=org_id,
        subject_id=str(subject_id) if subject_id else None,
        subject_email=subject_email,
        cooldown_seconds=policy.cooldown_seconds,
    )
    if existing:
        return data_rights_schemas.DataRightsExportRequestResponse(
            export_id=str(existing.export_id),
            status=existing.status,
            created_at=existing.created_at,
        )

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
    page_size: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    offset: int | None = Query(None, ge=0, deprecated=True),
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

    if cursor is not None:
        try:
            data_rights_service.decode_data_export_cursor_strict(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_cursor") from exc

    try:
        items, total, next_cursor, prev_cursor = await data_rights_service.list_data_export_requests(
            session,
            org_id=org_id,
            subject_email=subject_email,
            subject_id=subject_id,
            limit=page_size,
            cursor=cursor,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_cursor") from exc
    return data_rights_schemas.DataRightsExportListResponse(
        items=[
            data_rights_schemas.DataRightsExportListItem(
                export_id=str(item.export_id),
                status=item.status,
                subject_id=item.subject_id,
                subject_type=item.subject_type,
                created_at=item.created_at,
                completed_at=item.completed_at,
            )
            for item in items
        ],
        total=total,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
    )


@router.get("/v1/data-rights/exports/{export_id}/download")
async def download_data_export(
    export_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    client_identity = await _get_client_identity(request)
    saas_identity = await _get_saas_identity(request)
    if not client_identity and not saas_identity:
        _record_export_denied(request, "unauthenticated")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    org_id = entitlements.resolve_org_id(request)
    policy = await _resolve_export_policy(session, org_id)

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
            denied_key = _rate_limit_key(
                "data-export:download-denied",
                str(org_id),
                _actor_key(client_identity=client_identity, saas_identity=None),
            )
            throttled = await _enforce_download_denied_limits(
                request,
                denied_key=denied_key,
                policy=policy,
            )
            if throttled:
                return throttled
            _record_export_denied(request, "subject_mismatch")
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
                denied_key = _rate_limit_key(
                    "data-export:download-denied",
                    str(org_id),
                    _actor_key(client_identity=None, saas_identity=saas_identity),
                )
                throttled = await _enforce_download_denied_limits(
                    request,
                    denied_key=denied_key,
                    policy=policy,
                )
                if throttled:
                    return throttled
                _record_export_denied(request, "missing_permission")
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

    download_key = _rate_limit_key(
        "data-export:download",
        str(org_id),
        export_request.subject_type,
        export_request.subject_id,
        str(export_id),
    )
    rate_limited = await _enforce_export_download_limit(
        request,
        download_key=download_key,
        policy=policy,
    )
    if rate_limited:
        return rate_limited

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
