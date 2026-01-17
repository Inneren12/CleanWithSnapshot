from __future__ import annotations

from datetime import date, datetime, time, timezone, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking, Team
from app.domain.clients.db_models import ClientFeedback, ClientUser
from app.domain.quality.db_models import (
    QualityIssue,
    QualityIssueResponse,
    QualityIssueTag,
    QualityReviewReply,
)
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

QUALITY_TAG_CATALOG: dict[str, str] = {
    "lateness": "Lateness",
    "missed_spots": "Missed spots",
    "communication": "Communication",
    "supplies": "Supplies",
    "time_overrun": "Time overrun",
}


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


def list_quality_tag_catalog() -> list[dict[str, str]]:
    return [
        {"tag_key": tag_key, "label": label}
        for tag_key, label in QUALITY_TAG_CATALOG.items()
    ]


def _dedupe_tag_keys(tag_keys: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for key in tag_keys:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def validate_tag_keys(tag_keys: list[str]) -> tuple[list[str], list[str]]:
    normalized = [key.strip() for key in tag_keys if key and key.strip()]
    deduped = _dedupe_tag_keys(normalized)
    allowed = set(QUALITY_TAG_CATALOG.keys())
    invalid = sorted({key for key in deduped if key not in allowed})
    return deduped, invalid


async def list_issue_tags(
    session: AsyncSession,
    *,
    org_id,
    issue_id,
) -> list[dict[str, str]]:
    position_order = sa.case(
        (QualityIssueTag.position.is_(None), 1),
        else_=0,
    )
    stmt = (
        sa.select(QualityIssueTag.tag_key)
        .where(
            QualityIssueTag.org_id == org_id,
            QualityIssueTag.issue_id == issue_id,
        )
        .order_by(position_order, QualityIssueTag.position.asc(), QualityIssueTag.tag_key.asc())
    )
    tag_keys = [row[0] for row in (await session.execute(stmt)).all()]
    return [
        {"tag_key": key, "label": QUALITY_TAG_CATALOG.get(key, key)}
        for key in tag_keys
    ]


async def replace_issue_tags(
    session: AsyncSession,
    *,
    org_id,
    issue_id,
    tag_keys: list[str],
) -> list[dict[str, str]]:
    deduped, invalid = validate_tag_keys(tag_keys)
    if invalid:
        raise ValueError(f"Invalid tag keys: {', '.join(invalid)}")
    await session.execute(
        sa.delete(QualityIssueTag).where(
            QualityIssueTag.org_id == org_id,
            QualityIssueTag.issue_id == issue_id,
        )
    )
    for index, tag_key in enumerate(deduped):
        session.add(
            QualityIssueTag(
                org_id=org_id,
                issue_id=issue_id,
                tag_key=tag_key,
                position=index,
            )
        )
    await session.commit()
    return [
        {"tag_key": key, "label": QUALITY_TAG_CATALOG.get(key, key)}
        for key in deduped
    ]


async def list_common_issue_tags(
    session: AsyncSession,
    *,
    org_id,
    from_date: date,
    to_date: date,
) -> list[dict[str, object]]:
    issue_filters = [
        QualityIssueTag.org_id == org_id,
        QualityIssue.created_at >= _date_start(from_date),
        QualityIssue.created_at <= _date_end(to_date),
    ]
    totals_stmt = (
        sa.select(
            QualityIssueTag.tag_key,
            sa.func.count(sa.distinct(QualityIssueTag.issue_id)).label("issue_count"),
        )
        .join(QualityIssue, QualityIssue.id == QualityIssueTag.issue_id)
        .where(*issue_filters)
        .group_by(QualityIssueTag.tag_key)
    )
    totals = {
        row.tag_key: row.issue_count for row in (await session.execute(totals_stmt)).all()
    }

    worker_stmt = (
        sa.select(
            QualityIssueTag.tag_key,
            QualityIssue.worker_id,
            Worker.name,
            sa.func.count(sa.distinct(QualityIssueTag.issue_id)).label("issue_count"),
        )
        .join(QualityIssue, QualityIssue.id == QualityIssueTag.issue_id)
        .join(Worker, Worker.worker_id == QualityIssue.worker_id, isouter=True)
        .where(
            *issue_filters,
            QualityIssue.worker_id.isnot(None),
            sa.or_(Worker.org_id == org_id, Worker.org_id.is_(None)),
        )
        .group_by(QualityIssueTag.tag_key, QualityIssue.worker_id, Worker.name)
    )
    worker_rows = (await session.execute(worker_stmt)).all()
    workers_by_tag: dict[str, list[dict[str, object]]] = {}
    for row in worker_rows:
        workers_by_tag.setdefault(row.tag_key, []).append(
            {
                "worker_id": row.worker_id,
                "worker_name": row.name,
                "issue_count": row.issue_count,
            }
        )

    results: list[dict[str, object]] = []
    for tag_key, issue_count in totals.items():
        workers = sorted(
            workers_by_tag.get(tag_key, []),
            key=lambda entry: (-int(entry["issue_count"]), str(entry["worker_name"] or "")),
        )
        results.append(
            {
                "tag_key": tag_key,
                "label": QUALITY_TAG_CATALOG.get(tag_key, tag_key),
                "issue_count": issue_count,
                "worker_count": len(workers),
                "workers": workers,
            }
        )
    results.sort(key=lambda entry: (-int(entry["issue_count"]), entry["tag_key"]))
    return results


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


def _previous_period_range(from_date: date, to_date: date) -> tuple[date, date]:
    span_days = (to_date - from_date).days + 1
    previous_end = from_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=max(span_days - 1, 0))
    return previous_start, previous_end


