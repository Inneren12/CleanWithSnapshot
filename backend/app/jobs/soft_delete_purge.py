import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.soft_delete_purge import service as soft_delete_purge_service

logger = logging.getLogger(__name__)


async def run_soft_delete_purge(session: AsyncSession) -> dict[str, int]:
    results = await soft_delete_purge_service.run_soft_delete_purge(session)
    summary: dict[str, int] = {}
    for result in results:
        summary[f"{result.entity_type}_purged"] = result.deleted
        summary[f"{result.entity_type}_held"] = result.held
        logger.info(
            "soft_delete_purge_complete",
            extra={
                "extra": {
                    "entity_type": result.entity_type,
                    "deleted": result.deleted,
                    "held": result.held,
                    "grace_period_days": result.grace_period_days,
                    "status": result.status,
                }
            },
        )
    return summary
