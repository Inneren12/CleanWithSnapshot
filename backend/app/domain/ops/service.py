from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings.db_models import Booking, BookingWorker, EmailEvent, Team, TeamBlackout
from app.domain.bookings.service import (
    BLOCKING_STATUSES,
    BUFFER_MINUTES,
    DEFAULT_SLOT_DURATION_MINUTES,
    ensure_default_team,
    generate_slots,
)
from app.domain.availability import service as availability_service
from app.domain.clients.db_models import ClientAddress, ClientUser
from app.domain.invoices.db_models import Invoice, Payment
from app.domain.leads.db_models import Lead
from app.domain.org_settings import service as org_settings_service
from app.domain.workers.db_models import Worker
from app.domain.notifications import email_service

logger = logging.getLogger(__name__)


DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@", "\t")
BOOKING_STATUS_BANDS = (
    ("8–10", 8, 10),
    ("10–12", 10, 12),
    ("12–14", 12, 14),
    ("14–18", 14, 18),
)


def safe_csv_value(value: object) -> str:
    text = "" if value is None else str(value)
    if not text:
        return ""
    if text.startswith(DANGEROUS_CSV_PREFIXES):
        return f"'{text}"
    return text


def _resolve_service_label(policy_snapshot: dict | None, lead_inputs: dict | None) -> str:
    label = None
    if isinstance(policy_snapshot, dict):
        label = (
            policy_snapshot.get("service_type")
            or policy_snapshot.get("cleaning_type")
            or policy_snapshot.get("service")
        )
    if not label and isinstance(lead_inputs, dict):
        label = (
            lead_inputs.get("cleaning_type")
            or lead_inputs.get("service_type")
            or lead_inputs.get("service")
        )
    if label is None:
        return "Unspecified"
    normalized = str(label).strip()
    return normalized or "Unspecified"


async def build_top_performers_month(
    session: AsyncSession,
    org_id,
    *,
    window_start_utc: datetime,
    window_end_utc: datetime,
    month_start: date,
    month_end: date,
    limit: int = 5,
) -> dict[str, object]:
    booking_filters = [
        Booking.org_id == org_id,
        Booking.archived_at.is_(None),
        Booking.starts_at >= window_start_utc,
        Booking.starts_at < window_end_utc,
        Booking.status != "CANCELLED",
    ]

    revenue_total_stmt = select(func.coalesce(func.sum(Booking.base_charge_cents), 0)).where(
        *booking_filters
    )
    total_revenue_cents = int((await session.execute(revenue_total_stmt)).scalar() or 0)

    teams_stmt = (
        select(
            Team.team_id,
            Team.name,
            func.count(Booking.booking_id),
            func.coalesce(func.sum(Booking.base_charge_cents), 0),
        )
        .join(Team, Booking.team_id == Team.team_id)
        .where(*booking_filters)
        .group_by(Team.team_id, Team.name)
        .order_by(
            sa.desc(func.coalesce(func.sum(Booking.base_charge_cents), 0)),
            sa.desc(func.count(Booking.booking_id)),
        )
        .limit(limit)
    )
    team_rows = (await session.execute(teams_stmt)).all()
    top_teams = [
        {
            "team_id": team_id,
            "name": name,
            "bookings_count": int(bookings_count or 0),
            "revenue_cents": int(revenue_cents or 0),
        }
        for team_id, name, bookings_count, revenue_cents in team_rows
    ]

    clients_stmt = (
        select(
            ClientUser.client_id,
            ClientUser.name,
            ClientUser.email,
            func.count(Booking.booking_id),
            func.coalesce(func.sum(Booking.base_charge_cents), 0),
        )
        .join(ClientUser, Booking.client_id == ClientUser.client_id)
        .where(
            *booking_filters,
            Booking.client_id.is_not(None),
        )
        .group_by(ClientUser.client_id, ClientUser.name, ClientUser.email)
        .order_by(
            sa.desc(func.coalesce(func.sum(Booking.base_charge_cents), 0)),
            sa.desc(func.count(Booking.booking_id)),
        )
        .limit(limit)
    )
    client_rows = (await session.execute(clients_stmt)).all()
    top_clients = [
        {
            "client_id": client_id,
            "name": name,
            "email": email,
            "bookings_count": int(bookings_count or 0),
            "revenue_cents": int(revenue_cents or 0),
        }
        for client_id, name, email, bookings_count, revenue_cents in client_rows
    ]

    assignments_union = sa.union_all(
        select(
            BookingWorker.booking_id.label("booking_id"),
            BookingWorker.worker_id.label("worker_id"),
        ),
        select(
            Booking.booking_id.label("booking_id"),
            Booking.assigned_worker_id.label("worker_id"),
        ),
    ).subquery()
    assignments_distinct = (
        select(assignments_union.c.booking_id, assignments_union.c.worker_id)
        .where(assignments_union.c.worker_id.is_not(None))
        .distinct()
        .subquery()
    )

    workers_stmt = (
        select(
            Worker.worker_id,
            Worker.name,
            Worker.team_id,
            Team.name,
            func.count(Booking.booking_id),
            func.coalesce(func.sum(Booking.base_charge_cents), 0),
        )
        .join(assignments_distinct, Worker.worker_id == assignments_distinct.c.worker_id)
        .join(Booking, Booking.booking_id == assignments_distinct.c.booking_id)
        .join(Team, Worker.team_id == Team.team_id)
        .where(*booking_filters)
        .group_by(Worker.worker_id, Worker.name, Worker.team_id, Team.name)
        .order_by(
            sa.desc(func.coalesce(func.sum(Booking.base_charge_cents), 0)),
            sa.desc(func.count(Booking.booking_id)),
        )
        .limit(limit)
    )
    worker_rows = (await session.execute(workers_stmt)).all()
    top_workers = [
        {
            "worker_id": worker_id,
            "name": name,
            "team_id": team_id,
            "team_name": team_name,
            "bookings_count": int(bookings_count or 0),
            "revenue_cents": int(revenue_cents or 0),
        }
        for worker_id, name, team_id, team_name, bookings_count, revenue_cents in worker_rows
    ]

    service_stmt = (
        select(
            Booking.booking_id,
            Booking.base_charge_cents,
            Booking.policy_snapshot,
            Lead.structured_inputs,
        )
        .outerjoin(Lead, Booking.lead_id == Lead.lead_id)
        .where(*booking_filters)
    )
    service_rows = (await session.execute(service_stmt)).all()
    service_totals: dict[str, dict[str, int]] = {}
    for _booking_id, base_charge_cents, policy_snapshot, structured_inputs in service_rows:
        label = _resolve_service_label(policy_snapshot, structured_inputs)
        entry = service_totals.setdefault(label, {"bookings_count": 0, "revenue_cents": 0})
        entry["bookings_count"] += 1
        entry["revenue_cents"] += int(base_charge_cents or 0)

    top_services = []
    for label, metrics in sorted(
        service_totals.items(),
        key=lambda item: (item[1]["revenue_cents"], item[1]["bookings_count"]),
        reverse=True,
    )[:limit]:
        revenue_cents = metrics["revenue_cents"]
        share = revenue_cents / total_revenue_cents if total_revenue_cents else 0.0
        top_services.append(
            {
                "label": label,
                "bookings_count": metrics["bookings_count"],
                "revenue_cents": revenue_cents,
                "share_of_revenue": round(share, 4),
            }
        )

    return {
        "month_start": month_start,
        "month_end": month_end,
        "total_revenue_cents": total_revenue_cents,
        "workers": top_workers,
        "clients": top_clients,
        "teams": top_teams,
        "services": top_services,
    }


