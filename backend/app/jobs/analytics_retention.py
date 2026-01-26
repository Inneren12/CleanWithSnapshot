import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.analytics import retention as analytics_retention_service

logger = logging.getLogger(__name__)


async def run_analytics_retention_daily(session: AsyncSession) -> dict[str, int]:
    result = await analytics_retention_service.purge_raw_events(session)
    logger.info(
        "analytics_retention_job_complete",
        extra={
            "extra": {
                "deleted": result.deleted,
                "retention_days": result.retention_days or 0,
                "status": result.status,
            }
        },
    )
    return {"deleted": result.deleted}
