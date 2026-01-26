from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.admin_audit import service as admin_audit_service
from app.domain.data_rights.db_models import DataExportRequest
from app.domain.data_rights import service as data_rights_service
from app.infra.storage.backends import StorageBackend
from app.settings import settings

logger = logging.getLogger(__name__)


async def run_pending_data_exports(
    session: AsyncSession,
    *,
    storage_backend: StorageBackend | None = None,
    limit: int = 25,
) -> dict[str, int]:
    stmt = (
        select(DataExportRequest)
        .where(DataExportRequest.status.in_(("pending", "processing")))
        .order_by(DataExportRequest.created_at)
        .limit(limit)
    )
    result = await session.execute(stmt)
    requests = list(result.scalars().all())
    processed = 0
    completed = 0
    failed = 0
    for export_request in requests:
        processed += 1
        record = await data_rights_service.generate_data_export_bundle(
            session, export_request=export_request, storage_backend=storage_backend
        )
        if record.status == "completed":
            completed += 1
            await admin_audit_service.record_system_action(
                session,
                org_id=record.org_id,
                action="data_export_completed",
                resource_type="data_export",
                resource_id=str(record.export_id),
                context={
                    "request_id": record.request_id,
                    "subject_id": record.subject_id,
                    "subject_type": record.subject_type,
                    "subject_email": record.subject_email,
                    "completed_at": record.completed_at.isoformat() if record.completed_at else None,
                },
            )
        elif record.status == "failed":
            failed += 1
            await admin_audit_service.record_system_action(
                session,
                org_id=record.org_id,
                action="data_export_failed",
                resource_type="data_export",
                resource_id=str(record.export_id),
                context={
                    "request_id": record.request_id,
                    "subject_id": record.subject_id,
                    "subject_type": record.subject_type,
                    "subject_email": record.subject_email,
                    "error_code": record.error_code,
                },
            )
    if requests:
        await session.commit()
    return {"processed": processed, "completed": completed, "failed": failed}


async def run_data_export_retention(
    session: AsyncSession,
    *,
    storage_backend: StorageBackend | None = None,
) -> dict[str, int]:
    result = await data_rights_service.purge_expired_exports(
        session, storage_backend=storage_backend
    )
    if result.get("deleted", 0):
        await admin_audit_service.record_system_action(
            session,
            org_id=settings.default_org_id,
            action="data_export_retention_purge",
            resource_type="data_export",
            resource_id=None,
            context={
                "deleted": result.get("deleted", 0),
                "processed": result.get("processed", 0),
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            },
        )
    return result
