from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.config_audit.db_models import ConfigAuditActor
from app.domain.feature_flag_audit import FeatureFlagAuditAction
from app.domain.feature_flag_audit import service as feature_flag_audit_service
from app.domain.feature_flags.db_models import FeatureFlagDefinition, FeatureFlagLifecycleState
from app.domain.feature_flags.schemas import (
    FeatureFlagDefinitionCreateRequest,
    FeatureFlagDefinitionUpdateRequest,
)
from app.settings import settings

ALLOWED_EXPIRING_WINDOWS = {7, 14, 30}


def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_effective_state(
    definition: FeatureFlagDefinition, *, now: datetime | None = None
) -> FeatureFlagLifecycleState:
    now = now or datetime.now(tz=timezone.utc)
    if definition.lifecycle_state == FeatureFlagLifecycleState.RETIRED.value:
        return FeatureFlagLifecycleState.RETIRED
    if definition.expires_at and _ensure_timezone(definition.expires_at) <= now:
        return FeatureFlagLifecycleState.EXPIRED
    return FeatureFlagLifecycleState(definition.lifecycle_state)


def _validate_override_reason(override_enabled: bool, override_reason: str | None) -> None:
    if override_enabled and not override_reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="override_reason is required when overrides are enabled",
        )


def _validate_expiration_horizon(
    expires_at: datetime, *, override_max_horizon: bool, override_reason: str | None
) -> None:
    _validate_override_reason(override_max_horizon, override_reason)
    now = datetime.now(tz=timezone.utc)
    normalized = _ensure_timezone(expires_at)
    if normalized <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="expires_at must be in the future"
        )
    horizon = now + timedelta(days=settings.feature_flag_max_horizon_days)
    if normalized > horizon and not override_max_horizon:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expires_at exceeds the maximum allowed horizon",
        )


def _definition_snapshot(definition: FeatureFlagDefinition) -> dict[str, object]:
    return {
        "key": definition.key,
        "owner": definition.owner,
        "purpose": definition.purpose,
        "created_at": definition.created_at,
        "expires_at": definition.expires_at,
        "lifecycle_state": definition.lifecycle_state,
    }


def _derive_transition_action(
    lifecycle_state: FeatureFlagLifecycleState,
) -> FeatureFlagAuditAction | None:
    if lifecycle_state == FeatureFlagLifecycleState.ACTIVE:
        return FeatureFlagAuditAction.ACTIVATE
    if lifecycle_state == FeatureFlagLifecycleState.EXPIRED:
        return FeatureFlagAuditAction.EXPIRE
    if lifecycle_state == FeatureFlagLifecycleState.RETIRED:
        return FeatureFlagAuditAction.RETIRE
    return None


async def get_feature_flag_definition(
    session: AsyncSession, key: str
) -> FeatureFlagDefinition | None:
    return await session.get(FeatureFlagDefinition, key)


