from __future__ import annotations

from dataclasses import dataclass
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
_EVALUATION_CACHE: dict[str, datetime] = {}
# Prefer HTTP_422_UNPROCESSABLE_CONTENT to avoid deprecated HTTP_422_UNPROCESSABLE_ENTITY
HTTP_422_ENTITY = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


@dataclass(frozen=True)
class FeatureFlagRetirementCandidate:
    record: FeatureFlagDefinition
    reason: str
    eligible_since: datetime | None


def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def reset_evaluation_cache() -> None:
    _EVALUATION_CACHE.clear()


def _resolve_effective_state(
    definition: FeatureFlagDefinition, *, now: datetime | None = None
) -> FeatureFlagLifecycleState:
    now = _ensure_timezone(now or datetime.now(tz=timezone.utc))
    if definition.lifecycle_state == FeatureFlagLifecycleState.RETIRED.value:
        return FeatureFlagLifecycleState.RETIRED
    if definition.expires_at and _ensure_timezone(definition.expires_at) <= now:
        return FeatureFlagLifecycleState.EXPIRED
    return FeatureFlagLifecycleState(definition.lifecycle_state)


def _validate_override_reason(override_enabled: bool, override_reason: str | None) -> None:
    if override_enabled and not override_reason:
        raise HTTPException(
            status_code=HTTP_422_ENTITY,
            detail="override_reason is required when overrides are enabled",
        )


def _validate_expiration_horizon(
    expires_at: datetime, *, override_max_horizon: bool, override_reason: str | None
) -> None:
    _validate_override_reason(override_max_horizon, override_reason)
    now = _ensure_timezone(datetime.now(tz=timezone.utc))
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
        "pinned": definition.pinned,
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
    now = _ensure_timezone(datetime.now(tz=timezone.utc))
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


async def record_feature_flag_evaluation(
    session: AsyncSession,
    key: str,
    *,
    now: datetime | None = None,
    throttle_minutes: int | None = None,
) -> bool:
    if not key:
        return False
    should_commit = (
        not session.in_transaction()
        and not session.new
        and not session.dirty
        and not session.deleted
    )
    now = _ensure_timezone(now or datetime.now(tz=timezone.utc))
    throttle_minutes = (
        settings.feature_flag_evaluation_throttle_minutes
        if throttle_minutes is None
        else throttle_minutes
    )
    stmt = (
        sa.update(FeatureFlagDefinition)
        .where(FeatureFlagDefinition.key == key)
        .values(
            last_evaluated_at=now,
            evaluate_count=FeatureFlagDefinition.evaluate_count + 1,
        )
    )
    if throttle_minutes and throttle_minutes > 0:
        cutoff = now - timedelta(minutes=throttle_minutes)
        stmt = stmt.where(
            sa.or_(
                FeatureFlagDefinition.last_evaluated_at.is_(None),
                FeatureFlagDefinition.last_evaluated_at < cutoff,
            )
        )
    result = await session.execute(stmt)
    if should_commit:
        await session.commit()
    return bool(result.rowcount)


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
        pinned=payload.pinned,
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
    if payload.pinned is not None:
        record.pinned = payload.pinned
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


def _stale_condition(
    *,
    now: datetime,
    include_never: bool,
    inactive_days: int | None,
) -> tuple[sa.ColumnElement[bool] | None, datetime | None]:
    conditions: list[sa.ColumnElement[bool]] = []
    cutoff = None
    if include_never:
        conditions.append(FeatureFlagDefinition.last_evaluated_at.is_(None))
    if inactive_days is not None:
        cutoff = now - timedelta(days=inactive_days)
        conditions.append(
            sa.and_(
                FeatureFlagDefinition.last_evaluated_at.is_not(None),
                FeatureFlagDefinition.last_evaluated_at < cutoff,
            )
        )
    if not conditions:
        return None, cutoff
    return sa.or_(*conditions), cutoff