async def list_worker_timeline(
    session: AsyncSession,
    org_id,
    start_date: date,
    end_date: date,
    *,
    org_timezone: str | None = None,
    worker_id: int | None = None,
    team_id: int | None = None,
    status: str | None = None,
) -> dict[str, object]:
    resolved_timezone = org_timezone or org_settings_service.DEFAULT_TIMEZONE
    try:
        org_tz = ZoneInfo(resolved_timezone)
    except Exception:
        org_tz = ZoneInfo(org_settings_service.DEFAULT_TIMEZONE)

    start_local = datetime.combine(start_date, time.min).replace(tzinfo=org_tz)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min).replace(tzinfo=org_tz)
    window_start = start_local.astimezone(timezone.utc)
    window_end = end_local.astimezone(timezone.utc)

    days = [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]

    worker_conditions = [
        Worker.org_id == org_id,
        Worker.is_active.is_(True),
        Worker.archived_at.is_(None),
    ]
    if team_id is not None:
        worker_conditions.append(Worker.team_id == team_id)
    if worker_id is not None:
        worker_conditions.append(Worker.worker_id == worker_id)

    workers_stmt = (
        select(Worker, Team)
        .join(Team, Worker.team_id == Team.team_id)
        .where(*worker_conditions)
        .order_by(Worker.name.asc())
    )
    worker_rows = (await session.execute(workers_stmt)).all()

    timeline_by_worker: dict[int, dict[date, dict[str, object]]] = {}
    workers_payload: list[dict[str, object]] = []
    totals = {"booked_minutes": 0, "booking_count": 0, "revenue_cents": 0}

    for worker, team in worker_rows:
        day_entries = {
            day: {
                "date": day,
                "booked_minutes": 0,
                "booking_count": 0,
                "revenue_cents": 0,
                "booking_ids": [],
            }
            for day in days
        }
        timeline_by_worker[worker.worker_id] = day_entries
        workers_payload.append(
            {
                "worker_id": worker.worker_id,
                "name": worker.name,
                "team_id": worker.team_id,
                "team_name": team.name if team else None,
                "days": day_entries,
                "totals": {"booked_minutes": 0, "booking_count": 0, "revenue_cents": 0},
            }
        )

    booking_conditions = [
        Booking.org_id == org_id,
        Booking.archived_at.is_(None),
        Booking.assigned_worker_id.is_not(None),
        Booking.starts_at >= window_start,
        Booking.starts_at < window_end,
    ]
    if team_id is not None:
        booking_conditions.append(Booking.team_id == team_id)
    if worker_id is not None:
        booking_conditions.append(Booking.assigned_worker_id == worker_id)
    if status:
        booking_conditions.append(Booking.status == status)

    booking_stmt = select(
        Booking.booking_id,
        Booking.assigned_worker_id,
        Booking.starts_at,
        Booking.duration_minutes,
        Booking.base_charge_cents,
    ).where(*booking_conditions)

    booking_rows = (await session.execute(booking_stmt)).all()

    totals_by_worker_id = {
        worker_data["worker_id"]: worker_data["totals"] for worker_data in workers_payload
    }

    for booking_id, assigned_worker_id, starts_at, duration_minutes, base_charge_cents in booking_rows:
        if assigned_worker_id is None:
            continue
        day = starts_at.astimezone(org_tz).date()
        day_entries = timeline_by_worker.get(assigned_worker_id)
        if not day_entries:
            continue
        day_payload = day_entries.get(day)
        if not day_payload:
            continue
        day_payload["booked_minutes"] += duration_minutes
        day_payload["booking_count"] += 1
        day_payload["revenue_cents"] += base_charge_cents or 0
        day_payload["booking_ids"].append(booking_id)

        worker_totals = totals_by_worker_id[assigned_worker_id]
        worker_totals["booked_minutes"] += duration_minutes
        worker_totals["booking_count"] += 1
        worker_totals["revenue_cents"] += base_charge_cents or 0

        totals["booked_minutes"] += duration_minutes
        totals["booking_count"] += 1
        totals["revenue_cents"] += base_charge_cents or 0

    formatted_workers = []
    for worker_data in workers_payload:
        day_entries = worker_data["days"]
        worker_data["days"] = [day_entries[day] for day in days]
        formatted_workers.append(worker_data)

    return {
        "from_date": start_date,
        "to_date": end_date,
        "org_timezone": resolved_timezone,
        "days": days,
        "workers": formatted_workers,
        "totals": totals,
    }


