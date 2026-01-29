import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminPermission, AdminRole, require_permissions
from app.domain.admin_audit import service as audit_service
from app.domain.break_glass import service as break_glass_service
from app.domain.break_glass.db_models import BreakGlassScope, BreakGlassSession, BreakGlassStatus
from app.infra.db import get_db_session
from app.settings import settings

router = APIRouter()

BREAK_GLASS_HEADER = "X-Break-Glass-Token"


class BreakGlassStartRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    incident_ref: str = Field(..., min_length=1)
    scope: BreakGlassScope = Field(default=BreakGlassScope.ORG)
    ttl_minutes: int | None = Field(None, ge=1)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason cannot be empty")
        return cleaned

    @field_validator("incident_ref")
    @classmethod
    def _trim_incident(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("incident_ref cannot be empty")
        return cleaned


class BreakGlassStartResponse(BaseModel):
    token: str
    expires_at: datetime
    session_id: uuid.UUID


async def require_break_glass(
    request: Request, session: AsyncSession = Depends(get_db_session)
) -> BreakGlassSession:
    cached: BreakGlassSession | None = getattr(request.state, "break_glass_session", None)
    if cached:
        return cached

    token = request.headers.get(BREAK_GLASS_HEADER)
    if not token:
        raise HTTPException(status_code=403, detail="Break-glass token required")

    org_id = getattr(request.state, "current_org_id", None) or settings.default_org_id
    record = await break_glass_service.get_valid_session(
        session, org_id=org_id, token=token, request_id=_resolve_request_id(request)
    )
    if record is None:
        await session.commit()
        raise HTTPException(status_code=403, detail="Break-glass token invalid or expired")

    set_break_glass_state(request, record)
    return record


def set_break_glass_state(request: Request, record: BreakGlassSession) -> None:
    request.state.break_glass = True
    request.state.break_glass_reason = record.reason
    request.state.break_glass_incident_ref = record.incident_ref
    request.state.break_glass_scope = record.scope
    request.state.break_glass_session = record
    request.state.break_glass_session_id = record.session_id


@router.post(
    "/v1/admin/break-glass/start", response_model=BreakGlassStartResponse, status_code=status.HTTP_200_OK
)
async def start_break_glass(
    payload: BreakGlassStartRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
) -> BreakGlassStartResponse:
    _require_break_glass_eligibility(request, identity)
    if payload.scope == BreakGlassScope.GLOBAL and identity.role != AdminRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Global scope requires owner role")
    org_id: uuid.UUID = getattr(request.state, "current_org_id", None) or settings.default_org_id
    actor_id = _resolve_actor_id(request, identity)
    token, record = await break_glass_service.create_session(
        session,
        org_id=org_id,
        actor_id=actor_id,
        actor=identity.username,
        reason=payload.reason,
        incident_ref=payload.incident_ref,
        scope=payload.scope,
        ttl_minutes=payload.ttl_minutes,
    )

    await audit_service.record_action(
        session,
        identity=identity,
        action="break_glass_grant_created",
        resource_type="break_glass_session",
        resource_id=str(record.session_id),
        before=None,
        after={
            "actor_id": actor_id,
            "reason": payload.reason,
            "incident_ref": payload.incident_ref,
            "scope": payload.scope.value,
            "expires_at": record.expires_at.isoformat(),
            "request_id": _resolve_request_id(request),
        },
    )
    await session.commit()

    return BreakGlassStartResponse(token=token, expires_at=record.expires_at, session_id=record.session_id)


class BreakGlassRevokeRequest(BaseModel):
    reason: str | None = Field(default=None)

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reason cannot be empty")
        return cleaned


class BreakGlassReviewRequest(BaseModel):
    review_notes: str = Field(..., min_length=1)

    @field_validator("review_notes")
    @classmethod
    def _trim_notes(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("review_notes cannot be empty")
        return cleaned


class BreakGlassReviewResponse(BaseModel):
    session_id: uuid.UUID
    status: str
    reviewed_at: datetime | None


@router.post(
    "/v1/admin/break-glass/{session_id}/revoke",
    response_model=BreakGlassReviewResponse,
    status_code=status.HTTP_200_OK,
)
async def revoke_break_glass(
    session_id: uuid.UUID,
    payload: BreakGlassRevokeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
) -> BreakGlassReviewResponse:
    _require_break_glass_eligibility(request, identity)
    if isinstance(session_id, str):
        session_id = uuid.UUID(session_id)
    record = await session.get(BreakGlassSession, session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Break-glass session not found")
    org_id: uuid.UUID = getattr(request.state, "current_org_id", None) or settings.default_org_id
    if record.org_id != org_id and record.scope != BreakGlassScope.GLOBAL.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Break-glass session not in scope")
    if record.status != BreakGlassStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Break-glass session not active")

    await break_glass_service.revoke_session(
        session,
        record=record,
        revoked_by=_resolve_actor_id(request, identity),
        request_id=_resolve_request_id(request),
    )
    await audit_service.record_action(
        session,
        identity=identity,
        action="break_glass_revoked",
        resource_type="break_glass_session",
        resource_id=str(record.session_id),
        before=None,
        after={
            "reason": payload.reason,
            "incident_ref": record.incident_ref,
            "revoked_by": _resolve_actor_id(request, identity),
            "request_id": _resolve_request_id(request),
        },
    )
    await session.commit()
    return BreakGlassReviewResponse(
        session_id=record.session_id,
        status=record.status,
        reviewed_at=record.reviewed_at,
    )


@router.post(
    "/v1/admin/break-glass/{session_id}/review",
    response_model=BreakGlassReviewResponse,
    status_code=status.HTTP_200_OK,
)
async def review_break_glass(
    session_id: uuid.UUID,
    payload: BreakGlassReviewRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_permissions(AdminPermission.ADMIN)),
) -> BreakGlassReviewResponse:
    _require_break_glass_eligibility(request, identity)
    if isinstance(session_id, str):
        session_id = uuid.UUID(session_id)
    record = await session.get(BreakGlassSession, session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Break-glass session not found")
    org_id: uuid.UUID = getattr(request.state, "current_org_id", None) or settings.default_org_id
    if record.org_id != org_id and record.scope != BreakGlassScope.GLOBAL.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Break-glass session not in scope")
    if record.status == BreakGlassStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Break-glass session still active")

    await break_glass_service.review_session(
        session,
        record=record,
        reviewed_by=_resolve_actor_id(request, identity),
        review_notes=payload.review_notes,
        request_id=_resolve_request_id(request),
    )
    await audit_service.record_action(
        session,
        identity=identity,
        action="break_glass_reviewed",
        resource_type="break_glass_session",
        resource_id=str(record.session_id),
        before=None,
        after={
            "review_notes": payload.review_notes,
            "incident_ref": record.incident_ref,
            "reviewed_by": _resolve_actor_id(request, identity),
            "request_id": _resolve_request_id(request),
        },
    )
    await session.commit()
    return BreakGlassReviewResponse(
        session_id=record.session_id,
        status=record.status,
        reviewed_at=record.reviewed_at,
    )


def _resolve_request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    return request.headers.get("X-Request-ID")


def _resolve_actor_id(request: Request, identity: AdminIdentity) -> str:
    saas_identity = getattr(request.state, "saas_identity", None)
    if saas_identity and getattr(saas_identity, "user_id", None):
        return str(saas_identity.user_id)
    return identity.username


def _require_break_glass_eligibility(request: Request, identity: AdminIdentity) -> None:
    saas_identity = getattr(request.state, "saas_identity", None)
    role_key = None
    if saas_identity is not None:
        role_key = (saas_identity.role_key or getattr(saas_identity.role, "value", None) or "").lower()
    eligible = identity.role == AdminRole.OWNER or (role_key in {"owner", "security"})
    if not eligible:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Break-glass not permitted")

    mfa_required = settings.admin_mfa_required
    required_roles = {role.lower() for role in settings.admin_mfa_required_roles}
    if mfa_required and (role_key or identity.role.value) in required_roles:
        if saas_identity is None or not getattr(saas_identity, "mfa_verified", False):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="MFA required")