async def list_stale_feature_flag_definitions(
    session: AsyncSession,
    *,
    include_never: bool = True,
    inactive_days: int | None = None,
    max_evaluate_count: int | None = None,
    lifecycle_state: FeatureFlagLifecycleState | None = None,
    limit: int = 50,
    offset: int = 0,
    now: datetime | None = None,
) -> tuple[list[FeatureFlagDefinition], int, datetime | None]:
    now = _ensure_timezone(now or datetime.now(tz=timezone.utc))
    condition, cutoff = _stale_condition(
        now=now, include_never=include_never, inactive_days=inactive_days
    )
    if condition is None:
        return [], 0, cutoff

    stmt = select(FeatureFlagDefinition).where(
        condition, FeatureFlagDefinition.expires_at.is_not(None)
    )
    count_stmt = (
        select(sa.func.count())
        .select_from(FeatureFlagDefinition)
        .where(condition, FeatureFlagDefinition.expires_at.is_not(None))
    )

    if lifecycle_state is not None:
        state_value = lifecycle_state.value
        stmt = stmt.where(FeatureFlagDefinition.lifecycle_state == state_value)
        count_stmt = count_stmt.where(FeatureFlagDefinition.lifecycle_state == state_value)
    if max_evaluate_count is not None:
        stmt = stmt.where(FeatureFlagDefinition.evaluate_count <= max_evaluate_count)
        count_stmt = count_stmt.where(FeatureFlagDefinition.evaluate_count <= max_evaluate_count)

    stmt = stmt.order_by(
        FeatureFlagDefinition.last_evaluated_at.asc().nullsfirst(),
        FeatureFlagDefinition.evaluate_count.asc(),
        FeatureFlagDefinition.key.asc(),
    ).offset(offset).limit(limit)

    result = await session.execute(stmt)
    total = await session.scalar(count_stmt)
    return list(result.scalars().all()), int(total or 0), cutoff


async def stale_feature_flag_metrics_snapshot(
    session: AsyncSession,
    *,
    inactive_days: int,
    max_evaluate_count: int,
    expired_recent_days: int,
    now: datetime | None = None,
) -> dict[str, int]:
    now = _ensure_timezone(now or datetime.now(tz=timezone.utc))
    cutoff = now - timedelta(days=inactive_days)
    expired_cutoff = now - timedelta(days=expired_recent_days)
    stale_never_stmt = select(sa.func.count()).select_from(FeatureFlagDefinition).where(
        FeatureFlagDefinition.last_evaluated_at.is_(None),
        FeatureFlagDefinition.evaluate_count <= max_evaluate_count,
    )
    stale_inactive_stmt = select(sa.func.count()).select_from(FeatureFlagDefinition).where(
        FeatureFlagDefinition.last_evaluated_at.is_not(None),
        FeatureFlagDefinition.last_evaluated_at < cutoff,
        FeatureFlagDefinition.evaluate_count <= max_evaluate_count,
    )
    expired_evaluated_stmt = select(sa.func.count()).select_from(FeatureFlagDefinition).where(
        FeatureFlagDefinition.lifecycle_state.in_(
            [
                FeatureFlagLifecycleState.EXPIRED.value,
                FeatureFlagLifecycleState.RETIRED.value,
            ]
        ),
        FeatureFlagDefinition.last_evaluated_at.is_not(None),
        FeatureFlagDefinition.last_evaluated_at >= expired_cutoff,
    )
    stale_never = await session.scalar(stale_never_stmt)
    stale_inactive = await session.scalar(stale_inactive_stmt)
    expired_evaluated = await session.scalar(expired_evaluated_stmt)
    return {
        "never": int(stale_never or 0),
        "inactive": int(stale_inactive or 0),
        "expired_evaluated": int(expired_evaluated or 0),
    }


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