@dataclass(slots=True)
class QuickAction:
    label: str
    target: str
    method: str = "GET"


@dataclass(slots=True)
class SearchHit:
    kind: str
    ref: str
    label: str
    status: str | None
    created_at: datetime
    quick_actions: list[QuickAction]
    relevance_score: int = 0  # Higher = more relevant


def _build_quick_actions(kind: str, ref: str, extra_context: dict | None = None) -> list[QuickAction]:
    """Build context-aware quick actions for search results."""
    if kind == "lead":
        actions = [QuickAction(label="View lead", target=f"/v1/admin/leads/{ref}")]
        if extra_context and extra_context.get("email"):
            actions.append(QuickAction(label="Email", target=f"mailto:{extra_context['email']}"))
        if extra_context and extra_context.get("phone"):
            actions.append(QuickAction(label="Call", target=f"tel:{extra_context['phone']}"))
        return actions
    if kind == "booking":
        return [
            QuickAction(label="View booking", target=f"/v1/bookings/{ref}"),
            QuickAction(label="Move", target=f"/v1/admin/schedule/{ref}/move", method="POST"),
            QuickAction(label="Timeline", target=f"/v1/admin/timeline/booking/{ref}"),
        ]
    if kind == "invoice":
        return [
            QuickAction(label="View invoice", target=f"/v1/invoices/{ref}"),
            QuickAction(label="Resend", target=f"/v1/admin/invoices/{ref}/resend", method="POST"),
            QuickAction(label="Timeline", target=f"/v1/admin/timeline/invoice/{ref}"),
        ]
    if kind == "payment":
        return [QuickAction(label="Review payment", target=f"/v1/admin/payments/{ref}")]
    if kind == "worker":
        actions = [QuickAction(label="View worker", target=f"/v1/admin/workers/{ref}")]
        if extra_context and extra_context.get("phone"):
            actions.append(QuickAction(label="Call", target=f"tel:{extra_context['phone']}"))
        return actions
    return []


def _calculate_relevance(q: str, text_fields: list[str | None]) -> int:
    """Calculate relevance score (higher = more relevant).

    Exact matches score highest, then prefix matches, then contains.
    """
    q_lower = q.lower().strip()
    score = 0

    for field in text_fields:
        if not field:
            continue
        field_lower = field.lower()

        if field_lower == q_lower:
            score += 100  # Exact match
        elif field_lower.startswith(q_lower):
            score += 50  # Prefix match
        elif q_lower in field_lower:
            score += 10  # Contains

    return score


async def build_booking_status_bands(
    session: AsyncSession,
    org_id,
    *,
    today_local_date: date,
    org_timezone: ZoneInfo,
) -> list[tuple[str, int]]:
    bands: list[tuple[str, int]] = []
    for label, start_hour, end_hour in BOOKING_STATUS_BANDS:
        band_start_local = datetime.combine(
            today_local_date, time(hour=start_hour, tzinfo=org_timezone)
        )
        band_end_local = datetime.combine(
            today_local_date, time(hour=end_hour, tzinfo=org_timezone)
        )
        band_start_utc = band_start_local.astimezone(timezone.utc)
        band_end_utc = band_end_local.astimezone(timezone.utc)
        stmt = select(func.count()).where(
            Booking.org_id == org_id,
            Booking.archived_at.is_(None),
            Booking.starts_at >= band_start_utc,
            Booking.starts_at < band_end_utc,
        )
        count = (await session.execute(stmt)).scalar_one()
        bands.append((label, count))
    return bands


