from __future__ import annotations

from datetime import date, datetime, time, timezone

import sqlalchemy as sa
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.quality.db_models import QualityIssue, QualityIssueResponse
from app.domain.quality.schemas import QualityIssueSeverity


ACTIVE_STATUSES = {"open", "in_progress"}


def resolve_severity(
    explicit: str | None, rating: int | None
) -> QualityIssueSeverity:
    if explicit:
        normalized = explicit.strip().lower()
        if normalized in {
            QualityIssueSeverity.CRITICAL.value,
            QualityIssueSeverity.MEDIUM.value,
            QualityIssueSeverity.LOW.value,
        }:
            return QualityIssueSeverity(normalized)
    if rating is None:
        return QualityIssueSeverity.LOW
    if rating <= 2:
        return QualityIssueSeverity.CRITICAL
    if rating == 3:
        return QualityIssueSeverity.MEDIUM
    return QualityIssueSeverity.LOW


def _date_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _date_end(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _severity_filter(severity: QualityIssueSeverity) -> sa.ColumnElement[bool]:
    if severity == QualityIssueSeverity.CRITICAL:
        return sa.or_(
            QualityIssue.severity == severity.value,
            sa.and_(QualityIssue.severity.is_(None), QualityIssue.rating <= 2),
        )
    if severity == QualityIssueSeverity.MEDIUM:
        return sa.or_(
            QualityIssue.severity == severity.value,
            sa.and_(QualityIssue.severity.is_(None), QualityIssue.rating == 3),
        )
    return sa.or_(
        QualityIssue.severity == severity.value,
        sa.and_(
            QualityIssue.severity.is_(None),
            sa.or_(QualityIssue.rating.is_(None), QualityIssue.rating >= 4),
        ),
    )


async def list_quality_issues(
    session: AsyncSession,
    *,
    org_id,
    status: str | None = None,
    severity: QualityIssueSeverity | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    worker_id: int | None = None,
    client_id: str | None = None,
) -> list[QualityIssue]:
    filters: list[sa.ColumnElement[bool]] = [QualityIssue.org_id == org_id]
    if status:
        filters.append(QualityIssue.status == status)
    if severity:
        filters.append(_severity_filter(severity))
    if from_date:
        filters.append(QualityIssue.created_at >= _date_start(from_date))
    if to_date:
        filters.append(QualityIssue.created_at <= _date_end(to_date))
    if worker_id is not None:
        filters.append(QualityIssue.worker_id == worker_id)
    if client_id is not None:
        filters.append(QualityIssue.client_id == client_id)

    stmt = (
        sa.select(QualityIssue)
        .where(*filters)
        .order_by(QualityIssue.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_active_issues(
    session: AsyncSession,
    *,
    org_id,
    limit: int | None = None,
) -> list[QualityIssue]:
    filters = [
        QualityIssue.org_id == org_id,
        QualityIssue.status.in_(ACTIVE_STATUSES),
    ]
    stmt = (
        sa.select(QualityIssue)
        .where(*filters)
        .order_by(QualityIssue.created_at.desc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_quality_issue(
    session: AsyncSession,
    *,
    org_id,
    issue_id,
) -> QualityIssue | None:
    stmt = (
        sa.select(QualityIssue)
        .where(QualityIssue.org_id == org_id, QualityIssue.id == issue_id)
        .options(
            selectinload(QualityIssue.booking),
            selectinload(QualityIssue.worker),
            selectinload(QualityIssue.client),
            selectinload(QualityIssue.responses),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_issue_responses(
    session: AsyncSession,
    *,
    org_id,
    issue_id,
) -> list[QualityIssueResponse]:
    stmt = (
        sa.select(QualityIssueResponse)
        .where(
            QualityIssueResponse.org_id == org_id,
            QualityIssueResponse.issue_id == issue_id,
        )
        .order_by(QualityIssueResponse.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())
