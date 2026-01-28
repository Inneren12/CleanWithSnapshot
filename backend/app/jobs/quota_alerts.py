from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feature_modules import service as feature_service
from app.domain.notifications_center import db_models as notifications_models
from app.domain.org_settings import service as org_settings_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import Organization
from app.domain.storage_quota import service as storage_quota_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuotaThreshold:
    ratio: float
    label: str
    priority: str


THRESHOLDS = (
    QuotaThreshold(ratio=0.8, label="80", priority="MEDIUM"),
    QuotaThreshold(ratio=0.9, label="90", priority="HIGH"),
)

EVENT_TYPE = "org_quota_warning"


def _period_key(now: datetime) -> str:
    return now.strftime("%Y-%m")


def _format_bytes(value: int) -> str:
    size = float(max(value, 0))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def _notification_exists(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity_type: str,
    entity_id: str,
) -> bool:
    stmt = (
        sa.select(notifications_models.NotificationEvent.id)
        .where(
            notifications_models.NotificationEvent.org_id == org_id,
            notifications_models.NotificationEvent.type == EVENT_TYPE,
            notifications_models.NotificationEvent.entity_type == entity_type,
            notifications_models.NotificationEvent.entity_id == entity_id,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _emit_notification(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    priority: str,
    title: str,
    body: str,
    entity_type: str,
    entity_id: str,
) -> bool:
    enabled = await feature_service.effective_feature_enabled(
        session, org_id, "module.notifications_center"
    )
    if not enabled:
        return False

    if await _notification_exists(
        session, org_id=org_id, entity_type=entity_type, entity_id=entity_id
    ):
        return False

    event = notifications_models.NotificationEvent(
        org_id=org_id,
        priority=priority,
        type=EVENT_TYPE,
        title=title,
        body=body,
        entity_type=entity_type,
        entity_id=entity_id,
        action_href="/admin/settings/org",
        action_kind="open_settings",
    )
    session.add(event)
    await session.flush()
    return True


async def _check_user_quota(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    period: str,
) -> int:
    snapshot = await saas_service.get_org_user_quota_snapshot(session, org_id)
    if snapshot.max_users is None or snapshot.max_users <= 0:
        return 0

    usage_ratio = snapshot.current_users_count / snapshot.max_users
    sent = 0
    for threshold in THRESHOLDS:
        if usage_ratio < threshold.ratio:
            continue
        percent = int(threshold.ratio * 100)
        entity_id = f"{threshold.label}:{period}"
        title = f"User quota at {percent}%"
        body = (
            f"Organization has {snapshot.current_users_count} of {snapshot.max_users} "
            "active users. Consider removing inactive users or increasing the quota."
        )
        if await _emit_notification(
            session,
            org_id=org_id,
            priority=threshold.priority,
            title=title,
            body=body,
            entity_type="org_user_quota",
            entity_id=entity_id,
        ):
            sent += 1
    return sent


async def _check_storage_quota(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    period: str,
) -> int:
    snapshot = await storage_quota_service.get_org_storage_quota_snapshot(session, org_id)
    if snapshot.max_storage_bytes is None or snapshot.max_storage_bytes <= 0:
        return 0

    used_total = snapshot.storage_bytes_used + snapshot.storage_bytes_pending
    usage_ratio = used_total / snapshot.max_storage_bytes
    sent = 0
    for threshold in THRESHOLDS:
        if usage_ratio < threshold.ratio:
            continue
        percent = int(threshold.ratio * 100)
        entity_id = f"{threshold.label}:{period}"
        title = f"Storage quota at {percent}%"
        body = (
            "Organization has used "
            f"{_format_bytes(used_total)} of {_format_bytes(snapshot.max_storage_bytes)} "
            "storage. Consider deleting unused files or increasing the quota."
        )
        if await _emit_notification(
            session,
            org_id=org_id,
            priority=threshold.priority,
            title=title,
            body=body,
            entity_type="org_storage_quota",
            entity_id=entity_id,
        ):
            sent += 1
    return sent


async def run_quota_alerts(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    period = _period_key(now)

    result = await session.execute(sa.select(Organization.org_id))
    org_ids = [row[0] for row in result.all()]

    checked = 0
    sent = 0
    for org_id in org_ids:
        checked += 1
        await org_settings_service.get_or_create_org_settings(session, org_id)
        sent += await _check_user_quota(session, org_id, period=period)
        sent += await _check_storage_quota(session, org_id, period=period)

    await session.commit()
    logger.info("quota_alerts_run", extra={"extra": {"checked": checked, "sent": sent}})
    return {"checked": checked, "sent": sent}