async def global_search(session: AsyncSession, org_id, q: str, limit: int = 20) -> list[SearchHit]:
    """Enhanced global search with weighted results and expanded coverage.

    Searches across leads, bookings, invoices, payments, and workers.
    Results are sorted by relevance score (exact/prefix/contains matches) then recency.
    """
    if not q:
        return []

    term = f"%{q.strip()}%"
    hits: list[SearchHit] = []

    # Search leads
    lead_stmt: Select = (
        select(Lead)
        .where(Lead.org_id == org_id)
        .where(or_(Lead.name.ilike(term), Lead.email.ilike(term), Lead.phone.ilike(term)))
        .order_by(Lead.created_at.desc())
        .limit(limit * 2)  # Fetch more for relevance sorting
    )
    for lead in (await session.execute(lead_stmt)).scalars().all():
        relevance = _calculate_relevance(q, [lead.name, lead.email, lead.phone])
        hits.append(
            SearchHit(
                kind="lead",
                ref=lead.lead_id,
                label=lead.name,
                status=lead.status,
                created_at=lead.created_at,
                quick_actions=_build_quick_actions("lead", lead.lead_id, {"email": lead.email, "phone": lead.phone}),
                relevance_score=relevance,
            )
        )

    # Search bookings
    booking_stmt: Select = (
        select(Booking)
        .where(Booking.org_id == org_id)
        .where(
            or_(
                Booking.booking_id.ilike(term),
                Booking.status.ilike(term),
            )
        )
        .order_by(Booking.created_at.desc())
        .limit(limit * 2)
    )
    for booking in (await session.execute(booking_stmt)).scalars().all():
        relevance = _calculate_relevance(q, [booking.booking_id, booking.status])
        hits.append(
            SearchHit(
                kind="booking",
                ref=booking.booking_id,
                label=f"Booking {booking.booking_id}",
                status=booking.status,
                created_at=booking.created_at,
                quick_actions=_build_quick_actions("booking", booking.booking_id),
                relevance_score=relevance,
            )
        )

    # Search invoices
    invoice_stmt: Select = (
        select(Invoice)
        .where(Invoice.org_id == org_id)
        .where(or_(Invoice.invoice_number.ilike(term), Invoice.invoice_id.ilike(term)))
        .order_by(Invoice.created_at.desc())
        .limit(limit * 2)
    )
    for invoice in (await session.execute(invoice_stmt)).scalars().all():
        relevance = _calculate_relevance(q, [invoice.invoice_number, invoice.invoice_id])
        hits.append(
            SearchHit(
                kind="invoice",
                ref=invoice.invoice_id,
                label=invoice.invoice_number,
                status=invoice.status,
                created_at=invoice.created_at,
                quick_actions=_build_quick_actions("invoice", invoice.invoice_id),
                relevance_score=relevance,
            )
        )

    # Search payments
    payment_stmt: Select = (
        select(Payment)
        .where(Payment.org_id == org_id)
        .where(
            or_(
                Payment.payment_id.ilike(term),
                Payment.provider_ref.ilike(term),
                Payment.status.ilike(term),
            )
        )
        .order_by(Payment.created_at.desc())
        .limit(limit * 2)
    )
    for payment in (await session.execute(payment_stmt)).scalars().all():
        relevance = _calculate_relevance(q, [payment.payment_id, payment.provider_ref, payment.status])
        hits.append(
            SearchHit(
                kind="payment",
                ref=payment.payment_id,
                label=payment.provider_ref or payment.payment_id,
                status=payment.status,
                created_at=payment.created_at,
                quick_actions=_build_quick_actions("payment", payment.payment_id),
                relevance_score=relevance,
            )
        )

    # Search workers
    worker_stmt: Select = (
        select(Worker)
        .where(Worker.org_id == org_id)
        .where(
            or_(
                Worker.name.ilike(term),
                Worker.phone.ilike(term),
                Worker.email.ilike(term),
            )
        )
        .order_by(Worker.created_at.desc())
        .limit(limit * 2)
    )
    for worker in (await session.execute(worker_stmt)).scalars().all():
        relevance = _calculate_relevance(q, [worker.name, worker.phone, worker.email])
        hits.append(
            SearchHit(
                kind="worker",
                ref=str(worker.worker_id),
                label=worker.name,
                status="active" if worker.is_active else "inactive",
                created_at=worker.created_at,
                quick_actions=_build_quick_actions("worker", str(worker.worker_id), {"phone": worker.phone}),
                relevance_score=relevance,
            )
        )

    # Sort by relevance (desc) then created_at (desc)
    hits.sort(key=lambda item: (item.relevance_score, item.created_at), reverse=True)
    return hits[:limit]


