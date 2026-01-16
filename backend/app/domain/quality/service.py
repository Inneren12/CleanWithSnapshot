from __future__ import annotations

from datetime import date, datetime, time, timezone

import sqlalchemy as sa
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientFeedback, ClientUser
from app.domain.quality.db_models import QualityIssue, QualityIssueResponse, QualityReviewReply
from app.domain.quality.schemas import QualityIssueSeverity
from app.domain.workers.db_models import Worker


REVIEW_REPLY_TEMPLATES = [
    {
        "key": "apology_followup",
        "label": "Apology + follow-up",
        "body": "Thanks for the feedback. We’re sorry this visit fell short and want to make it right. "
        "Our team will review the details and follow up shortly.",
    },
    {
        "key": "gratitude",
        "label": "Thanks for the review",
        "body": "Thank you for taking the time to share your feedback. We’re glad the team could help!",
    },
    {
        "key": "issue_triage",
        "label": "Issue triage request",
        "body": "Thanks for letting us know. We’re reviewing this and will reach out if we need any "
        "additional details.",
    },
]


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


def list_review_templates() -> list[dict[str, str]]:
    return [template.copy() for template in REVIEW_REPLY_TEMPLATES]


def _review_issue_exists(org_id) -> sa.ColumnElement[bool]:
    return sa.exists().where(
        QualityIssue.org_id == org_id,
        QualityIssue.booking_id == ClientFeedback.booking_id,
    )


async def list_quality_reviews(
    session: AsyncSession,
    *,
    org_id,
    stars: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    worker_id: int | None = None,
    client_id: str | None = None,
    has_issue: bool | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[tuple[ClientFeedback, Booking, ClientUser, Worker | None, bool]], int]:
    filters: list[sa.ColumnElement[bool]] = [ClientFeedback.org_id == org_id]
    if stars is not None:
        filters.append(ClientFeedback.rating == stars)
    if from_date:
        filters.append(ClientFeedback.created_at >= _date_start(from_date))
    if to_date:
        filters.append(ClientFeedback.created_at <= _date_end(to_date))
    if worker_id is not None:
        filters.append(Booking.assigned_worker_id == worker_id)
    if client_id is not None:
        filters.append(ClientFeedback.client_id == client_id)

    issue_exists = _review_issue_exists(org_id)
    if has_issue is True:
        filters.append(issue_exists)
    if has_issue is False:
        filters.append(sa.not_(issue_exists))

    page = max(page, 1)
    offset = (page - 1) * page_size

    count_stmt = (
        sa.select(sa.func.count(ClientFeedback.feedback_id))
        .select_from(ClientFeedback)
        .join(Booking, Booking.booking_id == ClientFeedback.booking_id)
        .join(ClientUser, ClientUser.client_id == ClientFeedback.client_id)
        .outerjoin(Worker, Worker.worker_id == Booking.assigned_worker_id)
        .where(*filters)
    )
    total = int((await session.execute(count_stmt)).scalar_one() or 0)

    stmt = (
        sa.select(
            ClientFeedback,
            Booking,
            ClientUser,
            Worker,
            issue_exists.label("has_issue"),
        )
        .join(Booking, Booking.booking_id == ClientFeedback.booking_id)
        .join(ClientUser, ClientUser.client_id == ClientFeedback.client_id)
        .outerjoin(Worker, Worker.worker_id == Booking.assigned_worker_id)
        .where(*filters)
        .order_by(ClientFeedback.created_at.desc())
        .limit(page_size)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    return (
        [
            (
                row[0],
                row[1],
                row[2],
                row[3],
                bool(row[4]),
            )
            for row in rows
        ],
        total,
    )


async def get_rating_distribution(
    session: AsyncSession,
    *,
    org_id,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[list[tuple[int, int]], int, float | None]:
    filters: list[sa.ColumnElement[bool]] = [ClientFeedback.org_id == org_id]
    if from_date:
        filters.append(ClientFeedback.created_at >= _date_start(from_date))
    if to_date:
        filters.append(ClientFeedback.created_at <= _date_end(to_date))

    summary_stmt = (
        sa.select(
            sa.func.count(ClientFeedback.feedback_id),
            sa.func.avg(ClientFeedback.rating),
        )
        .select_from(ClientFeedback)
        .where(*filters)
    )
    total_count, avg_rating = (await session.execute(summary_stmt)).one()
    total = int(total_count or 0)
    average = float(avg_rating) if avg_rating is not None else None

    distribution_stmt = (
        sa.select(ClientFeedback.rating, sa.func.count(ClientFeedback.feedback_id))
        .select_from(ClientFeedback)
        .where(*filters)
        .group_by(ClientFeedback.rating)
    )
    rows = (await session.execute(distribution_stmt)).all()
    distribution = [(int(rating), int(count)) for rating, count in rows if rating is not None]
    return distribution, total, average


async def create_review_reply(
    session: AsyncSession,
    *,
    org_id,
    feedback_id: int,
    template_key: str | None,
    message: str,
    created_by: str | None,
) -> QualityReviewReply:
    reply = QualityReviewReply(
        org_id=org_id,
        feedback_id=feedback_id,
        template_key=template_key,
        message=message,
        created_by=created_by,
    )
    session.add(reply)
    await session.flush()
    return reply
