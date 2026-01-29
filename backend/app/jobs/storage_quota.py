from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, AdminRole
from app.domain.admin_audit import service as admin_audit_service
from app.domain.bookings.db_models import BookingPhoto, OrderPhoto
from app.domain.documents.db_models import Document
from app.domain.org_settings.db_models import OrganizationSettings
from app.domain.org_settings import service as org_settings_service
from app.domain.storage_quota.db_models import OrgStorageReservation
from app.domain.storage_quota.service import StorageReservationStatus
from app.infra.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)


def _now_for_db(session: AsyncSession) -> datetime:
    now = datetime.now(timezone.utc)
    bind = session.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "") if bind else ""
    if dialect_name == "sqlite":
        return now.replace(tzinfo=None)
    return now


async def run_storage_quota_cleanup(
    session: AsyncSession,
    *,
    batch_size: int | None = None,
) -> dict[str, int]:
    limit = batch_size if batch_size is not None else settings.storage_quota_cleanup_batch_size
    now = _now_for_db(session)

    select_stmt = (
        sa.select(OrgStorageReservation.reservation_id)
        .where(OrgStorageReservation.status == StorageReservationStatus.PENDING.value)
        .where(OrgStorageReservation.expires_at <= now)
        .order_by(OrgStorageReservation.expires_at)
    )
    if limit:
        select_stmt = select_stmt.limit(limit)
    result = await session.execute(select_stmt)
    reservation_ids = [row[0] for row in result.all()]

    expired = 0
    if reservation_ids:
        update_stmt = (
            sa.update(OrgStorageReservation)
            .where(OrgStorageReservation.reservation_id.in_(reservation_ids))
            .values(status=StorageReservationStatus.EXPIRED.value, released_at=now)
        )
        update_result = await session.execute(update_stmt)
        expired = int(update_result.rowcount or 0)
    await session.commit()

    pending_count = await session.scalar(
        sa.select(sa.func.count(OrgStorageReservation.reservation_id)).where(
            OrgStorageReservation.status == StorageReservationStatus.PENDING.value,
            OrgStorageReservation.expires_at > now,
        )
    )
    metrics.set_storage_reservations_pending(int(pending_count or 0))

    logger.info("storage_quota_cleanup", extra={"extra": {"expired": expired}})
    return {"expired": expired}


async def run_storage_quota_reconciliation(session: AsyncSession) -> dict[str, int]:
    usage: dict = {}

    def _merge(org_id, value) -> None:
        usage[org_id] = usage.get(org_id, 0) + int(value or 0)

    order_rows = await session.execute(
        sa.select(OrderPhoto.org_id, sa.func.coalesce(sa.func.sum(OrderPhoto.size_bytes), 0))
        .group_by(OrderPhoto.org_id)
    )
    for org_id, total in order_rows.all():
        _merge(org_id, total)

    booking_rows = await session.execute(
        sa.select(BookingPhoto.org_id, sa.func.coalesce(sa.func.sum(BookingPhoto.size_bytes), 0))
        .group_by(BookingPhoto.org_id)
    )
    for org_id, total in booking_rows.all():
        _merge(org_id, total)

    document_rows = await session.execute(
        sa.select(Document.org_id, sa.func.coalesce(sa.func.sum(sa.func.length(Document.pdf_bytes)), 0))
        .group_by(Document.org_id)
    )
    for org_id, total in document_rows.all():
        _merge(org_id, total)

    existing_rows = await session.execute(
        sa.select(OrganizationSettings.org_id, OrganizationSettings.storage_bytes_used)
    )

    reconciled = 0
    adjusted = 0
    identity = AdminIdentity(
        username="system",
        role=AdminRole.ADMIN,
        org_id=None,
        admin_id="system",
        auth_method="system",
    )
    existing_orgs = set()

    for org_id, stored_used in existing_rows.all():
        existing_orgs.add(org_id)
        computed = usage.get(org_id, 0)
        reconciled += 1
        if int(stored_used or 0) != int(computed or 0):
            settings_record = await org_settings_service.get_or_create_org_settings(session, org_id)
            before = settings_record.storage_bytes_used
            settings_record.storage_bytes_used = int(computed or 0)
            adjusted += 1
            await admin_audit_service.record_action(
                session,
                identity=identity,
                org_id=org_id,
                action="storage_usage_reconciled",
                resource_type="storage",
                resource_id=str(org_id),
                before={"storage_bytes_used": before},
                after={"storage_bytes_used": settings_record.storage_bytes_used},
            )

    for org_id, computed in usage.items():
        if org_id in existing_orgs:
            continue
        settings_record = await org_settings_service.get_or_create_org_settings(session, org_id)
        settings_record.storage_bytes_used = int(computed or 0)
        adjusted += 1
        await admin_audit_service.record_action(
            session,
            identity=identity,
            org_id=org_id,
            action="storage_usage_reconciled",
            resource_type="storage",
            resource_id=str(org_id),
            before={"storage_bytes_used": None},
            after={"storage_bytes_used": settings_record.storage_bytes_used},
        )

    await session.commit()
    metrics.set_storage_bytes_used(sum(usage.values()))

    pending_count = await session.scalar(
        sa.select(sa.func.count(OrgStorageReservation.reservation_id)).where(
            OrgStorageReservation.status == StorageReservationStatus.PENDING.value,
            OrgStorageReservation.expires_at > _now_for_db(session),
        )
    )
    metrics.set_storage_reservations_pending(int(pending_count or 0))

    logger.info(
        "storage_quota_reconciliation",
        extra={"extra": {"reconciled": reconciled, "adjusted": adjusted}},
    )
    return {"reconciled": reconciled, "adjusted": adjusted}