def _normalize(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _conflicts(existing_start: datetime, existing_duration: int, candidate_start: datetime, candidate_duration: int) -> bool:
    buffer_delta = timedelta(minutes=BUFFER_MINUTES)
    existing_end = existing_start + timedelta(minutes=existing_duration)
    candidate_end = candidate_start + timedelta(minutes=candidate_duration)
    return candidate_start < existing_end + buffer_delta and candidate_end > existing_start - buffer_delta


def _availability_note(block_type: str, reason: str | None) -> str:
    if reason:
        return f"{block_type}: {reason}"
    return block_type


async def _blocking_bookings(
    session: AsyncSession,
    team_id: int,
    window_start: datetime,
    window_end: datetime,
    *,
    exclude_booking_id: str | None = None,
) -> Iterable[Booking]:
    bind = session.get_bind()
    booking_end = Booking.ends_at if hasattr(Booking, "ends_at") else None
    if booking_end is None:
        if bind and bind.dialect.name == "sqlite":
            booking_end = func.datetime(
                Booking.starts_at, func.printf("+%d minutes", Booking.duration_minutes)
            )
        else:
            booking_end = Booking.starts_at + func.make_interval(mins=Booking.duration_minutes)

    buffer_delta = timedelta(minutes=BUFFER_MINUTES)
    stmt = select(Booking).where(
        Booking.team_id == team_id,
        Booking.starts_at < window_end + buffer_delta,
        booking_end > window_start - buffer_delta,
        Booking.status.in_(BLOCKING_STATUSES),
    )
    if exclude_booking_id:
        stmt = stmt.where(Booking.booking_id != exclude_booking_id)
    result = await session.execute(stmt)
    return result.scalars().all()


async def _team_for_org(session: AsyncSession, org_id, team_id: int | None) -> Team:
    team = None
    if team_id:
        team = await session.get(Team, team_id)
    if team is None:
        team = await ensure_default_team(session, org_id)
    if getattr(team, "org_id", None) != org_id:
        raise PermissionError("Team does not belong to org")
    return team


async def _team_conflicts(
    session: AsyncSession,
    team: Team,
    window_start: datetime,
    window_end: datetime,
    *,
    exclude_booking_id: str | None = None,
) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    for booking in await _blocking_bookings(
        session, team.team_id, window_start, window_end, exclude_booking_id=exclude_booking_id
    ):
        if _conflicts(
            _normalize(booking.starts_at), booking.duration_minutes, window_start, (window_end - window_start).seconds // 60
        ):
            conflicts.append(
                {
                    "kind": "booking",
                    "reference": booking.booking_id,
                    "starts_at": _normalize(booking.starts_at),
                    "ends_at": _normalize(booking.starts_at) + timedelta(minutes=booking.duration_minutes),
                    "note": "existing booking",
                }
            )

    blackout_stmt = select(TeamBlackout).where(
        TeamBlackout.team_id == team.team_id,
        TeamBlackout.starts_at < window_end,
        TeamBlackout.ends_at > window_start,
    )
    for blackout in (await session.execute(blackout_stmt)).scalars().all():
        conflicts.append(
            {
                "kind": "blackout",
                "reference": str(blackout.id),
                "starts_at": _normalize(blackout.starts_at),
                "ends_at": _normalize(blackout.ends_at),
                "note": blackout.reason,
            }
        )

    blocks = await availability_service.list_team_blocks(
        session,
        team.org_id,
        team.team_id,
        starts_at=window_start,
        ends_at=window_end,
    )
    for block in blocks:
        conflicts.append(
            {
                "kind": "availability_block",
                "reference": str(block.id),
                "starts_at": _normalize(block.starts_at),
                "ends_at": _normalize(block.ends_at),
                "note": _availability_note(block.block_type, block.reason),
            }
        )

    return conflicts


async def _worker_conflicts(
    session: AsyncSession,
    worker: Worker,
    window_start: datetime,
    window_end: datetime,
    *,
    exclude_booking_id: str | None = None,
) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    bind = session.get_bind()
    booking_end = Booking.ends_at if hasattr(Booking, "ends_at") else None
    if booking_end is None:
        if bind and bind.dialect.name == "sqlite":
            booking_end = func.datetime(
                Booking.starts_at, func.printf("+%d minutes", Booking.duration_minutes)
            )
        else:
            booking_end = Booking.starts_at + func.make_interval(mins=Booking.duration_minutes)

    buffer_delta = timedelta(minutes=BUFFER_MINUTES)
    stmt = select(Booking).where(
        Booking.org_id == worker.org_id,
        Booking.assigned_worker_id == worker.worker_id,
        Booking.starts_at < window_end + buffer_delta,
        booking_end > window_start - buffer_delta,
        Booking.status.in_(BLOCKING_STATUSES),
    )
    if exclude_booking_id:
        stmt = stmt.where(Booking.booking_id != exclude_booking_id)

    for booking in (await session.execute(stmt)).scalars().all():
        if _conflicts(
            _normalize(booking.starts_at), booking.duration_minutes, window_start, (window_end - window_start).seconds // 60
        ):
            conflicts.append(
                {
                    "kind": "worker_booking",
                    "reference": booking.booking_id,
                    "starts_at": _normalize(booking.starts_at),
                    "ends_at": _normalize(booking.starts_at) + timedelta(minutes=booking.duration_minutes),
                    "note": "worker has a conflicting booking",
                }
            )

    blocks = await availability_service.list_worker_blocks(
        session,
        worker.org_id,
        worker.worker_id,
        starts_at=window_start,
        ends_at=window_end,
    )
    for block in blocks:
        conflicts.append(
            {
                "kind": "availability_block",
                "reference": str(block.id),
                "starts_at": _normalize(block.starts_at),
                "ends_at": _normalize(block.ends_at),
                "note": _availability_note(block.block_type, block.reason),
            }
        )
    return conflicts


def _serialize_schedule_booking(
    booking: Booking,
    *,
    team: Team | None,
    worker: Worker | None,
    lead: Lead | None,
    client: ClientUser | None,
    address: ClientAddress | None,
) -> dict[str, object]:
    client_label = getattr(lead, "name", None) or getattr(client, "name", None) or getattr(client, "email", None)
    address_value = None
    if address and address.address_text:
        address_value = address.address_text
    elif client and client.address:
        address_value = client.address
    elif lead and lead.address:
        address_value = lead.address

    service_label = None
    if booking.policy_snapshot:
        service_label = (
            booking.policy_snapshot.get("service_type")
            or booking.policy_snapshot.get("cleaning_type")
            or booking.policy_snapshot.get("service")
        )
    if lead and lead.structured_inputs:
        service_label = service_label or (
            lead.structured_inputs.get("cleaning_type")
            or lead.structured_inputs.get("service_type")
            or lead.structured_inputs.get("service")
        )

    notes_parts: list[str] = []
    if client and client.notes:
        notes_parts.append(f"Client: {client.notes}")
    if address and address.notes:
        notes_parts.append(f"Address: {address.notes}")
    notes = "\n".join(notes_parts) if notes_parts else None

    duration = booking.duration_minutes or DEFAULT_SLOT_DURATION_MINUTES
    normalized_start = _normalize(booking.starts_at)
    ends_at = normalized_start + timedelta(minutes=duration)
    return {
        "booking_id": booking.booking_id,
        "starts_at": normalized_start,
        "ends_at": ends_at,
        "duration_minutes": duration,
        "status": booking.status,
        "worker_id": booking.assigned_worker_id,
        "worker_name": getattr(worker, "name", None),
        "team_id": booking.team_id,
        "team_name": getattr(team, "name", None),
        "client_label": client_label,
        "address": address_value,
        "service_label": service_label,
        "price_cents": booking.base_charge_cents,
        "notes": notes,
    }


async def list_schedule(
    session: AsyncSession,
    org_id,
    start_date: date,
    end_date: date,
    *,
    org_timezone: str | None = None,
    worker_id: int | None = None,
    team_id: int | None = None,
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    query: str | None = None,
) -> dict[str, object]:
    resolved_timezone = org_timezone or org_settings_service.DEFAULT_TIMEZONE
    try:
        org_tz = ZoneInfo(resolved_timezone)
    except Exception:
        org_tz = ZoneInfo(org_settings_service.DEFAULT_TIMEZONE)

    start_local = datetime.combine(start_date, time.min).replace(tzinfo=org_tz)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min).replace(tzinfo=org_tz)
    window_start = start_local.astimezone(timezone.utc)
    window_end = end_local.astimezone(timezone.utc)

    conditions = [
        Booking.org_id == org_id,
        Booking.archived_at.is_(None),
        Booking.starts_at >= window_start,
        Booking.starts_at < window_end,
    ]

    if team_id is not None:
        conditions.append(Booking.team_id == team_id)
    if worker_id is not None:
        conditions.append(Booking.assigned_worker_id == worker_id)
    if status:
        conditions.append(Booking.status == status)

    normalized_query = (query or "").strip()
    if normalized_query:
        like_value = f"%{normalized_query}%"
        conditions.append(
            or_(
                Booking.booking_id.ilike(like_value),
                Booking.status.ilike(like_value),
                Lead.name.ilike(like_value),
                Lead.email.ilike(like_value),
                Lead.phone.ilike(like_value),
                ClientUser.name.ilike(like_value),
                ClientUser.email.ilike(like_value),
                ClientUser.phone.ilike(like_value),
                ClientAddress.address_text.ilike(like_value),
                ClientUser.address.ilike(like_value),
            )
        )

    stmt = (
        select(Booking, Team, Worker, Lead, ClientUser, ClientAddress)
        .join(Team, Booking.team_id == Team.team_id)
        .outerjoin(Worker, Booking.assigned_worker_id == Worker.worker_id)
        .outerjoin(Lead, Booking.lead_id == Lead.lead_id)
        .outerjoin(ClientUser, Booking.client_id == ClientUser.client_id)
        .outerjoin(ClientAddress, Booking.address_id == ClientAddress.address_id)
        .where(*conditions)
        .order_by(Booking.starts_at.asc())
    )

    count_stmt = (
        select(func.count(func.distinct(Booking.booking_id)))
        .select_from(Booking)
        .join(Team, Booking.team_id == Team.team_id)
        .outerjoin(Worker, Booking.assigned_worker_id == Worker.worker_id)
        .outerjoin(Lead, Booking.lead_id == Lead.lead_id)
        .outerjoin(ClientUser, Booking.client_id == ClientUser.client_id)
        .outerjoin(ClientAddress, Booking.address_id == ClientAddress.address_id)
        .where(*conditions)
    )

    total = (await session.execute(count_stmt)).scalar_one()

    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).all()
    bookings = [
        _serialize_schedule_booking(
            booking,
            team=team,
            worker=worker,
            lead=lead,
            client=client,
            address=address,
        )
        for booking, team, worker, lead, client, address in rows
    ]

    return {
        "from_date": start_date,
        "to_date": end_date,
        "bookings": bookings,
        "total": total,
        "limit": limit,
        "offset": offset,
        "query": normalized_query or None,
    }