def _review_aggregate_stmt(
    *,
    org_id,
    from_date: date | None,
    to_date: date | None,
) -> sa.Select:
    filters: list[sa.ColumnElement[bool]] = [
        ClientFeedback.org_id == org_id,
        Booking.org_id == org_id,
        Booking.assigned_worker_id.is_not(None),
    ]
    if from_date:
        filters.append(ClientFeedback.created_at >= _date_start(from_date))
    if to_date:
        filters.append(ClientFeedback.created_at <= _date_end(to_date))
    return (
        sa.select(
            Booking.assigned_worker_id.label("worker_id"),
            sa.func.avg(ClientFeedback.rating).label("avg_rating"),
            sa.func.count(ClientFeedback.feedback_id).label("review_count"),
        )
        .select_from(ClientFeedback)
        .join(Booking, Booking.booking_id == ClientFeedback.booking_id)
        .where(*filters)
        .group_by(Booking.assigned_worker_id)
    )


def _complaint_aggregate_stmt(
    *,
    org_id,
    from_date: date | None,
    to_date: date | None,
) -> sa.Select:
    filters: list[sa.ColumnElement[bool]] = [
        QualityIssue.org_id == org_id,
        QualityIssue.worker_id.is_not(None),
    ]
    if from_date:
        filters.append(QualityIssue.created_at >= _date_start(from_date))
    if to_date:
        filters.append(QualityIssue.created_at <= _date_end(to_date))
    return (
        sa.select(
            QualityIssue.worker_id.label("worker_id"),
            sa.func.count(QualityIssue.id).label("complaint_count"),
        )
        .where(*filters)
        .group_by(QualityIssue.worker_id)
    )


async def _fetch_worker_quality_aggregates(
    session: AsyncSession,
    *,
    org_id,
    from_date: date | None,
    to_date: date | None,
) -> dict[int, dict[str, float | int | None]]:
    review_rows = (
        await session.execute(
            _review_aggregate_stmt(org_id=org_id, from_date=from_date, to_date=to_date)
        )
    ).all()
    complaint_rows = (
        await session.execute(
            _complaint_aggregate_stmt(org_id=org_id, from_date=from_date, to_date=to_date)
        )
    ).all()

    aggregates: dict[int, dict[str, float | int | None]] = {}
    for worker_id, avg_rating, review_count in review_rows:
        if worker_id is None:
            continue
        aggregates[int(worker_id)] = {
            "avg_rating": float(avg_rating) if avg_rating is not None else None,
            "review_count": int(review_count or 0),
            "complaint_count": 0,
        }

    for worker_id, complaint_count in complaint_rows:
        if worker_id is None:
            continue
        entry = aggregates.setdefault(
            int(worker_id),
            {"avg_rating": None, "review_count": 0, "complaint_count": 0},
        )
        entry["complaint_count"] = int(complaint_count or 0)

    return aggregates


async def list_worker_quality_leaderboard(
    session: AsyncSession,
    *,
    org_id,
    from_date: date,
    to_date: date,
    include_trend: bool = False,
) -> tuple[list[dict[str, object]], dict[int, dict[str, float | int | None]] | None]:
    current_aggregates = await _fetch_worker_quality_aggregates(
        session,
        org_id=org_id,
        from_date=from_date,
        to_date=to_date,
    )

    previous_aggregates: dict[int, dict[str, float | int | None]] | None = None
    if include_trend:
        previous_start, previous_end = _previous_period_range(from_date, to_date)
        previous_aggregates = await _fetch_worker_quality_aggregates(
            session,
            org_id=org_id,
            from_date=previous_start,
            to_date=previous_end,
        )

    workers_stmt = (
        sa.select(
            Worker.worker_id,
            Worker.name,
            Worker.team_id,
            Team.name.label("team_name"),
        )
        .select_from(Worker)
        .join(Team, Team.team_id == Worker.team_id)
        .where(Worker.org_id == org_id, Worker.is_active.is_(True))
        .order_by(Worker.name.asc())
    )
    worker_rows = (await session.execute(workers_stmt)).all()

    entries: list[dict[str, object]] = []
    for worker_id, worker_name, team_id, team_name in worker_rows:
        metrics = current_aggregates.get(int(worker_id))
        entries.append(
            {
                "worker_id": int(worker_id),
                "worker_name": worker_name,
                "team_id": int(team_id) if team_id is not None else None,
                "team_name": team_name,
                "average_rating": metrics.get("avg_rating") if metrics else None,
                "review_count": int(metrics.get("review_count", 0) if metrics else 0),
                "complaint_count": int(metrics.get("complaint_count", 0) if metrics else 0),
            }
        )

    def _sort_key(entry: dict[str, object]) -> tuple[float, int, int, str]:
        rating = entry.get("average_rating")
        rating_value = float(rating) if isinstance(rating, (int, float)) else -1.0
        review_count = int(entry.get("review_count", 0))
        complaint_count = int(entry.get("complaint_count", 0))
        worker_name = str(entry.get("worker_name", ""))
        return (-rating_value, -review_count, complaint_count, worker_name)

    entries.sort(key=_sort_key)

    return entries, previous_aggregates
