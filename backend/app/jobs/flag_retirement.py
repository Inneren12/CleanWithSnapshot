from __future__ import annotations

from datetime import datetime, timezone
import logging

from app.domain.config_audit import service as config_audit_service
from app.domain.feature_flags import service as feature_flag_service
from app.settings import settings

logger = logging.getLogger(__name__)


async def run_feature_flag_retirement(session, *, dry_run: bool | None = None) -> dict[str, int]:
    now = datetime.now(tz=timezone.utc)
    resolved_dry_run = settings.flag_retire_dry_run if dry_run is None else dry_run
    retire_stale_days = settings.flag_retire_stale_days
    if retire_stale_days is not None and retire_stale_days <= 0:
        retire_stale_days = None
    recent_eval_days = settings.flag_retire_recent_evaluation_days
    if recent_eval_days is not None and recent_eval_days <= 0:
        recent_eval_days = None

    candidates = await feature_flag_service.list_retirement_candidates(
        session,
        retire_expired=settings.flag_retire_expired,
        retire_stale_days=retire_stale_days,
        recent_evaluation_days=recent_eval_days,
        max_evaluate_count=settings.feature_flag_stale_max_evaluate_count,
        now=now,
    )
    expired_count = sum(1 for candidate in candidates if candidate.reason == "expired")
    stale_count = len(candidates) - expired_count

    logger.info(
        "feature_flag_retirement_candidates",
        extra={
            "extra": {
                "count": len(candidates),
                "dry_run": resolved_dry_run,
                "expired": expired_count,
                "stale": stale_count,
                "flags": [
                    {"key": candidate.record.key, "reason": candidate.reason}
                    for candidate in candidates
                ],
            }
        },
    )

    if resolved_dry_run or not candidates:
        return {
            "candidates": len(candidates),
            "retired": 0,
            "expired_candidates": expired_count,
            "stale_candidates": stale_count,
            "dry_run": int(resolved_dry_run),
        }

    retired = await feature_flag_service.retire_feature_flags(
        session,
        candidates=candidates,
        actor=config_audit_service.automation_actor("feature-flag-retirement"),
    )
    await session.commit()
    return {
        "candidates": len(candidates),
        "retired": len(retired),
        "expired_candidates": expired_count,
        "stale_candidates": stale_count,
        "dry_run": int(resolved_dry_run),
    }