async def list_team_calendar(
    session: AsyncSession,
    org_id,
    start_date: date,
    end_date: date,
    *,
    org_timezone: str | None = None,
    team_id: int | None = None,
    status: str | None = None,
) -> dict[str, object]:
    resolved_timezone = org_timezone or org_settings_service.DEFAULT_TIMEZONE
    try:
        org_tz = ZoneInfo(resolved_timezone)
    except Exception:
        org_tz = ZoneInfo(org_settings_service.DEFAULT_TIMEZONE)

    start_local = datetime.combine(start_date, time.min).replace(tzinfo=org_tz)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min).replace(tzinfo=org_tz)
    window_start = start_local.astimezone(timezone.utc)
    window_end = end_local.astimezone(timezone.utc)

    days = [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]

    team_conditions = [Team.org_id == org_id, Team.archived_at.is_(None)]
    if team_id is not None:
        team_conditions.append(Team.team_id == team_id)

    team_stmt = select(Team.team_id, Team.name).where(*team_conditions).order_by(Team.name.asc())
    team_rows = (await session.execute(team_stmt)).all()

    team_day_map: dict[int, dict[date, dict[str, object]]] = {}
    teams_payload: list[dict[str, object]] = []

    for team_id_value, name in team_rows:
        day_entries = {
            day: {"date": day, "bookings": 0, "revenue": 0, "workers_used": 0} for day in days
        }
        team_day_map[team_id_value] = day_entries
        teams_payload.append(
            {"team_id": team_id_value, "name": name, "days": day_entries}
        )

    booking_conditions = [
        Booking.org_id == org_id,
        Booking.archived_at.is_(None),
        Booking.starts_at >= window_start,
        Booking.starts_at < window_end,
    ]
    if team_id is not None:
        booking_conditions.append(Booking.team_id == team_id)
    if status:
        booking_conditions.append(Booking.status == status)

    booking_stmt = select(
        Booking.booking_id,
        Booking.team_id,
        Booking.starts_at,
        Booking.base_charge_cents,
        Booking.assigned_worker_id,
    ).where(*booking_conditions)
    booking_rows = (await session.execute(booking_stmt)).all()

    worker_sets: dict[tuple[int, date], set[int]] = {}

    for booking_id, booking_team_id, starts_at, base_charge_cents, assigned_worker_id in booking_rows:
        day = starts_at.astimezone(org_tz).date()
        day_entries = team_day_map.get(booking_team_id)
        if not day_entries:
            continue
        day_payload = day_entries.get(day)
        if not day_payload:
            continue
        day_payload["bookings"] += 1
        day_payload["revenue"] += base_charge_cents or 0
        if assigned_worker_id is not None:
            worker_sets.setdefault((booking_team_id, day), set()).add(assigned_worker_id)

    worker_stmt = (
        select(
            BookingWorker.booking_id,
            BookingWorker.worker_id,
            Booking.team_id,
            Booking.starts_at,
        )
        .join(Booking, BookingWorker.booking_id == Booking.booking_id)
        .where(*booking_conditions)
    )
    worker_rows = (await session.execute(worker_stmt)).all()

    for _booking_id, worker_id, booking_team_id, starts_at in worker_rows:
        day = starts_at.astimezone(org_tz).date()
        worker_sets.setdefault((booking_team_id, day), set()).add(worker_id)

    for team_id_value, day_entries in team_day_map.items():
        for day, payload in day_entries.items():
            payload["workers_used"] = len(worker_sets.get((team_id_value, day), set()))

    formatted_teams = []
    for team_data in teams_payload:
        day_entries = team_data["days"]
        team_data["days"] = [day_entries[day] for day in days]
        formatted_teams.append(team_data)

    return {
        "from_date": start_date,
        "to_date": end_date,
        "org_timezone": resolved_timezone,
        "days": days,
        "teams": formatted_teams,
    }


