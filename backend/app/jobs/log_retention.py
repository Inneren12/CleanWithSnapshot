import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.logs import service as log_retention_service

logger = logging.getLogger(__name__)


async def run_log_retention_daily(session: AsyncSession) -> dict[str, int]:
    result = await log_retention_service.purge_application_logs(session)
    logger.info(
        "log_retention_job_complete",
        extra={
            "extra": {
                "deleted": result.deleted,
                "retention_days": result.retention_days or 0,
                "status": result.status,
            }
        },
    )
    return {"deleted": result.deleted}
