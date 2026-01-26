import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_audit import service as audit_service
from app.domain.break_glass.db_models import BreakGlassScope, BreakGlassSession, BreakGlassStatus
from app.infra.auth import hash_api_token
from app.infra.metrics import metrics
from app.settings import settings

DEFAULT_TTL_MINUTES = 30


def _normalize_ttl(ttl_minutes: int | None) -> int:
    max_ttl = max(1, int(getattr(settings, "break_glass_max_ttl_minutes", 60)))
    default_ttl = max(1, int(getattr(settings, "break_glass_default_ttl_minutes", DEFAULT_TTL_MINUTES)))
    if ttl_minutes is None:
        return min(default_ttl, max_ttl)
    return max(1, min(int(ttl_minutes), max_ttl))


async def _count_active(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    stmt = sa.select(sa.func.count()).select_from(BreakGlassSession).where(
        BreakGlassSession.status == BreakGlassStatus.ACTIVE.value,
        BreakGlassSession.expires_at > now,
    )
    return int((await session.execute(stmt)).scalar_one() or 0)


async def _update_active_gauge(session: AsyncSession) -> None:
    await session.flush()
    active_count = await _count_active(session)
    metrics.set_break_glass_active(active_count)


async def create_session(
    session: AsyncSession,
    *,
    org_id,
    actor_id: str,
    actor: str,
    reason: str,
    incident_ref: str,
    scope: BreakGlassScope,
    ttl_minutes: int | None,
) -> Tuple[str, BreakGlassSession]:
    ttl = _normalize_ttl(ttl_minutes)
    token = secrets.token_urlsafe(32)
    token_hash = hash_api_token(token)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl)

    record = BreakGlassSession(
        org_id=org_id,
        actor_id=actor_id,
        actor=actor,
        reason=reason,
        incident_ref=incident_ref,
        scope=scope.value,
        status=BreakGlassStatus.ACTIVE.value,
        token_hash=token_hash,
        expires_at=expires_at,
        granted_at=now,
    )
    session.add(record)
    await session.flush()
    metrics.record_break_glass_grant(scope.value, "created")
    await _update_active_gauge(session)
    return token, record


async def revoke_session(
    session: AsyncSession,
    *,
    record: BreakGlassSession,
    revoked_by: str | None = None,
    request_id: str | None = None,
) -> BreakGlassSession:
    if record.status != BreakGlassStatus.ACTIVE.value:
        return record
    record.status = BreakGlassStatus.REVOKED.value
    record.revoked_at = datetime.now(timezone.utc)
    metrics.record_break_glass_grant(record.scope, "revoked")
    await _update_active_gauge(session)
    return record


async def review_session(
    session: AsyncSession,
    *,
    record: BreakGlassSession,
    reviewed_by: str,
    review_notes: str,
    request_id: str | None = None,
) -> BreakGlassSession:
    record.reviewed_at = datetime.now(timezone.utc)
    record.reviewed_by = reviewed_by
    record.review_notes = review_notes
    await audit_service.record_system_action(
        session,
        org_id=record.org_id,
        action="break_glass_reviewed",
        resource_type="break_glass_session",
        resource_id=str(record.session_id),
        after={
            "reviewed_by": reviewed_by,
            "review_notes": review_notes,
            "incident_ref": record.incident_ref,
            "request_id": request_id,
        },
    )
    return record


async def expire_session_if_needed(
    session: AsyncSession,
    *,
    record: BreakGlassSession,
    request_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at > now or record.status != BreakGlassStatus.ACTIVE.value:
        return
    record.status = BreakGlassStatus.EXPIRED.value
    await audit_service.record_system_action(
        session,
        org_id=record.org_id,
        action="break_glass_expired",
        resource_type="break_glass_session",
        resource_id=str(record.session_id),
        after={
            "actor_id": record.actor_id,
            "incident_ref": record.incident_ref,
            "scope": record.scope,
            "reason": record.reason,
            "request_id": request_id,
        },
    )
    metrics.record_break_glass_grant(record.scope, "expired")
    await _update_active_gauge(session)


async def get_valid_session(
    session: AsyncSession, *, org_id, token: str, request_id: str | None = None
) -> BreakGlassSession | None:
    token_hash = hash_api_token(token)
    result = await session.execute(
        select(BreakGlassSession).where(
            BreakGlassSession.token_hash == token_hash,
            sa.or_(
                BreakGlassSession.org_id == org_id,
                BreakGlassSession.scope == BreakGlassScope.GLOBAL.value,
            ),
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        return None

    if record.status != BreakGlassStatus.ACTIVE.value:
        return None

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= datetime.now(timezone.utc):
        await expire_session_if_needed(session, record=record, request_id=request_id)
        return None

    return record