async def fetch_schedule_booking(session: AsyncSession, org_id, booking_id: str) -> dict[str, object]:
    stmt = (
        select(Booking, Team, Worker, Lead, ClientUser, ClientAddress)
        .join(Team, Booking.team_id == Team.team_id)
        .outerjoin(Worker, Booking.assigned_worker_id == Worker.worker_id)
        .outerjoin(Lead, Booking.lead_id == Lead.lead_id)
        .outerjoin(ClientUser, Booking.client_id == ClientUser.client_id)
        .outerjoin(ClientAddress, Booking.address_id == ClientAddress.address_id)
        .where(Booking.org_id == org_id, Booking.booking_id == booking_id)
    )
    row = (await session.execute(stmt)).first()
    if not row:
        raise LookupError("booking_not_found")
    booking, team, worker, lead, client, address = row
    return _serialize_schedule_booking(
        booking,
        team=team,
        worker=worker,
        lead=lead,
        client=client,
        address=address,
    )


async def suggest_schedule_resources(
    session: AsyncSession,
    org_id,
    *,
    starts_at: datetime,
    ends_at: datetime,
    skill_tags: list[str] | None = None,
    exclude_booking_id: str | None = None,
) -> dict[str, list[dict[str, object]]]:
    normalized_start = _normalize(starts_at)
    normalized_end = _normalize(ends_at)
    if normalized_end <= normalized_start:
        raise ValueError("invalid_window")

    stmt = (
        select(Team)
        .where(Team.org_id == org_id, Team.archived_at.is_(None))
        .order_by(Team.team_id)
    )
    teams = (await session.execute(stmt)).scalars().all()
    if not teams:
        teams = [await ensure_default_team(session, org_id)]

    skill_terms = [tag.lower().strip() for tag in (skill_tags or []) if tag]
    available_teams: list[dict[str, object]] = []
    team_conflicts: dict[int, list[dict[str, object]]] = {}

    for team in teams:
        conflicts = await _team_conflicts(
            session, team, normalized_start, normalized_end, exclude_booking_id=exclude_booking_id
        )
        team_conflicts[team.team_id] = conflicts
        if not conflicts:
            available_teams.append({"team_id": team.team_id, "name": team.name})

    worker_stmt: Select = (
        select(Worker, Team.name)
        .join(Team, Worker.team_id == Team.team_id)
        .where(Team.org_id == org_id)
        .where(Worker.is_active.is_(True))
        .order_by(Worker.worker_id)
    )
    available_workers: list[dict[str, object]] = []
    for worker, team_name in (await session.execute(worker_stmt)).all():
        role_text = (worker.role or "").lower()
        if skill_terms and not all(term in role_text for term in skill_terms):
            continue

        team_conflict = team_conflicts.get(worker.team_id, [])
        worker_conflict = await _worker_conflicts(
            session, worker, normalized_start, normalized_end, exclude_booking_id=exclude_booking_id
        )
        if team_conflict or worker_conflict:
            continue

        available_workers.append(
            {
                "worker_id": worker.worker_id,
                "name": worker.name,
                "team_id": worker.team_id,
                "team_name": team_name,
            }
        )

    return {"teams": available_teams, "workers": available_workers}


async def check_schedule_conflicts(
    session: AsyncSession,
    org_id,
    *,
    starts_at: datetime,
    ends_at: datetime,
    team_id: int | None = None,
    booking_id: str | None = None,
    worker_id: int | None = None,
) -> list[dict[str, object]]:
    normalized_start = _normalize(starts_at)
    normalized_end = _normalize(ends_at)
    if normalized_end <= normalized_start:
        raise ValueError("invalid_window")

    team = await _team_for_org(session, org_id, team_id)
    conflicts = await _team_conflicts(
        session, team, normalized_start, normalized_end, exclude_booking_id=booking_id
    )

    if worker_id is not None:
        worker = await session.get(Worker, worker_id)
        if worker is None:
            raise LookupError("worker_not_found")
        if worker.org_id != org_id:
            raise PermissionError("Cross-org worker access blocked")
        worker_conflicts = await _worker_conflicts(
            session, worker, normalized_start, normalized_end, exclude_booking_id=booking_id
        )
        conflicts.extend(worker_conflicts)

    return conflicts


async def move_booking(
    session: AsyncSession,
    org_id,
    booking_id: str,
    starts_at: datetime,
    *,
    duration_minutes: int | None = None,
    team_id: int | None = None,
) -> Booking:
    booking = await session.get(Booking, booking_id)
    if booking is None:
        raise LookupError("booking_not_found")
    if booking.org_id != org_id:
        raise PermissionError("cross_org_forbidden")
    target_team = await _team_for_org(session, org_id, team_id or booking.team_id)

    duration = duration_minutes or booking.duration_minutes or DEFAULT_SLOT_DURATION_MINUTES
    normalized_start = _normalize(starts_at)
    normalized_end = normalized_start + timedelta(minutes=duration)

    for other in await _blocking_bookings(
        session, target_team.team_id, normalized_start, normalized_end, exclude_booking_id=booking.booking_id
    ):
        if _conflicts(_normalize(other.starts_at), other.duration_minutes, normalized_start, duration):
            raise ValueError("conflict_with_existing_booking")

    blackout_stmt = select(TeamBlackout).where(
        TeamBlackout.team_id == target_team.team_id,
        TeamBlackout.starts_at < normalized_end,
        TeamBlackout.ends_at > normalized_start,
    )
    blackout = (await session.execute(blackout_stmt)).scalar_one_or_none()
    if blackout:
        raise ValueError("conflict_with_blackout")

    blocks = await availability_service.list_team_blocks(
        session,
        target_team.org_id,
        target_team.team_id,
        starts_at=normalized_start,
        ends_at=normalized_end,
    )
    if blocks:
        raise ValueError("conflict_with_availability_block")

    booking.starts_at = normalized_start
    booking.duration_minutes = duration
    booking.team_id = target_team.team_id
    await session.commit()
    await session.refresh(booking)
    logger.info(
        "booking_moved",
        extra={
            "extra": {
                "booking_id": booking.booking_id,
                "starts_at": booking.starts_at.isoformat(),
                "team_id": booking.team_id,
                "duration_minutes": booking.duration_minutes,
            }
        },
    )
    return booking


