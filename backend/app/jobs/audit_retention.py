import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit_retention import service as audit_retention_service
from app.settings import settings

logger = logging.getLogger(__name__)


async def run_audit_retention(session: AsyncSession) -> dict[str, int]:
    result = await audit_retention_service.run_audit_retention(
        session,
        dry_run=settings.audit_retention_dry_run,
        batch_size=settings.audit_retention_batch_size,
    )
    logger.info("audit_retention_job_complete", extra={"extra": result})
    return result
