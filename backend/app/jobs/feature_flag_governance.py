from __future__ import annotations

from app.domain.feature_flags import service as feature_flag_service
from app.infra.metrics import metrics
from app.settings import settings


async def run_feature_flag_governance(session) -> dict[str, int]:
    snapshot = await feature_flag_service.stale_feature_flag_metrics_snapshot(
        session,
        inactive_days=settings.feature_flag_stale_inactive_days,
        max_evaluate_count=settings.feature_flag_stale_max_evaluate_count,
        expired_recent_days=settings.feature_flag_expired_recent_days,
    )
    metrics.record_feature_flag_stale_counts(snapshot)
    return {
        "stale_never": snapshot.get("never", 0),
        "stale_inactive": snapshot.get("inactive", 0),
        "expired_evaluated": snapshot.get("expired_evaluated", 0),
    }