async def block_team_slot(
    session: AsyncSession,
    org_id,
    *,
    team_id: int | None,
    starts_at: datetime,
    ends_at: datetime,
    reason: str | None = None,
) -> TeamBlackout:
    target_team = await _team_for_org(session, org_id, team_id)
    normalized_start = _normalize(starts_at)
    normalized_end = _normalize(ends_at)
    if normalized_end <= normalized_start:
        raise ValueError("invalid_window")

    for booking in await _blocking_bookings(
        session, target_team.team_id, normalized_start, normalized_end
    ):
        if _conflicts(_normalize(booking.starts_at), booking.duration_minutes, normalized_start, (normalized_end - normalized_start).seconds // 60):
            raise ValueError("conflict_with_existing_booking")

    overlap_stmt = select(TeamBlackout).where(
        TeamBlackout.team_id == target_team.team_id,
        TeamBlackout.starts_at < normalized_end,
        TeamBlackout.ends_at > normalized_start,
    )
    if (await session.execute(overlap_stmt)).scalar_one_or_none():
        raise ValueError("conflict_with_blackout")

    blackout = TeamBlackout(
        team_id=target_team.team_id,
        starts_at=normalized_start,
        ends_at=normalized_end,
        reason=reason,
    )
    session.add(blackout)
    await session.commit()
    await session.refresh(blackout)
    logger.info(
        "team_slot_blocked",
        extra={"extra": {"team_id": target_team.team_id, "starts_at": normalized_start.isoformat(), "ends_at": normalized_end.isoformat()}},
    )
    return blackout


async def bulk_update_bookings(
    session: AsyncSession,
    org_id,
    booking_ids: Iterable[str],
    *,
    team_id: int | None = None,
    status: str | None = None,
    send_reminder: bool = False,
    adapter=None,
) -> dict[str, int]:
    ids = list(booking_ids)
    if not ids:
        return {"updated": 0, "reminders_sent": 0}

    stmt = select(Booking, Lead).join(Lead, Lead.lead_id == Booking.lead_id, isouter=True).where(
        Booking.org_id == org_id, Booking.booking_id.in_(ids)
    )
    result = await session.execute(stmt)
    rows = result.all()
    updated = 0
    reminders = 0

    for booking, lead in rows:
        if team_id is not None:
            booking.team_id = team_id
        if status is not None:
            booking.status = status
        updated += 1
        if send_reminder and lead:
            delivered = await email_service.send_booking_reminder_email(session, adapter, booking, lead, dedupe=True)
            if delivered:
                reminders += 1

    await session.commit()
    return {"updated": updated, "reminders_sent": reminders}


async def list_templates() -> list[dict[str, str]]:
    return [
        {"template": email_service.EMAIL_TYPE_BOOKING_PENDING, "version": "v1"},
        {"template": email_service.EMAIL_TYPE_BOOKING_CONFIRMED, "version": "v1"},
        {"template": email_service.EMAIL_TYPE_BOOKING_REMINDER, "version": "v1"},
        {"template": email_service.EMAIL_TYPE_BOOKING_COMPLETED, "version": "v1"},
        {"template": email_service.EMAIL_TYPE_INVOICE_SENT, "version": "v1"},
        {"template": email_service.EMAIL_TYPE_INVOICE_OVERDUE, "version": "v1"},
    ]


async def render_template_preview(template: str, sample_booking: Booking | None, sample_lead: Lead | None, sample_invoice: Invoice | None) -> tuple[str, str]:
    render_map = {
        email_service.EMAIL_TYPE_BOOKING_PENDING: email_service._render_booking_pending,  # noqa: SLF001
        email_service.EMAIL_TYPE_BOOKING_CONFIRMED: email_service._render_booking_confirmed,  # noqa: SLF001
        email_service.EMAIL_TYPE_BOOKING_REMINDER: email_service._render_booking_reminder,  # noqa: SLF001
        email_service.EMAIL_TYPE_BOOKING_COMPLETED: email_service._render_booking_completed,  # noqa: SLF001
    }
    invoice_renders = {
        email_service.EMAIL_TYPE_INVOICE_SENT: email_service._render_invoice_sent,  # noqa: SLF001
        email_service.EMAIL_TYPE_INVOICE_OVERDUE: email_service._render_invoice_overdue,  # noqa: SLF001
    }
    if template in render_map:
        if not sample_booking or not sample_lead:
            raise ValueError("booking_and_lead_required")
        return render_map[template](sample_booking, sample_lead)
    if template in invoice_renders:
        if not sample_invoice or not sample_lead:
            raise ValueError("invoice_and_lead_required")
        public_link = None
        if template == email_service.EMAIL_TYPE_INVOICE_SENT:
            public_link = "https://example.invalid/invoice"
        return invoice_renders[template](sample_invoice, sample_lead, public_link)
    raise ValueError("template_not_supported")


async def resend_email_event(session: AsyncSession, adapter, org_id, event_id: str) -> dict[str, str]:
    stmt = select(EmailEvent).where(EmailEvent.event_id == event_id, EmailEvent.org_id == org_id)
    event = (await session.execute(stmt)).scalar_one_or_none()
    if event is None:
        raise LookupError("event_not_found")

    delivered = await email_service._try_send_email(  # noqa: SLF001
        adapter,
        event.recipient,
        event.subject,
        event.body,
        context={"email_type": event.email_type, "booking_id": event.booking_id, "invoice_id": event.invoice_id},
    )
    status = "delivered" if delivered else "queued"
    logger.info("email_event_resend", extra={"extra": {"event_id": event.event_id, "status": status}})
    return {"event_id": event.event_id, "status": status}