async def list_feature_flag_definitions(
    session: AsyncSession,
    *,
    state: FeatureFlagLifecycleState | None = None,
    expiring_within_days: int | None = None,
) -> list[FeatureFlagDefinition]:
    now = datetime.now(tz=timezone.utc)
    stmt = select(FeatureFlagDefinition).order_by(FeatureFlagDefinition.key.asc())
    if expiring_within_days is not None:
        if expiring_within_days not in ALLOWED_EXPIRING_WINDOWS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="expiring_within_days must be one of 7, 14, or 30",
            )
        window_end = now + timedelta(days=expiring_within_days)
        stmt = stmt.where(
            FeatureFlagDefinition.expires_at.is_not(None),
            FeatureFlagDefinition.expires_at >= now,
            FeatureFlagDefinition.expires_at <= window_end,
        )
    if state is not None:
        if state == FeatureFlagLifecycleState.EXPIRED:
            stmt = stmt.where(
                sa.or_(
                    FeatureFlagDefinition.lifecycle_state == FeatureFlagLifecycleState.EXPIRED.value,
                    sa.and_(
                        FeatureFlagDefinition.expires_at.is_not(None),
                        FeatureFlagDefinition.expires_at <= now,
                        FeatureFlagDefinition.lifecycle_state != FeatureFlagLifecycleState.RETIRED.value,
                    ),
                )
            )
        elif state == FeatureFlagLifecycleState.RETIRED:
            stmt = stmt.where(
                FeatureFlagDefinition.lifecycle_state == FeatureFlagLifecycleState.RETIRED.value
            )
        else:
            stmt = stmt.where(
                FeatureFlagDefinition.lifecycle_state == state.value,
                sa.or_(
                    FeatureFlagDefinition.expires_at.is_(None),
                    FeatureFlagDefinition.expires_at > now,
                ),
            )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_feature_flag_definition(
    session: AsyncSession,
    *,
    payload: FeatureFlagDefinitionCreateRequest,
    actor: ConfigAuditActor,
    request_id: str | None,
) -> FeatureFlagDefinition:
    existing = await session.get(FeatureFlagDefinition, payload.key)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Feature flag already exists"
        )
    _validate_expiration_horizon(
        payload.expires_at,
        override_max_horizon=payload.override_max_horizon,
        override_reason=payload.override_reason,
    )
    record = FeatureFlagDefinition(
        key=payload.key,
        owner=payload.owner,
        purpose=payload.purpose,
        expires_at=_ensure_timezone(payload.expires_at),
        lifecycle_state=payload.lifecycle_state.value,
    )
    session.add(record)
    await session.flush()
    await feature_flag_audit_service.audit_feature_flag_change(
        session,
        actor=actor,
        org_id=None,
        flag_key=record.key,
        action=FeatureFlagAuditAction.CREATE,
        before_state=None,
        after_state=_definition_snapshot(record),
        rollout_context=feature_flag_audit_service.build_rollout_context(
            enabled=None, targeting_rules=None, reason=payload.override_reason
        )
        if payload.override_max_horizon
        else None,
        request_id=request_id,
    )
    transition_action = _derive_transition_action(payload.lifecycle_state)
    if transition_action is not None:
        await feature_flag_audit_service.audit_feature_flag_change(
            session,
            actor=actor,
            org_id=None,
            flag_key=record.key,
            action=transition_action,
            before_state={"lifecycle_state": FeatureFlagLifecycleState.DRAFT.value},
            after_state=_definition_snapshot(record),
            rollout_context=None,
            request_id=request_id,
        )
    return record


async def update_feature_flag_definition(
    session: AsyncSession,
    *,
    record: FeatureFlagDefinition,
    payload: FeatureFlagDefinitionUpdateRequest,
    actor: ConfigAuditActor,
    request_id: str | None,
) -> FeatureFlagDefinition:
    before_state = _definition_snapshot(record)
    if payload.expires_at is not None:
        _validate_expiration_horizon(
            payload.expires_at,
            override_max_horizon=payload.override_max_horizon,
            override_reason=payload.override_reason,
        )
        record.expires_at = _ensure_timezone(payload.expires_at)
    if payload.owner is not None:
        record.owner = payload.owner
    if payload.purpose is not None:
        record.purpose = payload.purpose
    transition_action: FeatureFlagAuditAction | None = None
    if payload.lifecycle_state is not None and payload.lifecycle_state.value != record.lifecycle_state:
        record.lifecycle_state = payload.lifecycle_state.value
        transition_action = _derive_transition_action(payload.lifecycle_state)
    await session.flush()
    await feature_flag_audit_service.audit_feature_flag_change(
        session,
        actor=actor,
        org_id=None,
        flag_key=record.key,
        action=FeatureFlagAuditAction.UPDATE,
        before_state=before_state,
        after_state=_definition_snapshot(record),
        rollout_context=feature_flag_audit_service.build_rollout_context(
            enabled=None, targeting_rules=None, reason=payload.override_reason
        )
        if payload.override_max_horizon
        else None,
        request_id=request_id,
    )
    if transition_action is not None:
        await feature_flag_audit_service.audit_feature_flag_change(
            session,
            actor=actor,
            org_id=None,
            flag_key=record.key,
            action=transition_action,
            before_state=before_state,
            after_state=_definition_snapshot(record),
            rollout_context=None,
            request_id=request_id,
        )
    return record


def resolve_effective_state(
    definition: FeatureFlagDefinition, *, now: datetime | None = None
) -> FeatureFlagLifecycleState:
    return _resolve_effective_state(definition, now=now)


def is_flag_mutable(definition: FeatureFlagDefinition, *, now: datetime | None = None) -> bool:
    effective_state = resolve_effective_state(definition, now=now)
    return effective_state not in {
        FeatureFlagLifecycleState.EXPIRED,
        FeatureFlagLifecycleState.RETIRED,
    }
