from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminRole
# Lazy import to avoid cycle:
# storage_quota.service -> admin_audit.service -> admin_audit.db_models -> infra.db -> infra.models -> storage_quota.db_models -> storage_quota.service
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.domain.admin_audit import service as admin_audit_service
else:
    # We will import inside function
    pass

from app.domain.org_settings import service as org_settings_service
from app.domain.org_settings.db_models import OrganizationSettings
from app.domain.storage_quota.db_models import OrgStorageReservation
from app.infra.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)


def _is_sqlite(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return getattr(getattr(bind, "dialect", None), "name", "") == "sqlite"


async def _acquire_sqlite_write_lock(session: AsyncSession) -> None:
    if not _is_sqlite(session):
        return
    if session.in_transaction():
        return
    await session.execute(sa.text("BEGIN IMMEDIATE"))


class StorageReservationStatus(str, Enum):
    PENDING = "pending"
    FINALIZED = "finalized"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass(frozen=True)
class OrgStorageQuotaSnapshot:
    org_id: uuid.UUID
    storage_bytes_used: int
    storage_bytes_pending: int
    max_storage_bytes: int | None

    @property
    def remaining_bytes(self) -> int | None:
        if self.max_storage_bytes is None:
            return None
        return max(self.max_storage_bytes - (self.storage_bytes_used + self.storage_bytes_pending), 0)


@dataclass(frozen=True)
class StorageReservation:
    reservation_id: uuid.UUID
    org_id: uuid.UUID
    bytes_reserved: int
    expires_at: datetime
    status: StorageReservationStatus
    resource_type: str | None
    resource_id: str | None


class OrgStorageQuotaExceeded(Exception):
    def __init__(self, snapshot: OrgStorageQuotaSnapshot, requested_bytes: int) -> None:
        super().__init__("org_storage_quota_exceeded")
        self.snapshot = snapshot
        self.requested_bytes = requested_bytes


def _system_identity(org_id: uuid.UUID) -> AdminIdentity:
    return AdminIdentity(
        username="system",
        role=AdminRole.ADMIN,
        org_id=org_id,
        admin_id="system",
        auth_method="system",
    )


def _snapshot(
    org_id: uuid.UUID,
    *,
    storage_bytes_used: int,
    storage_bytes_pending: int,
    max_storage_bytes: int | None,
) -> OrgStorageQuotaSnapshot:
    return OrgStorageQuotaSnapshot(
        org_id=org_id,
        storage_bytes_used=int(storage_bytes_used or 0),
        storage_bytes_pending=int(storage_bytes_pending or 0),
        max_storage_bytes=max_storage_bytes,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now_for_db(session: AsyncSession) -> datetime:
    now = datetime.now(timezone.utc)
    bind = session.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "") if bind else ""
    if dialect_name == "sqlite":
        return now.replace(tzinfo=None)
    return now


async def _lock_org_settings(session: AsyncSession, org_id: uuid.UUID) -> OrganizationSettings:
    await _acquire_sqlite_write_lock(session)
    await org_settings_service.get_or_create_org_settings(session, org_id)
    result = await session.execute(
        sa.select(OrganizationSettings)
        .where(OrganizationSettings.org_id == org_id)
        .with_for_update()
    )
    record = result.scalar_one()
    if record.storage_bytes_used is None:
        record.storage_bytes_used = 0
    return record


async def _pending_bytes(session: AsyncSession, org_id: uuid.UUID, now: datetime) -> int:
    stmt = (
        sa.select(sa.func.coalesce(sa.func.sum(OrgStorageReservation.bytes_reserved), 0))
        .where(OrgStorageReservation.org_id == org_id)
        .where(OrgStorageReservation.status == StorageReservationStatus.PENDING.value)
        .where(OrgStorageReservation.expires_at > now)
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def _expire_pending_reservations(session: AsyncSession, org_id: uuid.UUID, now: datetime) -> int:
    stmt = (
        sa.update(OrgStorageReservation)
        .where(OrgStorageReservation.org_id == org_id)
        .where(OrgStorageReservation.status == StorageReservationStatus.PENDING.value)
        .where(OrgStorageReservation.expires_at <= now)
        .values(status=StorageReservationStatus.EXPIRED.value, released_at=now)
    )
    result = await session.execute(stmt)
    return int(result.rowcount or 0)


async def get_org_storage_quota_snapshot(
    session: AsyncSession, org_id: uuid.UUID
) -> OrgStorageQuotaSnapshot:
    now = _now_for_db(session)
    record = await org_settings_service.get_or_create_org_settings(session, org_id)
    pending = await _pending_bytes(session, org_id, now)
    return _snapshot(
        org_id,
        # Invariant: pending tracks reserved bytes; used tracks finalized bytes.
        storage_bytes_used=int(record.storage_bytes_used or 0),
        storage_bytes_pending=pending,
        max_storage_bytes=record.max_storage_bytes,
    )


async def reserve_bytes(
    session: AsyncSession,
    org_id: uuid.UUID,
    bytes_requested: int,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    expires_in_seconds: int | None = None,
    audit_identity: AdminIdentity | Any | None = None,
) -> StorageReservation:
    if bytes_requested < 0:
        raise ValueError("bytes_requested must be non-negative")

    record = await _lock_org_settings(session, org_id)
    now = _now_for_db(session)
    await _expire_pending_reservations(session, org_id, now)
    used = int(record.storage_bytes_used or 0)
    pending = await _pending_bytes(session, org_id, now)

    if record.max_storage_bytes is not None and used + pending + bytes_requested > record.max_storage_bytes:
        from app.domain.admin_audit import service as admin_audit_service
        snapshot = await get_org_storage_quota_snapshot(session, org_id)
        identity = audit_identity or _system_identity(org_id)
        await admin_audit_service.record_action(
            session,
            identity=identity,  # type: ignore[arg-type]
            org_id=org_id,
            action="org_storage_quota_rejected",
            resource_type=resource_type or "storage",
            resource_id=resource_id,
            before=None,
            after={
                "bytes_requested": bytes_requested,
                "storage_bytes_used": snapshot.storage_bytes_used,
                "storage_bytes_pending": snapshot.storage_bytes_pending,
                "max_storage_bytes": snapshot.max_storage_bytes,
                "remaining_bytes": snapshot.remaining_bytes,
            },
        )
        logger.warning(
            "org_storage_quota_rejected",
            extra={
                "extra": {
                    "org_id": str(org_id),
                    "reason": "hard_limit",
                    "resource_type": resource_type or "storage",
                    "resource_id": resource_id,
                    "bytes_requested": bytes_requested,
                    "storage_bytes_used": snapshot.storage_bytes_used,
                    "storage_bytes_pending": snapshot.storage_bytes_pending,
                    "max_storage_bytes": snapshot.max_storage_bytes,
                    "remaining_bytes": snapshot.remaining_bytes,
                }
            },
        )
        metrics.record_org_storage_quota_rejection("hard_limit")
        raise OrgStorageQuotaExceeded(snapshot, bytes_requested)

    expires_in = expires_in_seconds or settings.storage_quota_reservation_ttl_seconds
    reservation = OrgStorageReservation(
        org_id=org_id,
        bytes_reserved=bytes_requested,
        status=StorageReservationStatus.PENDING.value,
        resource_type=resource_type,
        resource_id=resource_id,
        expires_at=now + timedelta(seconds=expires_in),
    )
    session.add(reservation)
    await session.flush()
    return StorageReservation(
        reservation_id=reservation.reservation_id,
        org_id=org_id,
        bytes_reserved=reservation.bytes_reserved,
        expires_at=_ensure_utc(reservation.expires_at),
        status=StorageReservationStatus.PENDING,
        resource_type=reservation.resource_type,
        resource_id=reservation.resource_id,
    )


async def extend_reservation(
    session: AsyncSession,
    reservation_id: uuid.UUID,
    bytes_delta: int,
    *,
    audit_identity: AdminIdentity | Any | None = None,
) -> StorageReservation:
    if bytes_delta < 0:
        raise ValueError("bytes_delta must be non-negative")

    now = _now_for_db(session)
    result = await session.execute(
        sa.select(OrgStorageReservation)
        .where(OrgStorageReservation.reservation_id == reservation_id)
        .with_for_update()
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise ValueError("reservation_not_found")
    if reservation.status == StorageReservationStatus.FINALIZED.value:
        raise ValueError("reservation_finalized")
    if reservation.status == StorageReservationStatus.RELEASED.value:
        raise ValueError("reservation_released")

    await _expire_pending_reservations(session, reservation.org_id, now)
    if reservation.status != StorageReservationStatus.PENDING.value:
        raise ValueError("reservation_not_pending")

    record = await _lock_org_settings(session, reservation.org_id)
    pending = await _pending_bytes(session, reservation.org_id, now)
    used = int(record.storage_bytes_used or 0)
    if record.max_storage_bytes is not None and used + pending + bytes_delta > record.max_storage_bytes:
        from app.domain.admin_audit import service as admin_audit_service
        snapshot = await get_org_storage_quota_snapshot(session, reservation.org_id)
        identity = audit_identity or _system_identity(reservation.org_id)
        await admin_audit_service.record_action(
            session,
            identity=identity,  # type: ignore[arg-type]
            org_id=reservation.org_id,
            action="org_storage_quota_rejected",
            resource_type=reservation.resource_type or "storage",
            resource_id=reservation.resource_id,
            before=None,
            after={
                "bytes_requested": bytes_delta,
                "storage_bytes_used": snapshot.storage_bytes_used,
                "storage_bytes_pending": snapshot.storage_bytes_pending,
                "max_storage_bytes": snapshot.max_storage_bytes,
                "remaining_bytes": snapshot.remaining_bytes,
            },
        )
        logger.warning(
            "org_storage_quota_rejected",
            extra={
                "extra": {
                    "org_id": str(reservation.org_id),
                    "reason": "hard_limit",
                    "resource_type": reservation.resource_type or "storage",
                    "resource_id": reservation.resource_id,
                    "bytes_requested": bytes_delta,
                    "storage_bytes_used": snapshot.storage_bytes_used,
                    "storage_bytes_pending": snapshot.storage_bytes_pending,
                    "max_storage_bytes": snapshot.max_storage_bytes,
                    "remaining_bytes": snapshot.remaining_bytes,
                }
            },
        )
        metrics.record_org_storage_quota_rejection("hard_limit")
        raise OrgStorageQuotaExceeded(snapshot, bytes_delta)

    reservation.bytes_reserved += bytes_delta
    await session.flush()
    return StorageReservation(
        reservation_id=reservation.reservation_id,
        org_id=reservation.org_id,
        bytes_reserved=reservation.bytes_reserved,
        expires_at=_ensure_utc(reservation.expires_at),
        status=StorageReservationStatus.PENDING,
        resource_type=reservation.resource_type,
        resource_id=reservation.resource_id,
    )


async def finalize_reservation(
    session: AsyncSession,
    reservation_id: uuid.UUID,
    actual_bytes: int,
    *,
    audit_identity: AdminIdentity | Any | None = None,
) -> StorageReservation:
    if actual_bytes <= 0:
        raise ValueError("actual_bytes must be positive")

    now = _now_for_db(session)
    result = await session.execute(
        sa.select(OrgStorageReservation)
        .where(OrgStorageReservation.reservation_id == reservation_id)
        .with_for_update()
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise ValueError("reservation_not_found")
    if reservation.status == StorageReservationStatus.FINALIZED.value:
        return StorageReservation(
            reservation_id=reservation.reservation_id,
            org_id=reservation.org_id,
            bytes_reserved=reservation.bytes_reserved,
            expires_at=_ensure_utc(reservation.expires_at),
            status=StorageReservationStatus.FINALIZED,
            resource_type=reservation.resource_type,
            resource_id=reservation.resource_id,
        )
    if reservation.status == StorageReservationStatus.RELEASED.value:
        raise ValueError("reservation_released")

    record = await _lock_org_settings(session, reservation.org_id)
    await _expire_pending_reservations(session, reservation.org_id, now)
    total_used = int(record.storage_bytes_used or 0)
    pending_now = await _pending_bytes(session, reservation.org_id, now)
    pending_released = (
        reservation.bytes_reserved if reservation.status == StorageReservationStatus.PENDING.value else 0
    )
    projected_total = total_used + (pending_now - pending_released) + actual_bytes

    if record.max_storage_bytes is not None and projected_total > record.max_storage_bytes:
        from app.domain.admin_audit import service as admin_audit_service
        snapshot = _snapshot(
            reservation.org_id,
            storage_bytes_used=total_used,
            storage_bytes_pending=pending_now,
            max_storage_bytes=record.max_storage_bytes,
        )
        identity = audit_identity or _system_identity(reservation.org_id)
        await admin_audit_service.record_action(
            session,
            identity=identity,  # type: ignore[arg-type]
            org_id=reservation.org_id,
            action="org_storage_quota_finalize_rejected",
            resource_type=reservation.resource_type or "storage",
            resource_id=reservation.resource_id,
            before=None,
            after={
                "bytes_reserved": reservation.bytes_reserved,
                "actual_bytes": actual_bytes,
                "storage_bytes_used": snapshot.storage_bytes_used,
                "storage_bytes_pending": snapshot.storage_bytes_pending,
                "max_storage_bytes": snapshot.max_storage_bytes,
                "remaining_bytes": snapshot.remaining_bytes,
            },
        )
        logger.warning(
            "org_storage_quota_rejected",
            extra={
                "extra": {
                    "org_id": str(reservation.org_id),
                    "reason": "finalize_limit",
                    "resource_type": reservation.resource_type or "storage",
                    "resource_id": reservation.resource_id,
                    "bytes_reserved": reservation.bytes_reserved,
                    "actual_bytes": actual_bytes,
                    "storage_bytes_used": snapshot.storage_bytes_used,
                    "storage_bytes_pending": snapshot.storage_bytes_pending,
                    "max_storage_bytes": snapshot.max_storage_bytes,
                    "remaining_bytes": snapshot.remaining_bytes,
                }
            },
        )
        metrics.record_org_storage_quota_rejection("finalize_limit")
        raise OrgStorageQuotaExceeded(snapshot, actual_bytes)

    if reservation.status in {StorageReservationStatus.PENDING.value, StorageReservationStatus.EXPIRED.value}:
        record.storage_bytes_used = total_used + actual_bytes
    await session.execute(
        sa.update(OrgStorageReservation)
        .where(OrgStorageReservation.reservation_id == reservation.reservation_id)
        .values(
            status=StorageReservationStatus.FINALIZED.value,
            bytes_finalized=actual_bytes,
            finalized_at=now,
        )
    )

    if reservation.bytes_reserved != actual_bytes:
        from app.domain.admin_audit import service as admin_audit_service
        identity = audit_identity or _system_identity(reservation.org_id)
        await admin_audit_service.record_action(
            session,
            identity=identity,  # type: ignore[arg-type]
            org_id=reservation.org_id,
            action="storage_reservation_size_adjusted",
            resource_type=reservation.resource_type or "storage",
            resource_id=reservation.resource_id,
            before={
                "bytes_reserved": reservation.bytes_reserved,
            },
            after={
                "bytes_finalized": actual_bytes,
                "delta_bytes": actual_bytes - reservation.bytes_reserved,
            },
        )

    return StorageReservation(
        reservation_id=reservation.reservation_id,
        org_id=reservation.org_id,
        bytes_reserved=reservation.bytes_reserved,
        expires_at=_ensure_utc(reservation.expires_at),
        status=StorageReservationStatus.FINALIZED,
        resource_type=reservation.resource_type,
        resource_id=reservation.resource_id,
    )


async def release_reservation(
    session: AsyncSession,
    reservation_id: uuid.UUID,
    *,
    reason: str | None = None,
    audit_identity: AdminIdentity | Any | None = None,
) -> StorageReservation:
    now = _now_for_db(session)
    result = await session.execute(
        sa.select(OrgStorageReservation)
        .where(OrgStorageReservation.reservation_id == reservation_id)
        .with_for_update()
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise ValueError("reservation_not_found")
    if reservation.status in {
        StorageReservationStatus.RELEASED.value,
        StorageReservationStatus.FINALIZED.value,
    }:
        return StorageReservation(
            reservation_id=reservation.reservation_id,
            org_id=reservation.org_id,
            bytes_reserved=reservation.bytes_reserved,
            expires_at=_ensure_utc(reservation.expires_at),
            status=StorageReservationStatus(reservation.status),
            resource_type=reservation.resource_type,
            resource_id=reservation.resource_id,
        )

    reservation.status = StorageReservationStatus.RELEASED.value
    reservation.released_at = now
    await session.flush()

    from app.domain.admin_audit import service as admin_audit_service
    identity = audit_identity or _system_identity(reservation.org_id)
    await admin_audit_service.record_action(
        session,
        identity=identity,  # type: ignore[arg-type]
        org_id=reservation.org_id,
        action="storage_reservation_released",
        resource_type=reservation.resource_type or "storage",
        resource_id=reservation.resource_id,
        before=None,
        after={
            "bytes_reserved": reservation.bytes_reserved,
            "reason": reason,
        },
    )

    return StorageReservation(
        reservation_id=reservation.reservation_id,
        org_id=reservation.org_id,
        bytes_reserved=reservation.bytes_reserved,
        expires_at=_ensure_utc(reservation.expires_at),
        status=StorageReservationStatus.RELEASED,
        resource_type=reservation.resource_type,
        resource_id=reservation.resource_id,
    )


async def decrement_storage_usage(
    session: AsyncSession,
    org_id: uuid.UUID,
    bytes_to_release: int,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    audit_identity: AdminIdentity | Any | None = None,
) -> OrgStorageQuotaSnapshot:
    if bytes_to_release <= 0:
        raise ValueError("bytes_to_release must be positive")

    record = await _lock_org_settings(session, org_id)
    used = int(record.storage_bytes_used or 0)
    new_used = max(used - bytes_to_release, 0)
    record.storage_bytes_used = new_used

    if used < bytes_to_release:
        from app.domain.admin_audit import service as admin_audit_service
        identity = audit_identity or _system_identity(org_id)
        await admin_audit_service.record_action(
            session,
            identity=identity,  # type: ignore[arg-type]
            org_id=org_id,
            action="storage_usage_underflow_adjusted",
            resource_type=resource_type or "storage",
            resource_id=resource_id,
            before={"storage_bytes_used": used},
            after={"storage_bytes_used": new_used, "bytes_released": bytes_to_release},
        )

    pending = await _pending_bytes(session, org_id, _now_for_db(session))
    await session.flush()
    return _snapshot(
        org_id,
        storage_bytes_used=new_used,
        storage_bytes_pending=pending,
        max_storage_bytes=record.max_storage_bytes,
    )
