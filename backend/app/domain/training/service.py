from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.training.db_models import TrainingRequirement, WorkerTrainingRecord
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


def _compute_next_due_at(
    requirement: TrainingRequirement,
    record: WorkerTrainingRecord | None,
) -> datetime | None:
    if record is None:
        return None
    if record.expires_at is not None:
        return record.expires_at
    if requirement.renewal_months and record.completed_at:
        return record.completed_at + timedelta(days=30 * requirement.renewal_months)
    return None


def _compute_status(
    *,
    required: bool,
    record: WorkerTrainingRecord | None,
    now: datetime,
) -> str:
    if not required:
        return "ok"
    if record is None:
        return "due"
    if record.expires_at is not None and record.expires_at <= now:
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

    resolved_completed_at = completed_at or datetime.now(timezone.utc)
    resolved_expires_at = expires_at
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
    resolved_now = now or datetime.now(timezone.utc)
    payload: list[dict[str, object]] = []
    for requirement in requirements:
        record = records.get(requirement.requirement_id)
        required = _is_required_for_worker(requirement, worker)
        status = _compute_status(required=required, record=record, now=resolved_now)
        payload.append(
            {
                "key": requirement.key,
                "title": requirement.title,
                "required": required,
                "completed_at": record.completed_at if record else None,
                "expires_at": record.expires_at if record else None,
                "next_due_at": _compute_next_due_at(requirement, record),
                "status": status,
            }
        )
    return payload
