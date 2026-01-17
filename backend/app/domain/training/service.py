from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.training.db_models import (
    TrainingAssignment,
    TrainingCourse,
    TrainingRequirement,
    TrainingSession,
    TrainingSessionAttendee,
    WorkerTrainingRecord,
)
from app.domain.bookings.db_models import AvailabilityBlock
from app.domain.workers.db_models import Worker


def _normalize_role(role: str | None) -> str | None:
    if role is None:
        return None
    normalized = role.strip().lower()
    return normalized or None


def _is_required_for_worker(requirement: TrainingRequirement, worker: Worker) -> bool:
    required_for_role = _normalize_role(requirement.required_for_role)
    if required_for_role is None:
        return True
    worker_role = _normalize_role(worker.role)
    return worker_role == required_for_role


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compute_next_due_at(
    requirement: TrainingRequirement,
    record: WorkerTrainingRecord | None,
) -> datetime | None:
    if record is None:
        return None
    expires_at = _ensure_utc(record.expires_at)
    completed_at = _ensure_utc(record.completed_at)
    if expires_at is not None:
        return expires_at
    if requirement.renewal_months and completed_at:
        return completed_at + timedelta(days=30 * requirement.renewal_months)
    return None


def _compute_status(
    *,
    requirement: TrainingRequirement,
    required: bool,
    record: WorkerTrainingRecord | None,
    now: datetime,
) -> str:
    resolved_now = _ensure_utc(now) or datetime.now(timezone.utc)
    if not required:
        return "ok"
    if record is None:
        return "due"
    expires_at = _ensure_utc(record.expires_at)
    if expires_at is not None and expires_at <= resolved_now:
        return "overdue"
    next_due_at = _compute_next_due_at(requirement=requirement, record=record)
    if next_due_at is not None and next_due_at <= resolved_now:
        return "overdue"
    return "ok"