def _recent_evaluation_cutoff(now: datetime, recent_evaluation_days: int | None) -> datetime | None:
    if recent_evaluation_days is None or recent_evaluation_days <= 0:
        return None
    return now - timedelta(days=recent_evaluation_days)


async def list_retirement_candidates(
    session: AsyncSession,
    *,
    retire_expired: bool,
    retire_stale_days: int | None,
    recent_evaluation_days: int | None,
    max_evaluate_count: int,
    now: datetime | None = None,
) -> list[FeatureFlagRetirementCandidate]:
    now = _ensure_timezone(now or datetime.now(tz=timezone.utc))
    recent_cutoff = _recent_evaluation_cutoff(now, recent_evaluation_days)
    candidates: dict[str, FeatureFlagRetirementCandidate] = {}

    if retire_expired:
        expired_stmt = select(FeatureFlagDefinition).where(
            FeatureFlagDefinition.lifecycle_state != FeatureFlagLifecycleState.RETIRED.value,
            FeatureFlagDefinition.expires_at.is_not(None),
            FeatureFlagDefinition.expires_at <= now,
            FeatureFlagDefinition.pinned.is_(False),
        )
        if recent_cutoff is not None:
            expired_stmt = expired_stmt.where(
                sa.or_(
                    FeatureFlagDefinition.last_evaluated_at.is_(None),
                    FeatureFlagDefinition.last_evaluated_at < recent_cutoff,
                )
            )
        expired_result = await session.execute(expired_stmt)
        for record in expired_result.scalars().all():
            candidates[record.key] = FeatureFlagRetirementCandidate(
                record=record,
                reason="expired",
                eligible_since=record.expires_at,
            )

    if retire_stale_days is not None and retire_stale_days > 0:
        condition, cutoff = _stale_condition(
            now=now, include_never=True, inactive_days=retire_stale_days
        )
        if condition is not None:
            stale_stmt = select(FeatureFlagDefinition).where(
                condition,
                FeatureFlagDefinition.lifecycle_state != FeatureFlagLifecycleState.RETIRED.value,
                FeatureFlagDefinition.lifecycle_state != FeatureFlagLifecycleState.DRAFT.value,
                FeatureFlagDefinition.pinned.is_(False),
                FeatureFlagDefinition.evaluate_count <= max_evaluate_count,
            )
            if recent_cutoff is not None:
                stale_stmt = stale_stmt.where(
                    sa.or_(
                        FeatureFlagDefinition.last_evaluated_at.is_(None),
                        FeatureFlagDefinition.last_evaluated_at < recent_cutoff,
                    )
                )
            stale_result = await session.execute(stale_stmt)
            for record in stale_result.scalars().all():
                if record.key in candidates:
                    continue
                candidates[record.key] = FeatureFlagRetirementCandidate(
                    record=record,
                    reason="stale",
                    eligible_since=cutoff,
                )

    return list(candidates.values())


async def retire_feature_flags(
    session: AsyncSession,
    *,
    candidates: list[FeatureFlagRetirementCandidate],
    actor: ConfigAuditActor,
    request_id: str | None = None,
) -> list[FeatureFlagDefinition]:
    retired: list[FeatureFlagDefinition] = []
    for candidate in candidates:
        record = candidate.record
        if record.lifecycle_state == FeatureFlagLifecycleState.RETIRED.value or record.pinned:
            continue
        before_state = _definition_snapshot(record)
        record.lifecycle_state = FeatureFlagLifecycleState.RETIRED.value
        await session.flush()
        await feature_flag_audit_service.audit_feature_flag_change(
            session,
            actor=actor,
            org_id=None,
            flag_key=record.key,
            action=FeatureFlagAuditAction.RETIRE,
            before_state=before_state,
            after_state=_definition_snapshot(record),
            rollout_context=feature_flag_audit_service.build_rollout_context(
                enabled=False,
                targeting_rules=None,
                reason=f"automation:{candidate.reason}",
            ),
            request_id=request_id,
        )
        retired.append(record)
    return retired
