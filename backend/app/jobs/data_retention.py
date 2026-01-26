import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.analytics import retention as analytics_retention_service
from app.domain.data_retention import RetentionCategory, enforce_retention

logger = logging.getLogger(__name__)


async def _run_categories(
    session: AsyncSession,
    categories: list[RetentionCategory],
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    results: dict[str, int] = {}
    for category in categories:
        result = await enforce_retention(session, category=category, now=now)
        results[category.value] = result.deleted
        logger.info(
            "data_retention_category_complete",
            extra={
                "extra": {
                    "category": category.value,
                    "deleted": result.deleted,
                    "retention_days": result.retention_days,
                    "status": result.status,
                }
            },
        )
    return results


async def run_data_retention_daily(session: AsyncSession) -> dict[str, int]:
    result = await analytics_retention_service.purge_raw_events(session)
    return {"analytics_events": result.deleted}


async def run_data_retention_weekly(session: AsyncSession) -> dict[str, int]:
    return await _run_categories(
        session,
        [
            RetentionCategory.SOFT_DELETED_ENTITIES,
            RetentionCategory.AUDIT_LOGS,
        ],
    )