async def list_worker_training_status(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_id: int,
) -> tuple[Worker | None, list[TrainingRequirement], dict[uuid.UUID, WorkerTrainingRecord]]:
    worker = (
        await session.execute(
            select(Worker).where(Worker.org_id == org_id, Worker.worker_id == worker_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        return None, [], {}

    requirements = (
        await session.execute(
            select(TrainingRequirement)
            .where(TrainingRequirement.org_id == org_id, TrainingRequirement.active.is_(True))
            .order_by(TrainingRequirement.title.asc())
        )
    ).scalars().all()
    if not requirements:
        return worker, [], {}

    requirement_ids = [req.requirement_id for req in requirements]
    records = (
        await session.execute(
            select(WorkerTrainingRecord)
            .where(
                WorkerTrainingRecord.org_id == org_id,
                WorkerTrainingRecord.worker_id == worker_id,
                WorkerTrainingRecord.requirement_id.in_(requirement_ids),
            )
            .order_by(
                WorkerTrainingRecord.completed_at.desc(),
                WorkerTrainingRecord.created_at.desc(),
            )
        )
    ).scalars().all()

    latest: dict[uuid.UUID, WorkerTrainingRecord] = {}
    for record in records:
        if record.requirement_id not in latest:
            latest[record.requirement_id] = record

    return worker, requirements, latest


async def create_worker_training_record(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_id: int,
    requirement_id: uuid.UUID | None,
    requirement_key: str | None,
    completed_at: datetime | None,
    expires_at: datetime | None,
    score: int | None,
    note: str | None,
) -> WorkerTrainingRecord:
    worker = (
        await session.execute(
            select(Worker).where(Worker.org_id == org_id, Worker.worker_id == worker_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise ValueError("worker_not_found")

    requirement: TrainingRequirement | None = None
    if requirement_id is not None:
        requirement = (
            await session.execute(
                select(TrainingRequirement).where(
                    TrainingRequirement.org_id == org_id,
                    TrainingRequirement.requirement_id == requirement_id,
                )
            )
        ).scalar_one_or_none()
    elif requirement_key:
        normalized_key = requirement_key.strip()
        requirement = (
            await session.execute(
                select(TrainingRequirement).where(
                    TrainingRequirement.org_id == org_id,
                    TrainingRequirement.key == normalized_key,
                )
            )
        ).scalar_one_or_none()

    if requirement is None:
        raise ValueError("requirement_not_found")

    resolved_completed_at = _ensure_utc(completed_at) or datetime.now(timezone.utc)
    resolved_expires_at = _ensure_utc(expires_at)
    if resolved_expires_at is None and requirement.renewal_months:
        resolved_expires_at = resolved_completed_at + timedelta(days=30 * requirement.renewal_months)

    record = WorkerTrainingRecord(
        org_id=org_id,
        worker_id=worker.worker_id,
        requirement_id=requirement.requirement_id,
        completed_at=resolved_completed_at,
        expires_at=resolved_expires_at,
        score=score,
        note=note,
    )
    session.add(record)
    await session.flush()
    return record


def build_training_status_payload(
    *,
    worker: Worker,
    requirements: list[TrainingRequirement],
    records: dict[uuid.UUID, WorkerTrainingRecord],
    now: datetime | None = None,
) -> list[dict[str, object]]:
    resolved_now = _ensure_utc(now) or datetime.now(timezone.utc)
    payload: list[dict[str, object]] = []
    for requirement in requirements:
        record = records.get(requirement.requirement_id)
        required = _is_required_for_worker(requirement, worker)
        status = _compute_status(
            requirement=requirement,
            required=required,
            record=record,
            now=resolved_now,
        )
        payload.append(
            {
                "key": requirement.key,
                "title": requirement.title,
                "required": required,
                "completed_at": _ensure_utc(record.completed_at) if record else None,
                "expires_at": _ensure_utc(record.expires_at) if record else None,
                "next_due_at": _compute_next_due_at(requirement, record),
                "status": status,
            }
        )
    return payload


UNSET = object()


def _normalize_session_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise ValueError("title_required")
    return normalized


def _normalize_training_window(starts_at: datetime, ends_at: datetime) -> tuple[datetime, datetime]:
    normalized_start = _ensure_utc(starts_at)
    normalized_end = _ensure_utc(ends_at)
    if normalized_start is None or normalized_end is None:
        raise ValueError("invalid_window")
    if normalized_end <= normalized_start:
        raise ValueError("invalid_window")
    return normalized_start, normalized_end


def _build_training_reason(title: str) -> str:
    base = f"Training: {title.strip()}"
    return base[:255]


async def _resolve_workers(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_ids: list[int],
) -> list[Worker]:
    if not worker_ids:
        return []
    unique_ids = sorted(set(worker_ids))
    workers = (
        await session.execute(
            select(Worker).where(Worker.org_id == org_id, Worker.worker_id.in_(unique_ids))
        )
    ).scalars().all()
    found_ids = {worker.worker_id for worker in workers}
    missing = [worker_id for worker_id in unique_ids if worker_id not in found_ids]
    if missing:
        raise ValueError("workers_not_found")
    return workers


async def list_training_sessions(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> list[TrainingSession]:
    stmt = select(TrainingSession).where(TrainingSession.org_id == org_id)
    if starts_at:
        stmt = stmt.where(TrainingSession.ends_at > starts_at)
    if ends_at:
        stmt = stmt.where(TrainingSession.starts_at < ends_at)
    return (await session.execute(stmt.order_by(TrainingSession.starts_at.asc()))).scalars().all()


async def get_training_session(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
) -> TrainingSession | None:
    return (
        await session.execute(
            select(TrainingSession).where(
                TrainingSession.org_id == org_id, TrainingSession.session_id == session_id
            )
        )
    ).scalar_one_or_none()


async def list_training_session_attendees(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_ids: list[uuid.UUID],
) -> list[tuple[TrainingSessionAttendee, str]]:
    if not session_ids:
        return []
    stmt = (
        select(TrainingSessionAttendee, Worker.name)
        .join(TrainingSession, TrainingSession.session_id == TrainingSessionAttendee.session_id)
        .join(Worker, Worker.worker_id == TrainingSessionAttendee.worker_id)
        .where(
            TrainingSession.org_id == org_id,
            TrainingSessionAttendee.session_id.in_(session_ids),
        )
        .order_by(TrainingSessionAttendee.session_id, Worker.name.asc())
    )
    return (await session.execute(stmt)).all()


async def create_training_session(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    title: str,
    starts_at: datetime,
    ends_at: datetime,
    location: str | None,
    instructor_user_id: uuid.UUID | None,
    notes: str | None,
    worker_ids: list[int],
    created_by: str | None,
) -> TrainingSession:
    normalized_title = _normalize_session_title(title)
    normalized_start, normalized_end = _normalize_training_window(starts_at, ends_at)
    workers = await _resolve_workers(session, org_id=org_id, worker_ids=worker_ids)

    session_row = TrainingSession(
        org_id=org_id,
        title=normalized_title,
        starts_at=normalized_start,
        ends_at=normalized_end,
        location=location,
        instructor_user_id=instructor_user_id,
        notes=notes,
    )
    session.add(session_row)
    await session.flush()

    reason = _build_training_reason(normalized_title)
    for worker in workers:
        block = AvailabilityBlock(
            org_id=org_id,
            scope_type="worker",
            scope_id=worker.worker_id,
            block_type="training",
            starts_at=normalized_start,
            ends_at=normalized_end,
            reason=reason,
            created_by=created_by,
        )
        session.add(block)
        await session.flush()
        session.add(
            TrainingSessionAttendee(
                session_id=session_row.session_id,
                worker_id=worker.worker_id,
                status="enrolled",
                block_id=block.id,
            )
        )
    await session.flush()
    return session_row


async def update_training_session(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    title: str | None | object = UNSET,
    starts_at: datetime | None | object = UNSET,
    ends_at: datetime | None | object = UNSET,
    location: str | None | object = UNSET,
    instructor_user_id: uuid.UUID | None | object = UNSET,
    notes: str | None | object = UNSET,
) -> TrainingSession | None:
    session_row = await get_training_session(session, org_id=org_id, session_id=session_id)
    if not session_row:
        return None

    previous_title = session_row.title
    previous_start = session_row.starts_at
    previous_end = session_row.ends_at
    new_title = previous_title
    if title is not UNSET and isinstance(title, str):
        new_title = _normalize_session_title(title)
        session_row.title = new_title
    if location is not UNSET:
        session_row.location = location if isinstance(location, str) else None
    if instructor_user_id is not UNSET:
        session_row.instructor_user_id = (
            instructor_user_id if isinstance(instructor_user_id, uuid.UUID) else None
        )
    if notes is not UNSET:
        session_row.notes = notes if isinstance(notes, str) else None

    new_start = session_row.starts_at
    new_end = session_row.ends_at
    if starts_at is not UNSET and starts_at is not None:
        new_start = _ensure_utc(starts_at) or session_row.starts_at
    if ends_at is not UNSET and ends_at is not None:
        new_end = _ensure_utc(ends_at) or session_row.ends_at
    if new_start != session_row.starts_at or new_end != session_row.ends_at:
        new_start, new_end = _normalize_training_window(new_start, new_end)
        session_row.starts_at = new_start
        session_row.ends_at = new_end

    title_changed = new_title != previous_title
    window_changed = new_start != previous_start or new_end != previous_end
    if title_changed or window_changed:
        reason = _build_training_reason(new_title)
        attendees = (
            await session.execute(
                select(TrainingSessionAttendee).where(
                    TrainingSessionAttendee.session_id == session_row.session_id
                )
            )
        ).scalars().all()
        for attendee in attendees:
            if attendee.block_id is None:
                continue
            block = await session.get(AvailabilityBlock, attendee.block_id)
            if block is None or block.org_id != org_id:
                continue
            block.starts_at = new_start
            block.ends_at = new_end
            block.reason = reason

    await session.flush()
    return session_row


async def sync_training_session_attendees(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
    worker_ids: list[int],
    created_by: str | None,
) -> TrainingSession | None:
    session_row = await get_training_session(session, org_id=org_id, session_id=session_id)
    if not session_row:
        return None
    workers = await _resolve_workers(session, org_id=org_id, worker_ids=worker_ids)
    target_ids = {worker.worker_id for worker in workers}
    existing = (
        await session.execute(
            select(TrainingSessionAttendee).where(
                TrainingSessionAttendee.session_id == session_row.session_id
            )
        )
    ).scalars().all()
    existing_ids = {attendee.worker_id for attendee in existing}

    reason = _build_training_reason(session_row.title)
    normalized_start = _ensure_utc(session_row.starts_at) or session_row.starts_at
    normalized_end = _ensure_utc(session_row.ends_at) or session_row.ends_at

    for attendee in existing:
        if attendee.worker_id not in target_ids:
            if attendee.block_id is not None:
                block = await session.get(AvailabilityBlock, attendee.block_id)
                if block is not None and block.org_id == org_id:
                    await session.delete(block)
            await session.delete(attendee)

    for worker in workers:
        if worker.worker_id in existing_ids:
            continue
        block = AvailabilityBlock(
            org_id=org_id,
            scope_type="worker",
            scope_id=worker.worker_id,
            block_type="training",
            starts_at=normalized_start,
            ends_at=normalized_end,
            reason=reason,
            created_by=created_by,
        )
        session.add(block)
        await session.flush()
        session.add(
            TrainingSessionAttendee(
                session_id=session_row.session_id,
                worker_id=worker.worker_id,
                status="enrolled",
                block_id=block.id,
            )
        )

    await session.flush()
    return session_row


async def delete_training_session(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    session_id: uuid.UUID,
) -> bool:
    session_row = await get_training_session(session, org_id=org_id, session_id=session_id)
    if not session_row:
        return False
    attendees = (
        await session.execute(
            select(TrainingSessionAttendee).where(
                TrainingSessionAttendee.session_id == session_row.session_id
            )
        )
    ).scalars().all()
    for attendee in attendees:
        if attendee.block_id is not None:
            block = await session.get(AvailabilityBlock, attendee.block_id)
            if block is not None and block.org_id == org_id:
                await session.delete(block)
    await session.execute(
        delete(TrainingSessionAttendee).where(
            TrainingSessionAttendee.session_id == session_row.session_id
        )
    )
    await session.delete(session_row)
    await session.flush()
    return True

ASSIGNMENT_STATUS_ORDER = {
    "assigned": {"assigned", "in_progress", "completed", "overdue"},
    "in_progress": {"in_progress", "completed", "overdue"},
    "overdue": {"overdue", "in_progress", "completed"},
    "completed": {"completed"},
}


def _normalize_assignment_status(status: str | None) -> str | None:
    if status is None:
        return None
    return status.strip().lower() or None


def _validate_assignment_transition(current: str, target: str) -> None:
    allowed = ASSIGNMENT_STATUS_ORDER.get(current, set())
    if target not in allowed:
        raise ValueError("invalid_status_transition")


async def list_training_courses(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    include_inactive: bool = True,
) -> list[TrainingCourse]:
    stmt = select(TrainingCourse).where(TrainingCourse.org_id == org_id)
    if not include_inactive:
        stmt = stmt.where(TrainingCourse.active.is_(True))
    return (await session.execute(stmt.order_by(TrainingCourse.title.asc()))).scalars().all()


async def get_training_course(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
) -> TrainingCourse | None:
    return (
        await session.execute(
            select(TrainingCourse).where(
                TrainingCourse.org_id == org_id, TrainingCourse.course_id == course_id
            )
        )
    ).scalar_one_or_none()


async def create_training_course(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    title: str,
    description: str | None,
    duration_minutes: int | None,
    active: bool,
    format: str | None,
) -> TrainingCourse:
    course = TrainingCourse(
        org_id=org_id,
        title=title.strip(),
        description=description,
        duration_minutes=duration_minutes,
        active=active,
        format=format,
    )
    session.add(course)
    await session.flush()
    return course


async def update_training_course(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    title: str | None | object = UNSET,
    description: str | None | object = UNSET,
    duration_minutes: int | None | object = UNSET,
    active: bool | None | object = UNSET,
    format: str | None | object = UNSET,
) -> TrainingCourse | None:
    course = await get_training_course(session, org_id=org_id, course_id=course_id)
    if not course:
        return None
    if title is not UNSET:
        course.title = title.strip() if isinstance(title, str) else course.title
    if description is not UNSET:
        course.description = (
            description
            if description is None or isinstance(description, str)
            else course.description
        )
    if duration_minutes is not UNSET:
        course.duration_minutes = (
            duration_minutes
            if duration_minutes is None or isinstance(duration_minutes, int)
            else course.duration_minutes
        )
    if active is not UNSET:
        course.active = active if isinstance(active, bool) else course.active
    if format is not UNSET:
        course.format = format if format is None or isinstance(format, str) else course.format
    await session.flush()
    return course


async def delete_training_course(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
) -> bool:
    course = await get_training_course(session, org_id=org_id, course_id=course_id)
    if not course:
        return False
    await session.delete(course)
    await session.flush()
    return True


async def list_course_assignments(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
) -> list[tuple[TrainingAssignment, str]]:
    stmt = (
        select(TrainingAssignment, Worker.name)
        .join(Worker, Worker.worker_id == TrainingAssignment.worker_id)
        .where(
            TrainingAssignment.org_id == org_id,
            TrainingAssignment.course_id == course_id,
        )
        .order_by(TrainingAssignment.assigned_at.desc())
    )
    return (await session.execute(stmt)).all()


async def assign_workers_to_course(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    worker_ids: list[int],
    due_at: datetime | None,
    assigned_by_user_id: uuid.UUID | None,
) -> list[TrainingAssignment]:
    course = await get_training_course(session, org_id=org_id, course_id=course_id)
    if not course:
        raise ValueError("course_not_found")
    if not worker_ids:
        return []
    unique_ids = sorted(set(worker_ids))
    workers = (
        await session.execute(
            select(Worker).where(Worker.org_id == org_id, Worker.worker_id.in_(unique_ids))
        )
    ).scalars().all()
    found_ids = {worker.worker_id for worker in workers}
    missing = [worker_id for worker_id in unique_ids if worker_id not in found_ids]
    if missing:
        raise ValueError("workers_not_found")
    resolved_due_at = _ensure_utc(due_at)
    now = datetime.now(timezone.utc)
    assignments: list[TrainingAssignment] = []
    for worker_id in unique_ids:
        status = "overdue" if resolved_due_at and resolved_due_at <= now else "assigned"
        assignment = TrainingAssignment(
            org_id=org_id,
            course_id=course_id,
            worker_id=worker_id,
            due_at=resolved_due_at,
            status=status,
            assigned_by_user_id=assigned_by_user_id,
        )
        session.add(assignment)
        assignments.append(assignment)
    await session.flush()
    return assignments


async def list_worker_assignments(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_id: int,
) -> list[tuple[TrainingAssignment, str]]:
    worker = (
        await session.execute(select(Worker).where(Worker.org_id == org_id, Worker.worker_id == worker_id))
    ).scalar_one_or_none()
    if worker is None:
        raise ValueError("worker_not_found")
    stmt = (
        select(TrainingAssignment, TrainingCourse.title)
        .join(TrainingCourse, TrainingCourse.course_id == TrainingAssignment.course_id)
        .where(
            TrainingAssignment.org_id == org_id,
            TrainingAssignment.worker_id == worker_id,
        )
        .order_by(TrainingAssignment.assigned_at.desc())
    )
    return (await session.execute(stmt)).all()


async def update_training_assignment(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    assignment_id: uuid.UUID,
    status: str | None,
    completed_at: datetime | None,
    score: int | None,
) -> TrainingAssignment | None:
    assignment = (
        await session.execute(
            select(TrainingAssignment).where(
                TrainingAssignment.org_id == org_id,
                TrainingAssignment.assignment_id == assignment_id,
            )
        )
    ).scalar_one_or_none()
    if assignment is None:
        return None
    resolved_status = _normalize_assignment_status(status)
    if resolved_status:
        _validate_assignment_transition(assignment.status, resolved_status)
        assignment.status = resolved_status
    resolved_completed_at = _ensure_utc(completed_at)
    if resolved_completed_at and not resolved_status:
        assignment.status = "completed"
        resolved_status = "completed"
    if resolved_status == "completed":
        assignment.completed_at = resolved_completed_at or datetime.now(timezone.utc)
    elif resolved_status:
        assignment.completed_at = None
    if score is not None:
        assignment.score = score
    await session.flush()
    return assignment
