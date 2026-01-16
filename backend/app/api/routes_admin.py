import asyncio
import csv
import io
import html
import json
import logging
import math
import re
from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
import uuid
from typing import Iterable, List, Literal, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, EmailStr
import sqlalchemy as sa
from sqlalchemy import and_, func, select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import entitlements
from app.api.idempotency import enforce_org_action_rate_limit, require_idempotency
from app.api.problem_details import problem_details
from app.api.admin_auth import (
    AdminIdentity,
    require_admin,
    require_dispatch,
    require_finance,
    require_any_permission_keys,
    require_permission_keys,
    permission_keys_for_request,
    require_viewer,
    verify_admin_or_dispatcher,
)
from app.dependencies import get_bot_store
from app.domain.addons import schemas as addon_schemas
from app.domain.addons import service as addon_service
from app.domain.addons.db_models import AddonDefinition, OrderAddon
from app.domain.analytics import schemas as analytics_schemas
from app.domain.analytics.db_models import EventLog
from app.domain.analytics.service import (
    EventType,
    average_revenue_cents,
    cohort_repeat_rates,
    conversion_counts,
    duration_accuracy,
    funnel_summary,
    kpi_aggregates,
    nps_distribution,
    nps_trends,
    estimated_duration_from_booking,
    estimated_revenue_from_lead,
    log_event,
)
from app.dependencies import get_db_session
from app.infra.db import get_session_factory
from app.infra.org_context import org_id_context
from app.domain.bookings.db_models import (
    AvailabilityBlock,
    Booking,
    BookingWorker,
    EmailEvent,
    OrderPhoto,
    OrderPhotoTombstone,
    Team,
    TeamBlackout,
    TeamWorkingHours,
)
from app.domain.availability import schemas as availability_schemas
from app.domain.availability import service as availability_service
from app.domain.bookings import schemas as booking_schemas
from app.domain.bookings import service as booking_service
from app.domain.bookings.service import DEFAULT_TEAM_NAME
from app.domain.clients.db_models import (
    ClientAddress,
    ClientFeedback,
    ClientNote,
    ClientUser,
    normalize_note_type,
    normalize_tags,
    parse_tags_json,
)
from app.domain.clients import service as client_service
from app.domain.export_events import schemas as export_schemas
from app.domain.export_events.db_models import ExportEvent
from app.domain.export_events.schemas import ExportEventResponse, ExportReplayResponse
from app.domain.invoices import schemas as invoice_schemas
from app.domain.invoices import service as invoice_service
from app.domain.invoices import statuses as invoice_statuses
from app.domain.checklists.db_models import ChecklistRun, ChecklistRunItem
from app.domain.chat_threads import schemas as chat_schemas
from app.domain.chat_threads import service as chat_service
from app.domain.chat_threads.service import PARTICIPANT_ADMIN
from app.domain.message_templates import service as message_template_service
from app.domain.disputes.db_models import Dispute, FinancialAdjustmentEvent
from app.domain.documents import service as document_service
from app.domain.invoices.db_models import Invoice, InvoiceItem, InvoicePublicToken, Payment
from app.domain.leads import statuses as lead_statuses
from app.domain.leads.db_models import Lead, ReferralCredit
from app.domain.nps.db_models import NpsResponse, SupportTicket
from app.domain.leads.service import grant_referral_credit, export_payload_from_lead
from app.domain.leads.schemas import AdminLeadResponse, AdminLeadStatusUpdateRequest, admin_lead_from_model
from app.domain.leads.statuses import assert_valid_transition, is_valid_status
from app.domain.config import schemas as config_schemas
from app.domain.notifications import email_service
from app.domain.data_rights import schemas as data_rights_schemas, service as data_rights_service
from app.infra.email import resolve_app_email_adapter
from app.domain.outbox.db_models import OutboxEvent
from app.domain.outbox.schemas import OutboxEventResponse, OutboxReplayResponse
from app.domain.outbox.service import replay_outbox_event
from app.domain.queues.schemas import DLQBatchReplayResponse
from app.domain.nps import schemas as nps_schemas, service as nps_service
from app.domain.feature_modules import service as feature_service
from app.domain.pricing.config_loader import load_pricing_config
from app.domain.pricing_settings.db_models import ServiceType
from app.domain.notifications.db_models import EmailFailure
from app.domain.org_settings import service as org_settings_service
from app.domain.policy_overrides.db_models import PolicyOverrideAudit
from app.domain.reason_logs import schemas as reason_schemas
from app.domain.reason_logs import service as reason_service
from app.domain.reason_logs.db_models import ReasonLog
from app.domain.saas import billing_service, service as saas_service
from app.domain.saas.db_models import Membership, MembershipRole, Organization, PasswordResetEvent, User
from app.domain.ops import service as ops_service
from app.domain.ops.db_models import JobHeartbeat
from app.domain.ops.schemas import (
    BlockSlotRequest,
    BulkBookingsRequest,
    BulkBookingsResponse,
    GlobalSearchResult,
    ConflictCheckResponse,
    ConflictDetail,
    JobStatusResponse,
    OpsDashboardAlert,
    OpsDashboardAlertAction,
    OpsDashboardBookingStatusBand,
    OpsDashboardBookingStatusToday,
    OpsDashboardBookingStatusTotals,
    OpsDashboardResponse,
    OpsDashboardUpcomingEvent,
    MoveBookingRequest,
    QuickActionModel,
    QuickCreateBookingRequest,
    RankedWorkerSuggestion,
    ScheduleBlackout,
    ScheduleBooking,
    ScheduleSuggestions,
    ScheduleResponse,
    TeamCalendarResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    WorkerTimelineResponse,
)
from app.domain.errors import DomainError
from app.domain.retention import cleanup_retention
from app.domain.subscriptions import schemas as subscription_schemas
from app.domain.subscriptions import service as subscription_service
from app.domain.subscriptions.db_models import Subscription
from app.domain.time_tracking.db_models import WorkTimeEntry
from app.domain.admin_audit import service as audit_service
from app.domain.workers.compliance import (
    CertificateSnapshot,
    ONBOARDING_CHECKLIST_FIELDS,
    get_skill_cert_requirements,
    missing_required_certificates,
    onboarding_progress,
)
from app.domain.workers.db_models import (
    Worker,
    WorkerCertificate,
    WorkerNote,
    WorkerOnboarding,
    WorkerReview,
)
from app.infra.auth import hash_password
from app.infra.export import send_export_with_retry, validate_webhook_url
from app.infra.logging import update_log_context
from app.infra.storage import new_storage_backend
from app.infra.csrf import get_csrf_token, issue_csrf_token, render_csrf_input, require_csrf
from app.infra.bot_store import BotStore
from app.infra.i18n import render_lang_toggle, resolve_lang, tr
from app.jobs.dlq_auto_replay import run_dlq_auto_replay
from app.settings import settings

router = APIRouter(dependencies=[Depends(require_viewer)])
logger = logging.getLogger(__name__)


@router.get("/v1/admin", include_in_schema=False)
@router.get("/v1/admin/", include_in_schema=False)
async def admin_entrypoint() -> RedirectResponse:
    return RedirectResponse(url="/v1/admin/ui/invoices", status_code=status.HTTP_302_FOUND)


def _email_adapter(request: Request | None):
    if request is None:
        return None
    return resolve_app_email_adapter(request)


class AdminProfileResponse(BaseModel):
    username: str
    role: str
    permissions: list[str]


class AdminWhoamiResponse(BaseModel):
    username: str
    role: str
    org_id: uuid.UUID | None = None


async def _overdue_invoice_summary_totals(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    as_of_date: date,
) -> tuple[int, int]:
    paid_subq = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(Payment.amount_cents), 0).label("paid_cents"),
        )
        .where(Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED)
        .group_by(Payment.invoice_id)
        .subquery()
    )
    balance_expr = Invoice.total_cents - func.coalesce(paid_subq.c.paid_cents, 0)
    overdue_cutoff = as_of_date - timedelta(days=7)
    stmt = (
        select(
            func.count(Invoice.invoice_id),
            func.coalesce(func.sum(balance_expr), 0),
        )
        .outerjoin(paid_subq, paid_subq.c.invoice_id == Invoice.invoice_id)
        .where(
            Invoice.org_id == org_id,
            Invoice.due_date.is_not(None),
            Invoice.due_date <= overdue_cutoff,
            Invoice.status.in_(
                [
                    invoice_statuses.INVOICE_STATUS_SENT,
                    invoice_statuses.INVOICE_STATUS_PARTIAL,
                    invoice_statuses.INVOICE_STATUS_OVERDUE,
                ]
            ),
            balance_expr > 0,
        )
    )
    row = (await session.execute(stmt)).one()
    return int(row[0] or 0), int(row[1] or 0)


async def _unassigned_bookings_count(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    window_start_utc: datetime,
    window_end_utc: datetime,
) -> int:
    stmt = (
        select(func.count(Booking.booking_id))
        .where(
            Booking.org_id == org_id,
            Booking.archived_at.is_(None),
            Booking.starts_at >= window_start_utc,
            Booking.starts_at < window_end_utc,
            Booking.assigned_worker_id.is_(None),
            Booking.status != "CANCELLED",
        )
    )
    count = await session.scalar(stmt)
    return int(count or 0)


async def _invoices_due_today_summary(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    due_date: date,
) -> tuple[int, int]:
    paid_subq = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(Payment.amount_cents), 0).label("paid_cents"),
        )
        .where(Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED)
        .group_by(Payment.invoice_id)
        .subquery()
    )
    balance_expr = Invoice.total_cents - func.coalesce(paid_subq.c.paid_cents, 0)
    stmt = (
        select(
            func.count(Invoice.invoice_id),
            func.coalesce(func.sum(balance_expr), 0),
        )
        .outerjoin(paid_subq, paid_subq.c.invoice_id == Invoice.invoice_id)
        .where(
            Invoice.org_id == org_id,
            Invoice.due_date == due_date,
            Invoice.status.in_(
                [
                    invoice_statuses.INVOICE_STATUS_SENT,
                    invoice_statuses.INVOICE_STATUS_PARTIAL,
                    invoice_statuses.INVOICE_STATUS_OVERDUE,
                ]
            ),
            balance_expr > 0,
        )
    )
    row = (await session.execute(stmt)).one()
    return int(row[0] or 0), int(row[1] or 0)


async def _build_ops_upcoming_events(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    permission_keys: set[str],
    org_timezone: ZoneInfo,
    now_local: datetime,
    next24_start_utc: datetime,
    next24_end_utc: datetime,
) -> list[OpsDashboardUpcomingEvent]:
    events: list[OpsDashboardUpcomingEvent] = []
    now_utc = now_local.astimezone(timezone.utc)

    if "bookings.view" in permission_keys:
        soon_end_local = now_local + timedelta(hours=4)
        soon_end_utc = soon_end_local.astimezone(timezone.utc)
        unassigned_stmt = (
            select(Booking)
            .where(
                Booking.org_id == org_id,
                Booking.archived_at.is_(None),
                Booking.starts_at >= now_utc,
                Booking.starts_at < soon_end_utc,
                Booking.assigned_worker_id.is_(None),
                Booking.status != "CANCELLED",
            )
            .order_by(Booking.starts_at.asc())
            .limit(5)
        )
        unassigned_rows = (await session.execute(unassigned_stmt)).scalars().all()
        for booking in unassigned_rows:
            starts_at = booking.starts_at
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            start_local = starts_at.astimezone(org_timezone)
            events.append(
                OpsDashboardUpcomingEvent(
                    starts_at=starts_at,
                    title="Unassigned booking starting soon",
                    entity_ref={
                        "kind": "booking",
                        "booking_id": booking.booking_id,
                        "team_id": booking.team_id,
                        "status": booking.status,
                    },
                    actions=[
                        OpsDashboardAlertAction(
                            label="Open schedule",
                            href=f"/admin/schedule?date={start_local.date().isoformat()}",
                        )
                    ],
                )
            )

        tomorrow_start_local = datetime.combine(
            now_local.date() + timedelta(days=1),
            time.min,
            tzinfo=org_timezone,
        )
        tomorrow_end_local = tomorrow_start_local + timedelta(days=1)
        tomorrow_start_utc = tomorrow_start_local.astimezone(timezone.utc)
        tomorrow_end_utc = tomorrow_end_local.astimezone(timezone.utc)
        tomorrow_stmt = (
            select(Booking)
            .where(
                Booking.org_id == org_id,
                Booking.archived_at.is_(None),
                Booking.starts_at >= tomorrow_start_utc,
                Booking.starts_at < tomorrow_end_utc,
            )
            .order_by(Booking.starts_at.asc())
            .limit(1)
        )
        first_tomorrow = (await session.execute(tomorrow_stmt)).scalars().first()
        if first_tomorrow:
            starts_at = first_tomorrow.starts_at
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            if next24_start_utc <= starts_at < next24_end_utc:
                events.append(
                    OpsDashboardUpcomingEvent(
                        starts_at=starts_at,
                        title="First booking tomorrow",
                        entity_ref={
                            "kind": "booking",
                            "booking_id": first_tomorrow.booking_id,
                            "team_id": first_tomorrow.team_id,
                            "status": first_tomorrow.status,
                        },
                        actions=[
                            OpsDashboardAlertAction(
                                label="Open schedule",
                                href=f"/admin/schedule?date={tomorrow_start_local.date().isoformat()}",
                            )
                        ],
                    )
                )

    if "invoices.view" in permission_keys:
        due_count, due_total = await _invoices_due_today_summary(
            session,
            org_id,
            due_date=now_local.date(),
        )
        if due_count > 0:
            events.append(
                OpsDashboardUpcomingEvent(
                    starts_at=now_local.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(
                        timezone.utc
                    ),
                    title="Invoices due today",
                    entity_ref={
                        "kind": "invoice",
                        "count": due_count,
                        "total_cents": due_total,
                        "due_date": now_local.date().isoformat(),
                    },
                    actions=[
                        OpsDashboardAlertAction(
                            label="Review invoices",
                            href="/admin/invoices?status=SENT",
                        )
                    ],
                )
            )

    if "schedule.blocking.manage" in permission_keys:
        training_stmt = (
            select(AvailabilityBlock)
            .where(
                AvailabilityBlock.org_id == org_id,
                AvailabilityBlock.block_type == "training",
                AvailabilityBlock.starts_at < next24_end_utc,
                AvailabilityBlock.ends_at > next24_start_utc,
            )
            .order_by(AvailabilityBlock.starts_at.asc())
            .limit(5)
        )
        training_rows = (await session.execute(training_stmt)).scalars().all()
        for block in training_rows:
            starts_at = block.starts_at
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            events.append(
                OpsDashboardUpcomingEvent(
                    starts_at=starts_at,
                    title="Training block scheduled",
                    entity_ref={
                        "kind": "training_block",
                        "block_id": block.id,
                        "scope_type": block.scope_type,
                        "scope_id": block.scope_id,
                        "reason": block.reason,
                    },
                    actions=[
                        OpsDashboardAlertAction(
                            label="Manage availability blocks",
                            href="/admin/settings/availability-blocks",
                        )
                    ],
                )
            )

    return sorted(events, key=lambda event: event.starts_at)[:10]


async def _build_ops_critical_alerts(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    permission_keys: set[str],
    org_settings: org_settings_service.OrganizationSettings,
    now_local: datetime,
    next24_start_local: datetime,
    next24_end_local: datetime,
    next24_start_utc: datetime,
    next24_end_utc: datetime,
) -> list[OpsDashboardAlert]:
    alerts: list[OpsDashboardAlert] = []
    created_at = datetime.now(timezone.utc)
    currency_code = org_settings_service.resolve_currency(org_settings)

    if "invoices.view" in permission_keys and "finance.view" in permission_keys:
        overdue_count, overdue_total = await _overdue_invoice_summary_totals(
            session,
            org_id,
            as_of_date=now_local.date(),
        )
        if overdue_count > 0:
            invoice_label = "invoice" if overdue_count == 1 else "invoices"
            description = (
                f"{overdue_count} {invoice_label} are overdue by 7+ days "
                f"totaling {_format_money(overdue_total, currency_code)}."
            )
            alerts.append(
                OpsDashboardAlert(
                    type="overdue_invoices",
                    severity="critical",
                    title="Overdue invoices (7+ days)",
                    description=description,
                    entity_ref={
                        "kind": "invoice",
                        "count": overdue_count,
                        "total_cents": overdue_total,
                        "currency": currency_code,
                        "min_days_overdue": 7,
                    },
                    actions=[
                        OpsDashboardAlertAction(
                            label="Open overdue invoices",
                            href="/admin/invoices?overdue_bucket=attention",
                        ),
                        OpsDashboardAlertAction(
                            label="Open 14+ day overdue",
                            href="/admin/invoices?overdue_bucket=critical",
                        ),
                    ],
                    created_at=created_at,
                )
            )

    if "bookings.view" in permission_keys:
        unassigned_count = await _unassigned_bookings_count(
            session,
            org_id,
            window_start_utc=next24_start_utc,
            window_end_utc=next24_end_utc,
        )
        if unassigned_count > 0:
            booking_label = "booking" if unassigned_count == 1 else "bookings"
            description = (
                f"{unassigned_count} {booking_label} in the next 24 hours "
                "have no assigned worker."
            )
            alerts.append(
                OpsDashboardAlert(
                    type="unassigned_bookings_24h",
                    severity="warning",
                    title="Upcoming bookings missing workers",
                    description=description,
                    entity_ref={
                        "kind": "booking",
                        "count": unassigned_count,
                        "window_start": next24_start_local.isoformat(),
                        "window_end": next24_end_local.isoformat(),
                    },
                    actions=[
                        OpsDashboardAlertAction(
                            label="Open schedule",
                            href=f"/admin/schedule?date={next24_start_local.date().isoformat()}",
                        )
                    ],
                    created_at=created_at,
                )
            )

    alerts.append(
        OpsDashboardAlert(
            type="negative_review_placeholder",
            severity="info",
            title="Negative review alerts",
            description="Quality module disabled/no data.",
            entity_ref={
                "kind": "quality",
                "status": "disabled",
            },
            actions=[
                OpsDashboardAlertAction(
                    label="Open modules",
                    href="/admin/settings/modules",
                )
            ],
            created_at=created_at,
        )
    )

    return alerts


@router.get("/v1/admin/whoami", response_model=AdminWhoamiResponse)
async def admin_whoami(identity: AdminIdentity = Depends(require_viewer)) -> AdminWhoamiResponse:
    return AdminWhoamiResponse(
        username=identity.username,
        role=getattr(identity.role, "value", str(identity.role)),
        org_id=identity.org_id,
    )


@router.get("/v1/admin/profile", response_model=AdminProfileResponse)
async def get_admin_profile(
    request: Request, identity: AdminIdentity = Depends(require_viewer)
) -> AdminProfileResponse:
    permissions = sorted(permission_keys_for_request(request, identity))
    saas_identity = getattr(request.state, "saas_identity", None)
    if saas_identity and getattr(saas_identity, "role_key", None):
        role_value = saas_identity.role_key
    else:
        role_value = getattr(identity.role, "value", str(identity.role))
    return AdminProfileResponse(
        username=identity.username,
        role=role_value,
        permissions=permissions,
    )


@router.get("/v1/admin/dashboard/ops", response_model=OpsDashboardResponse)
async def get_ops_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("core.view")),
) -> OpsDashboardResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    guard = await _require_dashboard_enabled(request, session, org_id)
    if guard is not None:
        return guard
    permission_keys = permission_keys_for_request(request, _identity)

    org_settings = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_timezone = org_settings_service.resolve_timezone(org_settings)
    try:
        org_tz = ZoneInfo(org_timezone)
    except Exception:  # noqa: BLE001
        org_timezone = org_settings_service.DEFAULT_TIMEZONE
        org_tz = ZoneInfo(org_timezone)

    now_local = datetime.now(org_tz)
    today_start_local = datetime.combine(now_local.date(), time.min, tzinfo=org_tz)
    today_end_local = today_start_local + timedelta(days=1)
    today_start_utc = today_start_local.astimezone(timezone.utc)
    today_end_utc = today_end_local.astimezone(timezone.utc)

    next24_start_local = now_local
    next24_end_local = now_local + timedelta(hours=24)
    next24_start_utc = next24_start_local.astimezone(timezone.utc)
    next24_end_utc = next24_end_local.astimezone(timezone.utc)

    status_stmt = (
        select(Booking.status, func.count())
        .where(
            Booking.org_id == org_id,
            Booking.archived_at.is_(None),
            Booking.starts_at >= today_start_utc,
            Booking.starts_at < today_end_utc,
        )
        .group_by(Booking.status)
    )
    status_rows = (await session.execute(status_stmt)).all()
    status_counts = {status: count for status, count in status_rows}
    total_count = sum(status_counts.values())
    totals = OpsDashboardBookingStatusTotals(
        total=total_count,
        pending=status_counts.get("PENDING", 0),
        confirmed=status_counts.get("CONFIRMED", 0),
        done=status_counts.get("DONE", 0),
        cancelled=status_counts.get("CANCELLED", 0),
    )
    band_counts = await ops_service.build_booking_status_bands(
        session,
        org_id,
        today_local_date=now_local.date(),
        org_timezone=org_tz,
    )
    bands = [
        OpsDashboardBookingStatusBand(label=label, count=count)
        for label, count in band_counts
    ]

    upcoming_events = await _build_ops_upcoming_events(
        session,
        org_id,
        permission_keys=permission_keys,
        org_timezone=org_tz,
        now_local=now_local,
        next24_start_utc=next24_start_utc,
        next24_end_utc=next24_end_utc,
    )

    critical_alerts = await _build_ops_critical_alerts(
        session,
        org_id,
        permission_keys=permission_keys,
        org_settings=org_settings,
        now_local=now_local,
        next24_start_local=next24_start_local,
        next24_end_local=next24_end_local,
        next24_start_utc=next24_start_utc,
        next24_end_utc=next24_end_utc,
    )

    return OpsDashboardResponse(
        as_of=datetime.now(timezone.utc),
        org_timezone=org_timezone,
        critical_alerts=critical_alerts,
        upcoming_events=upcoming_events,
        worker_availability=[],
        booking_status_today=OpsDashboardBookingStatusToday(
            totals=totals,
            bands=bands,
        ),
    )


class AdminUserCreateRequest(BaseModel):
    email: EmailStr
    target_type: Literal["client", "worker"]
    name: str | None = None
    phone: str | None = None
    role: MembershipRole | None = None
    team_id: int | None = None


class AdminUserResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    target_type: str
    must_change_password: bool
    temp_password: str


class ResetPasswordRequest(BaseModel):
    reason: str | None = None


class AdminClientSummary(BaseModel):
    client_id: str
    name: str | None
    email: str
    phone: str | None
    address: str | None
    is_active: bool
    is_blocked: bool


class AdminAddressSummary(BaseModel):
    address_id: int
    label: str
    address_text: str
    notes: str | None = None
    is_active: bool


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _format_ts(value: float | None) -> str:
    if value is None:
        return "-"
    dt = datetime.fromtimestamp(value, tz=timezone.utc)
    return _format_dt(dt)


def _resolve_admin_org(request: Request, identity: AdminIdentity) -> uuid.UUID:
    requested_org_header = request.headers.get("X-Test-Org")
    if requested_org_header:
        try:
            requested_org = uuid.UUID(requested_org_header)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid organization header")
        saas_identity = getattr(request.state, "saas_identity", None)
        if saas_identity and requested_org != saas_identity.org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        if not saas_identity and (settings.testing or settings.app_env == "dev"):
            request.state.current_org_id = requested_org
            return requested_org
        if identity.org_id and requested_org != identity.org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        request.state.current_org_id = requested_org
        return requested_org
    org_id = entitlements.resolve_org_id(request)
    if identity.org_id and identity.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return org_id


async def _resolve_admin_membership_id(
    request: Request, session: AsyncSession, org_id: uuid.UUID, identity: AdminIdentity
) -> int:
    saas_identity = getattr(request.state, "saas_identity", None)
    user_id = getattr(saas_identity, "user_id", None) if saas_identity else None
    return await chat_service.resolve_admin_membership_id(
        session,
        org_id=org_id,
        admin_username=identity.username,
        user_id=user_id,
    )


def _parse_since_timestamp(since: str | None) -> datetime:
    if not since:
        return datetime.now(timezone.utc)
    normalized = since.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid since timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def _require_dashboard_enabled(
    request: Request, session: AsyncSession, org_id: uuid.UUID
):
    enabled = await feature_service.effective_feature_enabled(session, org_id, "module.dashboard")
    if not enabled:
        return problem_details(
            request=request,
            status=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail="Disabled by org settings",
        )
    return None


def _parse_availability_scope(scope: str | None) -> tuple[str | None, int | None]:
    if not scope:
        return (None, None)
    normalized = scope.strip().lower()
    if normalized == "org":
        return ("org", None)
    if ":" not in normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid scope format")
    prefix, value = normalized.split(":", 1)
    if prefix not in {"team", "worker"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid scope type")
    if not value.isdigit():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid scope id")
    return (prefix, int(value))


async def _chat_stream(
    request: Request,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    thread_id: uuid.UUID,
    participant_type: str,
    admin_membership_id: int | None = None,
) -> StreamingResponse:
    last_seen = _parse_since_timestamp(request.query_params.get("since"))
    last_seen_id = 0

    async def event_stream():
        nonlocal last_seen, last_seen_id
        while True:
            if await request.is_disconnected():
                break
            async with session_factory() as stream_session:
                with org_id_context(org_id):
                    messages = await chat_service.list_messages_since(
                        stream_session,
                        org_id=org_id,
                        thread_id=thread_id,
                        since=last_seen,
                        since_message_id=last_seen_id,
                    )
            if messages:
                for message in messages:
                    payload = json.dumps(jsonable_encoder(_chat_message_response(message)))
                    yield f"event: message\ndata: {payload}\n\n"
                    last_seen = message.created_at
                    last_seen_id = message.message_id
            else:
                yield ": keep-alive\n\n"
                await asyncio.sleep(2.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _chat_message_response(message) -> chat_schemas.ChatMessageResponse:
    return chat_schemas.ChatMessageResponse(
        message_id=message.message_id,
        thread_id=message.thread_id,
        sender_type=message.sender_type,
        body=message.body,
        created_at=message.created_at,
    )


def _thread_summary_response(summary: chat_service.ThreadSummary) -> chat_schemas.ChatThreadSummary:
    last_message = summary.last_message
    last_message_summary = (
        chat_schemas.ChatMessageSummary(
            message_id=last_message.message_id,
            sender_type=last_message.sender_type,
            body=last_message.body,
            created_at=last_message.created_at,
        )
        if last_message
        else None
    )
    return chat_schemas.ChatThreadSummary(
        thread_id=summary.thread.thread_id,
        thread_type=summary.thread.thread_type,
        worker_id=summary.worker_id,
        admin_membership_id=summary.admin_membership_id,
        last_message=last_message_summary,
        unread_count=summary.unread_count,
    )


@router.get(
    "/v1/admin/chat/threads",
    response_model=list[chat_schemas.ChatThreadSummary],
)
async def admin_list_chat_threads(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_viewer),
) -> list[chat_schemas.ChatThreadSummary]:
    org_id = _resolve_admin_org(request, identity)
    admin_membership_id = await _resolve_admin_membership_id(request, session, org_id, identity)
    summaries = await chat_service.list_threads(
        session,
        org_id=org_id,
        participant_type=PARTICIPANT_ADMIN,
        admin_membership_id=admin_membership_id,
    )
    return [_thread_summary_response(summary) for summary in summaries]


@router.get("/v1/admin/chat/unread-count")
async def admin_chat_unread_count(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_viewer),
) -> dict[str, int]:
    org_id = _resolve_admin_org(request, identity)
    admin_membership_id = await _resolve_admin_membership_id(request, session, org_id, identity)
    unread_count = await chat_service.count_unread_messages(
        session,
        org_id=org_id,
        participant_type=PARTICIPANT_ADMIN,
        admin_membership_id=admin_membership_id,
    )
    return {"unread_count": unread_count}


@router.get(
    "/v1/admin/chat/threads/{thread_id}/messages",
    response_model=list[chat_schemas.ChatMessageResponse],
)
async def admin_list_chat_messages(
    thread_id: uuid.UUID,
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_viewer),
) -> list[chat_schemas.ChatMessageResponse]:
    org_id = _resolve_admin_org(request, identity)
    admin_membership_id = await _resolve_admin_membership_id(request, session, org_id, identity)
    try:
        await chat_service.ensure_participant(
            session,
            org_id=org_id,
            thread_id=thread_id,
            participant_type=PARTICIPANT_ADMIN,
            admin_membership_id=admin_membership_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    messages = await chat_service.list_messages(
        session,
        org_id=org_id,
        thread_id=thread_id,
        limit=limit,
    )
    return [_chat_message_response(message) for message in messages]


@router.get("/v1/admin/chat/threads/{thread_id}/stream")
async def admin_stream_chat_messages(
    thread_id: uuid.UUID,
    request: Request,
    identity: AdminIdentity = Depends(require_viewer),
) -> StreamingResponse:
    org_id = _resolve_admin_org(request, identity)
    try:
        session_factory = getattr(request.app.state, "db_session_factory", None) or get_session_factory()
        async with session_factory() as session:
            with org_id_context(org_id):
                admin_membership_id = await _resolve_admin_membership_id(
                    request, session, org_id, identity
                )
                await chat_service.ensure_participant(
                    session,
                    org_id=org_id,
                    thread_id=thread_id,
                    participant_type=PARTICIPANT_ADMIN,
                    admin_membership_id=admin_membership_id,
                )
        return await _chat_stream(
            request,
            session_factory=session_factory,
            org_id=org_id,
            thread_id=thread_id,
            participant_type=PARTICIPANT_ADMIN,
            admin_membership_id=admin_membership_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc


@router.post(
    "/v1/admin/chat/threads/{thread_id}/messages",
    response_model=chat_schemas.ChatMessageResponse,
)
async def admin_send_chat_message(
    thread_id: uuid.UUID,
    payload: chat_schemas.ChatMessageCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> chat_schemas.ChatMessageResponse:
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")
    org_id = _resolve_admin_org(request, identity)
    admin_membership_id = await _resolve_admin_membership_id(request, session, org_id, identity)
    try:
        thread = await chat_service.ensure_participant(
            session,
            org_id=org_id,
            thread_id=thread_id,
            participant_type=PARTICIPANT_ADMIN,
            admin_membership_id=admin_membership_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    message = await chat_service.send_message(
        session,
        org_id=org_id,
        thread=thread,
        sender_type=PARTICIPANT_ADMIN,
        admin_membership_id=admin_membership_id,
        body=body,
    )
    await session.commit()
    return _chat_message_response(message)


@router.post("/v1/admin/chat/threads/{thread_id}/read")
async def admin_mark_chat_read(
    thread_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_viewer),
) -> dict[str, str]:
    org_id = _resolve_admin_org(request, identity)
    admin_membership_id = await _resolve_admin_membership_id(request, session, org_id, identity)
    try:
        await chat_service.ensure_participant(
            session,
            org_id=org_id,
            thread_id=thread_id,
            participant_type=PARTICIPANT_ADMIN,
            admin_membership_id=admin_membership_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    await chat_service.mark_thread_read(
        session,
        org_id=org_id,
        thread_id=thread_id,
        participant_type=PARTICIPANT_ADMIN,
        admin_membership_id=admin_membership_id,
    )
    await session.commit()
    return {"status": "ok"}


def _resolve_membership_role(target_type: str, explicit: MembershipRole | None) -> MembershipRole:
    if explicit:
        return explicit
    if target_type == "worker":
        return MembershipRole.WORKER
    return MembershipRole.VIEWER


@router.post("/v1/admin/users", response_model=AdminUserResponse)
async def admin_create_user(
    payload: AdminUserCreateRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> AdminUserResponse:
    org_id = _resolve_admin_org(request, identity)
    org = await session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    normalized_email = saas_service.normalize_email(payload.email)
    existing_user = await session.scalar(sa.select(User).where(User.email == normalized_email))
    if existing_user:
        membership = await session.scalar(
            sa.select(Membership).where(Membership.user_id == existing_user.user_id, Membership.org_id == org_id)
        )
        if membership:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists in organization")
        user = existing_user
    else:
        user = await saas_service.create_user(session, normalized_email)

    role = _resolve_membership_role(payload.target_type, payload.role)
    await saas_service.create_membership(session, org, user, role)

    if payload.target_type == "worker":
        team: Team | None = None
        if payload.team_id:
            team = await session.get(Team, payload.team_id)
            if not team or team.org_id != org_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid team")
        else:
            team = await session.scalar(sa.select(Team).where(Team.org_id == org_id).limit(1))
            if not team:
                team = Team(org_id=org_id, name=DEFAULT_TEAM_NAME)
                session.add(team)
                await session.flush()

        worker = Worker(
            org_id=org_id,
            team_id=team.team_id,
            name=payload.name or payload.email,
            phone=payload.phone or "unknown",
            email=normalized_email,
            role=role.value,
        )
        session.add(worker)

    temp_password = await saas_service.issue_temp_password(session, user)
    response.headers["Cache-Control"] = "no-store"
    await session.commit()
    return AdminUserResponse(
        user_id=user.user_id,
        email=user.email,
        target_type=payload.target_type,
        must_change_password=user.must_change_password,
        temp_password=temp_password,
    )


@router.post("/v1/admin/users/{user_id}/reset-temp-password", response_model=AdminUserResponse)
async def reset_temp_password(
    user_id: uuid.UUID,
    payload: ResetPasswordRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> AdminUserResponse:
    org_id = _resolve_admin_org(request, identity)
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    membership = await session.scalar(
        sa.select(Membership).where(Membership.user_id == user.user_id, Membership.org_id == org_id)
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    temp_password = await saas_service.issue_temp_password(session, user)
    await saas_service.revoke_user_sessions(session, user.user_id, reason="password_reset")
    event = PasswordResetEvent(
        org_id=org_id,
        user_id=user.user_id,
        actor_admin=identity.username,
        reason=payload.reason,
    )
    session.add(event)

    adapter = _email_adapter(request)
    if adapter:
        subject = "Your account password was reset"
        if settings.email_temp_passwords:
            body = (
                "A new temporary password was issued. Log in and change it immediately.\n\n"
                f"Temporary password: {temp_password}\n"
                "This password will only work until you change it."
            )
        else:
            body = "A new temporary password was issued. Please log in and change it immediately."
        try:
            await adapter.send_email(recipient=user.email, subject=subject, body=body)
        except Exception:
            logger.warning("password_reset_email_failed", extra={"extra": {"user_id": str(user.user_id)}})

    response.headers["Cache-Control"] = "no-store"
    await session.commit()
    target_type = "worker" if membership.role == MembershipRole.WORKER else "client"
    return AdminUserResponse(
        user_id=user.user_id,
        email=user.email,
        target_type=target_type,
        must_change_password=user.must_change_password,
        temp_password=temp_password,
    )


def _icon(name: str) -> str:
    icons = {
        "eye": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">
          <path d=\"M1.5 12s4-6.5 10.5-6.5S22.5 12 22.5 12s-4 6.5-10.5 6.5S1.5 12 1.5 12Z\" />
          <circle cx=\"12\" cy=\"12\" r=\"3.5\" />
        </svg>
        """,
        "receipt": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">
          <path d=\"M7 3.5 9 2l2 1.5L13 2l2 1.5L17 2l2 1.5V21l-2-1.5-2 1.5-2-1.5-2 1.5-2-1.5-2 1.5V3.5Z\" />
          <path d=\"M8.5 8.5h7M8.5 12h7M8.5 15.5h4\" />
        </svg>
        """,
        "search": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">
          <circle cx=\"11\" cy=\"11\" r=\"6.5\" />
          <path d=\"m16 16 4.5 4.5\" />
        </svg>
        """,
        "copy": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">
          <rect x=\"8\" y=\"8\" width=\"11\" height=\"11\" rx=\"2.5\" />
          <path d=\"M5 15.5V6.5A2.5 2.5 0 0 1 7.5 4H15\" />
        </svg>
        """,
        "warning": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\"> 
          <path d=\"m12 3.5 9 16H3l9-16Z\" />
          <path d=\"M12 10v4.5M12 18.1h.01\" />
        </svg>
        """,
        "users": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">
          <path d=\"M17 21v-2.5A3.5 3.5 0 0 0 13.5 15h-7A3.5 3.5 0 0 0 3 18.5V21\" />
          <circle cx=\"10\" cy=\"7\" r=\"3.5\" />
          <path d=\"M21 21v-2a3 3 0 0 0-2.5-3 3.1 3.1 0 0 0-1.3 0\" />
          <path d=\"M17.5 3.5a3 3 0 1 1-2 5.3\" />
        </svg>
        """,
        "calendar": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">
          <rect x=\"3.5\" y=\"5\" width=\"17\" height=\"15.5\" rx=\"2.5\" />
          <path d=\"M7.5 3.5v3M16.5 3.5v3M3.5 9.5h17\" />
        </svg>
        """,
        "edit": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">
          <path d=\"M4 20h4l11-11-4-4L4 16v4Z\" />
          <path d=\"M14 5 19 10\" />
        </svg>
        """,
        "message-circle": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">
          <path d=\"M21 11.5a7.5 7.5 0 0 1-7.5 7.5H8l-4 3v-6A7.5 7.5 0 1 1 21 11.5Z\" />
        </svg>
        """,
        "plus": """
        <svg class=\"icon\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">
          <path d=\"M12 5v14M5 12h14\" />
        </svg>
        """,
    }
    return icons.get(name, "")


def _filter_badge(filter_key: str, active_filters: set[str], lang: str | None) -> str:
    labels = {
        "needs_human": tr(lang, "admin.filters.needs_human"),
        "waiting_for_contact": tr(lang, "admin.filters.waiting_for_contact"),
        "order_created": tr(lang, "admin.filters.order_created"),
    }
    label = labels.get(filter_key, filter_key)
    is_active = filter_key in active_filters
    href = "" if is_active else f"?filters={filter_key}"
    class_name = "badge" + (" badge-active" if is_active else "")
    return f'<a class="{class_name}" href="{href}">{html.escape(label)}</a>'


def _render_filters(active_filters: set[str], lang: str | None) -> str:
    parts = [
        '<div class="filters">',
        f"<div class=\"with-icon\">{_icon('search')}<strong>{tr(lang, 'admin.filters.title')}</strong></div>",
        _filter_badge("needs_human", active_filters, lang),
        _filter_badge("waiting_for_contact", active_filters, lang),
        _filter_badge("order_created", active_filters, lang),
        f'<a class="badge" href="/v1/admin/observability">{tr(lang, "admin.filters.clear")}</a>',
        "</div>",
    ]
    return "".join(parts)


def _render_section(title: str, body: str) -> str:
    return f"<section><h2>{html.escape(title)}</h2>{body}</section>"


def _render_empty(message: str) -> str:
    return f"<p class=\"muted\">{html.escape(message)}</p>"


def _render_leads(leads: Iterable[Lead], active_filters: set[str], lang: str | None) -> str:
    cards: list[str] = []
    tag_labels = {
        "needs_human": tr(lang, "admin.filters.needs_human"),
        "waiting_for_contact": tr(lang, "admin.filters.waiting_for_contact"),
        "order_created": tr(lang, "admin.filters.order_created"),
    }
    for lead in leads:
        tags: set[str] = set()
        bookings_count = len(getattr(lead, "bookings", []))
        if lead.status == lead_statuses.LEAD_STATUS_NEW:
            tags.add("waiting_for_contact")
        if bookings_count:
            tags.add("order_created")

        if active_filters and not active_filters.intersection(tags):
            continue

        contact_bits = [html.escape(lead.phone)]
        if lead.email:
            contact_bits.append(html.escape(lead.email))
        contact = " · ".join(contact_bits)
        tag_text = " ".join(
            f"<span class=\"tag\">{html.escape(tag_labels.get(t, t))}</span>" for t in sorted(tags)
        )
        cards.append(
            """
            <div class="card">
              <div class="card-row">
                <div>
                  <div class="title">{name}</div>
                  <div class="muted">{contact}</div>
                </div>
                <div class="status">{status}</div>
              </div>
              <div class="card-row">
                <div class="muted">{created}</div>
                <div>{tags}</div>
              </div>
              <div class="muted">{notes}</div>
            </div>
            """.format(
                name=html.escape(lead.name),
                contact=contact,
                status=html.escape(lead.status),
                created=html.escape(tr(lang, "admin.leads.created_at", created=_format_dt(lead.created_at))),
                notes=html.escape(tr(lang, "admin.leads.notes", notes=lead.notes or "-")),
                tags=tag_text,
            )
        )
    if not cards:
        return _render_empty(tr(lang, "admin.empty.leads"))
    return "".join(cards)


def _render_cases(cases: Iterable[object], active_filters: set[str], lang: str | None) -> str:
    cards: list[str] = []
    for case in cases:
        tags = {"needs_human"}
        if active_filters and not active_filters.intersection(tags):
            continue
        summary = getattr(case, "summary", tr(lang, "admin.cases.default_summary")) or tr(
            lang, "admin.cases.default_summary"
        )
        reason = getattr(case, "reason", "-")
        conversation_id = getattr(case, "source_conversation_id", None)
        cards.append(
            """
            <div class="card">
              <div class="card-row">
                <div>
                  <div class="title">{summary}</div>
                  <div class="muted">{reason_label} {reason}</div>
                </div>
                <div class="muted">{created}</div>
              </div>
              <div class="card-row">
                <a class="btn" href="/v1/admin/observability/cases/{case_id}">{view_detail}</a>
                <div class="muted">{conversation_label}: {conversation}</div>
              </div>
            </div>
            """.format(
                summary=html.escape(summary),
                reason_label=html.escape(tr(lang, "admin.labels.reason")),
                reason=html.escape(reason),
                created=html.escape(
                    tr(lang, "admin.cases.created_at", created=_format_ts(getattr(case, "created_at", None)))
                ),
                case_id=html.escape(getattr(case, "case_id", "")),
                view_detail=html.escape(tr(lang, "admin.cases.view_detail")),
                conversation_label=html.escape(tr(lang, "admin.labels.conversation")),
                conversation=html.escape(conversation_id or "n/a"),
            )
        )
    if not cards:
        return _render_empty(tr(lang, "admin.empty.cases"))
    return "".join(cards)


def _render_dialogs(
    conversations: Iterable[object],
    message_lookup: dict[str, list[object]],
    active_filters: set[str],
    lang: str | None,
) -> str:
    cards: list[str] = []
    for conversation in conversations:
        tags: set[str] = set()
        status = getattr(conversation, "status", "")
        if str(status).lower() == "handed_off":
            tags.add("needs_human")

        if active_filters and not active_filters.intersection(tags):
            continue

        messages = message_lookup.get(conversation.conversation_id, [])
        last_message = messages[-1].text if messages else tr(lang, "admin.dialogs.no_messages")
        cards.append(
            """
            <div class="card">
              <div class="card-row">
                <div class="title">{conversation_id}</div>
                <div class="status">{status}</div>
              </div>
              <div class="muted">{last_message_label}: {last_message}</div>
              <div class="muted">{updated_label} {updated_at}</div>
            </div>
            """.format(
                conversation_id=html.escape(conversation.conversation_id),
                status=html.escape(str(status)),
                last_message=html.escape(last_message),
                last_message_label=html.escape(tr(lang, "admin.dialogs.last_message")),
                updated_label=html.escape(tr(lang, "admin.dialogs.updated")),
                updated_at=html.escape(_format_ts(getattr(conversation, "updated_at", None))),
            )
        )
    if not cards:
        return _render_empty(tr(lang, "admin.empty.dialogs"))
    return "".join(cards)


def _wrap_page(
    request: Request,
    content: str,
    *,
    title: str = "Admin",
    active: str | None = None,
    page_lang: str | None = None,
) -> str:
    resolved_lang = resolve_lang(request)
    page_lang = page_lang or resolved_lang
    nav_lang = "en" if active == "invoices" else resolved_lang
    chat_badge = '<span class="nav-badge" id="nav-chat-badge"></span>'
    nav_links = [
        (
            _icon("eye") + html.escape(tr(nav_lang, "admin.nav.observability")),
            "/v1/admin/observability",
            "observability",
        ),
        (
            _icon("users") + html.escape(tr(nav_lang, "admin.nav.workers")) + chat_badge,
            "/v1/admin/ui/workers",
            "workers",
        ),
        (
            _icon("users") + html.escape(tr(nav_lang, "admin.nav.teams")),
            "/v1/admin/ui/teams",
            "teams",
        ),
        (
            _icon("users") + html.escape(tr(nav_lang, "admin.nav.clients")),
            "/v1/admin/ui/clients",
            "clients",
        ),
        (
            _icon("calendar") + html.escape(tr(nav_lang, "admin.nav.dispatch")),
            "/v1/admin/ui/dispatch",
            "dispatch",
        ),
        (
            _icon("receipt") + html.escape(tr(nav_lang, "admin.nav.invoices")),
            "/v1/admin/ui/invoices",
            "invoices",
        ),
    ]
    nav = "".join(
        f'<a class="nav-link{" nav-link-active" if active == key else ""}" href="{href}"><span class="with-icon">{label}</span></a>'
        for label, href, key in nav_links
    )
    lang_toggle = render_lang_toggle(request, resolved_lang)
    return f"""
    <html lang=\"{html.escape(page_lang)}\">
      <head>
        <title>{html.escape(title)}</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 0; background: #f8fafc; color: #111827; }}
          h1 {{ margin: 0 0 8px; font-size: 24px; }}
          h2 {{ margin: 24px 0 12px; font-size: 18px; }}
          a {{ color: #2563eb; }}
          .page {{ max-width: 1080px; margin: 0 auto; padding: 24px; }}
          .topbar {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; gap: 16px; flex-wrap: wrap; }}
          .topbar-actions {{ display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
          .nav {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
          .nav-link {{ text-decoration: none; color: #374151; padding: 8px 12px; border-radius: 10px; border: 1px solid transparent; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
          .nav-link-active {{ background: #111827; color: #fff; border-color: #111827; box-shadow: 0 1px 2px rgba(0,0,0,0.08); }}
          .nav-badge {{ display: inline-flex; align-items: center; justify-content: center; min-width: 20px; height: 20px; padding: 0 6px; border-radius: 999px; background: #2563eb; color: #fff; font-size: 11px; font-weight: 700; margin-left: 6px; }}
          .nav-badge:empty {{ display: none; }}
          .lang-toggle {{ display: flex; gap: 8px; font-size: 13px; align-items: center; }}
          .lang-link {{ text-decoration: none; color: #374151; padding: 6px 10px; border-radius: 8px; border: 1px solid transparent; font-weight: 600; background: #fff; }}
          .lang-link-active {{ background: #111827; color: #fff; border-color: #111827; box-shadow: 0 1px 2px rgba(0,0,0,0.08); }}
          .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 10px 15px -10px rgba(15,23,42,0.15); }}
          .card-row {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }}
          .title {{ font-weight: 600; }}
          .status {{ font-weight: 600; color: #2563eb; }}
          .muted {{ color: #6b7280; font-size: 13px; }}
          .small {{ font-size: 12px; }}
          .filters {{ display: flex; gap: 8px; align-items: flex-end; margin-bottom: 16px; flex-wrap: wrap; }}
          .form-group {{ display: flex; flex-direction: column; gap: 6px; font-size: 13px; }}
          .input {{ padding: 8px 10px; border-radius: 8px; border: 1px solid #d1d5db; min-width: 160px; font-size: 14px; background: #fff; }}
          .badge {{ display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; border: 1px solid #d1d5db; text-decoration: none; color: #111827; font-size: 13px; background: #fff; }}
          .badge-low {{ background: #f3f4f6; color: #374151; border-color: #e5e7eb; }}
          .badge-medium {{ background: #fffbeb; color: #92400e; border-color: #fcd34d; }}
          .badge-high {{ background: #fef2f2; color: #b91c1c; border-color: #fecaca; }}
          .badge-active {{ background: #2563eb; color: #fff; border-color: #2563eb; }}
          .badge-status {{ font-weight: 600; }}
          .note-badge {{ font-weight: 600; }}
          .note-badge-note {{ background: #f3f4f6; color: #374151; border-color: #e5e7eb; }}
          .note-badge-complaint {{ background: #fef2f2; color: #b91c1c; border-color: #fecaca; }}
          .note-badge-praise {{ background: #ecfdf3; color: #065f46; border-color: #a7f3d0; }}
          .status-draft {{ background: #f3f4f6; }}
          .status-sent {{ background: #eef2ff; color: #4338ca; border-color: #c7d2fe; }}
          .status-partial {{ background: #fffbeb; color: #92400e; border-color: #fcd34d; }}
          .status-paid {{ background: #ecfdf3; color: #065f46; border-color: #a7f3d0; }}
          .status-overdue {{ background: #fef2f2; color: #b91c1c; border-color: #fecaca; }}
          .status-void {{ background: #f3f4f6; color: #374151; }}
          .btn {{ padding: 10px 14px; background: #111827; color: #fff; border-radius: 8px; text-decoration: none; font-size: 13px; border: none; cursor: pointer; display: inline-flex; align-items: center; gap: 8px; }}
          .btn.secondary {{ background: #fff; color: #111827; border: 1px solid #d1d5db; }}
          .btn.small {{ padding: 8px 10px; font-size: 12px; }}
          .btn:disabled {{ opacity: 0.6; cursor: not-allowed; }}
          .tag {{ display: inline-block; background: #eef2ff; color: #4338ca; padding: 4px 8px; border-radius: 8px; font-size: 12px; margin-left: 4px; }}
          .table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }}
          .table th, .table td {{ padding: 12px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; }}
          .table th {{ background: #f9fafb; font-weight: 600; }}
          .table .muted {{ font-size: 12px; }}
          .table .align-right {{ text-align: right; }}
          .pill {{ display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; border-radius: 10px; border: 1px solid #e5e7eb; background: #f9fafb; }}
          .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-top: 12px; }}
          .metric {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px; }}
          .metric .label {{ font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.03em; }}
          .metric .value {{ font-size: 18px; font-weight: 700; margin-top: 2px; }}
          .danger {{ color: #b91c1c; }}
          .success {{ color: #065f46; }}
          .chip {{ display: inline-flex; align-items: center; gap: 8px; background: #eef2ff; border: 1px solid #c7d2fe; padding: 8px 10px; border-radius: 10px; font-size: 13px; }}
          .stack {{ display: flex; flex-direction: column; gap: 8px; }}
          .row-highlight {{ background: #fffbeb; }}
          .actions {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
          .section {{ margin-top: 16px; }}
          .note {{ padding: 10px 12px; background: #f9fafb; border: 1px dashed #d1d5db; border-radius: 10px; }}
          .with-icon {{ display: inline-flex; align-items: center; gap: 8px; }}
          .icon {{ width: 18px; height: 18px; display: block; }}
          .progress {{ width: 100%; height: 10px; background: #e5e7eb; border-radius: 999px; overflow: hidden; }}
          .progress-fill {{ height: 100%; background: #2563eb; }}
          .progress-meta {{ display: flex; justify-content: space-between; font-size: 12px; color: #6b7280; }}
        </style>
      </head>
      <body>
        <div class="page">
          <div class="topbar">
            <h1>{html.escape(title)}</h1>
            <div class="topbar-actions">
              <div class="nav">{nav}</div>
              <div class="lang-toggle">{lang_toggle}</div>
            </div>
          </div>
          {content}
        </div>
        <script>
          (function() {{
            const badge = document.getElementById('nav-chat-badge');
            if (!badge || !window.fetch) return;
            fetch('/v1/admin/chat/unread-count', {{ credentials: 'same-origin' }})
              .then((response) => response.ok ? response.json() : null)
              .then((data) => {{
                if (!data || !badge) return;
                if (data.unread_count) {{
                  badge.textContent = String(data.unread_count);
                }}
              }})
              .catch(() => null);
          }})();
        </script>
      </body>
    </html>
    """


@router.get("/v1/admin/leads", response_model=List[AdminLeadResponse])
async def list_leads(
    request: Request,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_viewer),
) -> List[AdminLeadResponse]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    stmt = (
        select(Lead)
        .options(
            selectinload(Lead.referral_credits),
            selectinload(Lead.referred_credit),
        )
        .where(Lead.org_id == org_id)
        .order_by(Lead.created_at.desc())
        .limit(limit)
    )
    if status_filter and hasattr(Lead, "status"):
        normalized = status_filter.upper()
        if not is_valid_status(normalized):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid lead status filter: {status_filter}",
            )
        stmt = stmt.where(Lead.status == normalized)
    result = await session.execute(stmt)
    leads = result.scalars().all()
    return [admin_lead_from_model(lead) for lead in leads]


@router.post("/v1/admin/leads/{lead_id}/status", response_model=AdminLeadResponse)
async def update_lead_status(
    http_request: Request,
    lead_id: str,
    payload: AdminLeadStatusUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> AdminLeadResponse:
    org_id = getattr(http_request.state, "org_id", None) or entitlements.resolve_org_id(http_request)
    lead_result = await session.execute(
        select(Lead).where(Lead.lead_id == lead_id, Lead.org_id == org_id)
    )
    lead = lead_result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    before = admin_lead_from_model(lead).model_dump(mode="json")

    try:
        assert_valid_transition(lead.status, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    lead.status = payload.status
    credit_count = await session.scalar(
        select(func.count()).select_from(ReferralCredit).where(ReferralCredit.referrer_lead_id == lead.lead_id)
    )
    response_body = admin_lead_from_model(lead, referral_credit_count=int(credit_count or 0))

    http_request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="lead_status_update",
        resource_type="lead",
        resource_id=lead.lead_id,
        before=before,
        after=response_body.model_dump(mode="json"),
    )
    await session.commit()
    return response_body


@router.post("/v1/admin/email-scan", status_code=status.HTTP_202_ACCEPTED)
async def email_scan(
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> dict[str, int]:
    adapter = resolve_app_email_adapter(http_request.app)
    result = await email_service.scan_and_send_reminders(session, adapter)
    return result


@router.post("/v1/admin/bookings/{booking_id}/resend-last-email", status_code=status.HTTP_202_ACCEPTED)
async def resend_last_email(
    booking_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> dict[str, str]:
    org_id = getattr(http_request.state, "org_id", None) or entitlements.resolve_org_id(http_request)
    rate_limited = await enforce_org_action_rate_limit(http_request, org_id, "resend_email")
    if rate_limited:
        return rate_limited
    idempotency = await require_idempotency(http_request, session, org_id, "resend_last_email")
    if isinstance(idempotency, Response):
        return idempotency
    if idempotency.existing_response:
        return idempotency.existing_response
    booking_result = await session.execute(
        select(Booking)
        .where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        .options(selectinload(Booking.worker_assignments))
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    adapter = resolve_app_email_adapter(http_request.app)
    try:
        result = await email_service.resend_last_email(session, adapter, booking_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No prior email for booking") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Email send failed") from exc

    http_request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="booking_resend_email",
        resource_type="booking",
        resource_id=booking_id,
        before=None,
        after=result,
    )
    await idempotency.save_response(
        session,
        status_code=status.HTTP_202_ACCEPTED,
        body=result,
    )
    await session.commit()
    return result


def _serialize_hit(hit) -> GlobalSearchResult:
    return GlobalSearchResult(
        kind=hit.kind,
        ref=hit.ref,
        label=hit.label,
        status=hit.status,
        quick_actions=[QuickActionModel(**action.__dict__) for action in hit.quick_actions],
    )


@router.get("/v1/admin/search", response_model=list[GlobalSearchResult])
async def global_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_viewer),
) -> list[GlobalSearchResult]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    hits = await ops_service.global_search(session, org_id, q, limit)
    return [_serialize_hit(hit) for hit in hits]


@router.get("/v1/admin/clients", response_model=list[AdminClientSummary])
async def list_clients(
    request: Request,
    q: str | None = Query(default=None, min_length=1, max_length=120),
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("contacts.view")),
) -> list[AdminClientSummary]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    stmt = (
        select(ClientUser)
        .where(ClientUser.org_id == org_id, ClientUser.is_active.is_(True))
        .order_by(ClientUser.name.asc(), ClientUser.email.asc())
        .limit(limit)
    )
    if q:
        needle = f"%{q.lower().strip()}%"
        stmt = stmt.where(
            or_(
                func.lower(ClientUser.name).like(needle),
                func.lower(ClientUser.email).like(needle),
                func.lower(ClientUser.phone).like(needle),
            )
        )
    clients = (await session.execute(stmt)).scalars().all()
    return [
        AdminClientSummary(
            client_id=client.client_id,
            name=client.name,
            email=client.email,
            phone=client.phone,
            address=client.address,
            is_active=client.is_active,
            is_blocked=client.is_blocked,
        )
        for client in clients
    ]


@router.get("/v1/admin/clients/{client_id}/addresses", response_model=list[AdminAddressSummary])
async def list_client_addresses(
    request: Request,
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("contacts.view")),
) -> list[AdminAddressSummary]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    stmt = (
        select(ClientAddress)
        .where(
            ClientAddress.org_id == org_id,
            ClientAddress.client_id == client_id,
            ClientAddress.is_active.is_(True),
        )
        .order_by(ClientAddress.created_at.desc())
    )
    addresses = (await session.execute(stmt)).scalars().all()
    return [
        AdminAddressSummary(
            address_id=address.address_id,
            label=address.label,
            address_text=address.address_text,
            notes=address.notes,
            is_active=address.is_active,
        )
        for address in addresses
    ]


@router.get("/v1/admin/schedule", response_model=ScheduleResponse)
async def list_schedule(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    worker_id: int | None = None,
    team_id: int | None = None,
    status: str | None = None,
    query: str | None = Query(default=None, alias="q"),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("bookings.view")),
) -> ScheduleResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    resolved_from = from_date or date.today()
    resolved_to = to_date or resolved_from
    org_settings = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_timezone = org_settings_service.resolve_timezone(org_settings)
    payload = await ops_service.list_schedule(
        session,
        org_id,
        resolved_from,
        resolved_to,
        org_timezone=org_timezone,
        worker_id=worker_id,
        team_id=team_id,
        status=status,
        limit=limit,
        offset=offset,
        query=query,
    )
    return ScheduleResponse(**payload)


@router.get("/v1/admin/schedule/team_calendar", response_model=TeamCalendarResponse)
async def get_team_calendar(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    team_id: int | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("bookings.view")),
) -> TeamCalendarResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    resolved_from = from_date or date.today()
    resolved_to = to_date or resolved_from
    org_settings = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_timezone = org_settings_service.resolve_timezone(org_settings)
    payload = await ops_service.list_team_calendar(
        session,
        org_id,
        resolved_from,
        resolved_to,
        org_timezone=org_timezone,
        team_id=team_id,
        status=status,
    )
    return TeamCalendarResponse(**payload)


@router.get("/v1/admin/schedule/worker_timeline", response_model=WorkerTimelineResponse)
async def get_worker_timeline(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    worker_id: int | None = None,
    team_id: int | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("bookings.view")),
) -> WorkerTimelineResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    resolved_from = from_date or date.today()
    resolved_to = to_date or resolved_from
    org_settings = await org_settings_service.get_or_create_org_settings(session, org_id)
    org_timezone = org_settings_service.resolve_timezone(org_settings)
    payload = await ops_service.list_worker_timeline(
        session,
        org_id,
        resolved_from,
        resolved_to,
        org_timezone=org_timezone,
        worker_id=worker_id,
        team_id=team_id,
        status=status,
    )
    return WorkerTimelineResponse(**payload)


@router.get(
    "/v1/admin/availability-blocks",
    response_model=list[availability_schemas.AvailabilityBlockResponse],
)
async def list_availability_blocks(
    request: Request,
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    scope: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("bookings.view")),
) -> list[availability_schemas.AvailabilityBlockResponse]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    scope_type, scope_id = _parse_availability_scope(scope)
    blocks = await availability_service.list_blocks(
        session,
        org_id,
        starts_at=from_at,
        ends_at=to_at,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    return [availability_schemas.AvailabilityBlockResponse.model_validate(block) for block in blocks]


@router.post(
    "/v1/admin/availability-blocks",
    response_model=availability_schemas.AvailabilityBlockResponse,
)
async def create_availability_block(
    request: Request,
    payload: availability_schemas.AvailabilityBlockCreate,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(
        require_any_permission_keys("settings.manage", "schedule.blocking.manage")
    ),
) -> availability_schemas.AvailabilityBlockResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    try:
        block = await availability_service.create_block(
            session,
            org_id,
            payload=payload,
            created_by=identity.username,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return availability_schemas.AvailabilityBlockResponse.model_validate(block)


@router.patch(
    "/v1/admin/availability-blocks/{block_id}",
    response_model=availability_schemas.AvailabilityBlockResponse,
)
async def update_availability_block(
    block_id: int,
    request: Request,
    payload: availability_schemas.AvailabilityBlockUpdate,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(
        require_any_permission_keys("settings.manage", "schedule.blocking.manage")
    ),
) -> availability_schemas.AvailabilityBlockResponse:
    fields_set = payload.model_fields_set
    if not fields_set:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No updates provided")
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    try:
        block = await availability_service.update_block(
            session,
            org_id,
            block_id,
            payload=payload,
            reason_set="reason" in fields_set,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return availability_schemas.AvailabilityBlockResponse.model_validate(block)


@router.delete("/v1/admin/availability-blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_availability_block(
    block_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(
        require_any_permission_keys("settings.manage", "schedule.blocking.manage")
    ),
) -> Response:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    try:
        await availability_service.delete_block(session, org_id, block_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/admin/schedule/suggestions", response_model=ScheduleSuggestions)
async def suggest_schedule(
    request: Request,
    starts_at: datetime,
    ends_at: datetime | None = None,
    duration_min: int | None = Query(None, ge=1),
    address_id: int | None = None,
    service_type_id: int | None = None,
    skill_tags: list[str] | None = Query(None),
    booking_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> ScheduleSuggestions:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    resolved_end = ends_at
    if resolved_end is None:
        if duration_min is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing ends_at or duration_min")
        resolved_end = starts_at + timedelta(minutes=duration_min)
    try:
        suggestions = await ops_service.suggest_schedule_resources(
            session,
            org_id,
            starts_at=starts_at,
            ends_at=resolved_end,
            skill_tags=skill_tags,
            exclude_booking_id=booking_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    ranked_workers = [
        RankedWorkerSuggestion(
            worker_id=worker["worker_id"],
            name=worker["name"],
            team_id=worker["team_id"],
            team_name=worker["team_name"],
            reasons=["available"],
        )
        for worker in sorted(suggestions.get("workers", []), key=lambda item: (item.get("name") or ""))
    ]
    if address_id:
        ranked_workers = [
            worker.model_copy(update={"reasons": [*worker.reasons, "address_provided"]})
            for worker in ranked_workers
        ]
    if service_type_id:
        ranked_workers = [
            worker.model_copy(update={"reasons": [*worker.reasons, "service_type_provided"]})
            for worker in ranked_workers
        ]

    return ScheduleSuggestions(**suggestions, ranked_workers=ranked_workers)


@router.get("/v1/admin/schedule/addons", response_model=list[addon_schemas.AddonDefinitionResponse])
async def list_schedule_addons(
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("bookings.edit")),
) -> list[addon_schemas.AddonDefinitionResponse]:
    addons = await addon_service.list_definitions(session, include_inactive=False)
    return [_addon_response(addon) for addon in addons]


@router.post("/v1/admin/schedule/quick-create", response_model=ScheduleBooking)
async def quick_create_booking(
    request: Request,
    payload: QuickCreateBookingRequest,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_permission_keys("bookings.edit")),
) -> ScheduleBooking:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    normalized_start = booking_service._normalize_datetime(payload.starts_at)
    duration_minutes = payload.duration_minutes
    ends_at = normalized_start + timedelta(minutes=duration_minutes)

    if payload.client_id:
        client = (
            await session.execute(
                select(ClientUser).where(
                    ClientUser.client_id == payload.client_id,
                    ClientUser.org_id == org_id,
                    ClientUser.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if client is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    else:
        normalized_email = payload.client.email.lower().strip() if payload.client else None
        if not normalized_email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Client email is required")
        client = (
            await session.execute(
                select(ClientUser).where(func.lower(ClientUser.email) == normalized_email)
            )
        ).scalar_one_or_none()
        if client and client.org_id != org_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Client email belongs to another org")
        if client is None:
            client = ClientUser(
                org_id=org_id,
                email=normalized_email,
                name=payload.client.name if payload.client else None,
                phone=payload.client.phone if payload.client else None,
            )
            session.add(client)
            await session.flush()
        elif payload.client:
            if not client.name:
                client.name = payload.client.name
            if not client.phone:
                client.phone = payload.client.phone

    address_id = payload.address_id
    if address_id:
        address = (
            await session.execute(
                select(ClientAddress).where(
                    ClientAddress.address_id == address_id,
                    ClientAddress.client_id == client.client_id,
                    ClientAddress.org_id == org_id,
                    ClientAddress.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if address is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")
    else:
        if not payload.address_text:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Address text is required")
        address = ClientAddress(
            org_id=org_id,
            client_id=client.client_id,
            label=(payload.address_label or "Primary").strip() or "Primary",
            address_text=payload.address_text.strip(),
        )
        session.add(address)
        await session.flush()
        address_id = address.address_id
        if not client.address:
            client.address = address.address_text

    service_type_name = None
    if payload.service_type_id is not None:
        service_type = (
            await session.execute(
                select(ServiceType).where(
                    ServiceType.service_type_id == payload.service_type_id,
                    ServiceType.org_id == org_id,
                    ServiceType.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if service_type is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service type not found")
        service_type_name = service_type.name

    assigned_worker_id = payload.assigned_worker_id
    team_id = None
    if assigned_worker_id is not None:
        worker = await session.get(Worker, assigned_worker_id)
        if worker is None or worker.org_id != org_id or not worker.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
        team_id = worker.team_id
    else:
        team = await booking_service.ensure_default_team(session, org_id=org_id)
        team_id = team.team_id

    if not await booking_service.is_slot_available(
        normalized_start, duration_minutes, session, team_id=team_id
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slot is not available")

    if assigned_worker_id is not None:
        worker_conflicts = await ops_service.check_schedule_conflicts(
            session,
            org_id,
            starts_at=normalized_start,
            ends_at=ends_at,
            team_id=team_id,
            worker_id=assigned_worker_id,
        )
        if worker_conflicts:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Worker is not available")

    decision = await booking_service.evaluate_deposit_policy(
        session=session,
        lead=None,
        starts_at=normalized_start,
        deposit_percent=settings.deposit_percent,
        deposits_enabled=settings.deposits_enabled,
        service_type=service_type_name,
        estimated_total=payload.price_cents / 100 if payload.price_cents else None,
    )
    policy_snapshot = decision.policy_snapshot
    if service_type_name or payload.price_cents:
        policy_snapshot = policy_snapshot.model_copy(
            update={
                "service_type": service_type_name,
                "total_amount_cents": payload.price_cents,
            }
        )

    deposit_required = decision.required
    deposit_cents = decision.deposit_cents
    deposit_policy = decision.reasons
    if payload.deposit_cents is not None:
        updated_deposit = policy_snapshot.deposit.model_copy(
            update={
                "required": payload.deposit_cents > 0,
                "amount_cents": payload.deposit_cents,
            }
        )
        policy_snapshot = policy_snapshot.model_copy(update={"deposit": updated_deposit})
        deposit_required = payload.deposit_cents > 0
        deposit_cents = payload.deposit_cents
        deposit_policy = [*deposit_policy, "manual_override"]

    booking = Booking(
        booking_id=str(uuid.uuid4()),
        org_id=org_id,
        client_id=client.client_id,
        address_id=address_id,
        team_id=team_id,
        assigned_worker_id=assigned_worker_id,
        starts_at=normalized_start,
        duration_minutes=duration_minutes,
        planned_minutes=duration_minutes,
        status="PENDING",
        deposit_required=deposit_required,
        deposit_cents=deposit_cents,
        deposit_policy=deposit_policy,
        deposit_status="pending" if deposit_required else None,
        base_charge_cents=payload.price_cents,
        policy_snapshot=policy_snapshot.model_dump(mode="json"),
        refund_total_cents=0,
        credit_note_total_cents=0,
    )
    session.add(booking)
    await session.flush()

    if payload.addon_ids:
        addon_stmt = select(AddonDefinition).where(
            AddonDefinition.addon_id.in_(payload.addon_ids),
            AddonDefinition.is_active.is_(True),
        )
        addon_rows = (await session.execute(addon_stmt)).scalars().all()
        if len(addon_rows) != len(set(payload.addon_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid addon selection")
        selections = [
            addon_schemas.OrderAddonSelection(addon_id=addon_id, qty=1)
            for addon_id in payload.addon_ids
        ]
        await addon_service.set_order_addons(session, booking.booking_id, selections)

    await audit_service.record_action(
        session,
        identity=identity,
        action="CREATE_BOOKING",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=None,
        after={
            "team_id": team_id,
            "client_id": client.client_id,
            "assigned_worker_id": assigned_worker_id,
            "starts_at": normalized_start.isoformat(),
            "duration_minutes": duration_minutes,
            "price_cents": payload.price_cents,
            "deposit_cents": deposit_cents,
        },
    )
    await session.commit()

    booking_payload = await ops_service.fetch_schedule_booking(session, org_id, booking.booking_id)
    return ScheduleBooking(**booking_payload)


@router.get("/v1/admin/schedule/conflicts", response_model=ConflictCheckResponse)
async def check_schedule_conflicts(
    request: Request,
    starts_at: datetime,
    ends_at: datetime,
    team_id: int | None = None,
    booking_id: str | None = None,
    worker_id: int | None = None,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> ConflictCheckResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    try:
        conflicts = await ops_service.check_schedule_conflicts(
            session,
            org_id,
            starts_at=starts_at,
            ends_at=ends_at,
            team_id=team_id,
            booking_id=booking_id,
            worker_id=worker_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return ConflictCheckResponse(
        has_conflict=bool(conflicts),
        conflicts=[ConflictDetail(**conflict) for conflict in conflicts],
    )


@router.post("/v1/admin/schedule/{booking_id}/move", response_model=booking_schemas.AdminBookingListItem)
async def move_booking_slot(
    booking_id: str,
    payload: MoveBookingRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> booking_schemas.AdminBookingListItem:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    try:
        booking = await ops_service.move_booking(
            session,
            org_id,
            booking_id,
            starts_at=payload.starts_at,
            duration_minutes=payload.duration_minutes,
            team_id=payload.team_id,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-org move blocked")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    lead = getattr(booking, "lead", None)
    return booking_schemas.AdminBookingListItem(
        booking_id=booking.booking_id,
        lead_id=booking.lead_id,
        starts_at=booking.starts_at,
        duration_minutes=booking.duration_minutes,
        status=booking.status,
        lead_name=getattr(lead, "name", None),
        lead_email=getattr(lead, "email", None),
    )


@router.post("/v1/admin/schedule/block", response_model=ScheduleBlackout)
async def block_schedule_slot(
    payload: BlockSlotRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> ScheduleBlackout:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    try:
        blackout = await ops_service.block_team_slot(
            session,
            org_id,
            team_id=payload.team_id,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            reason=payload.reason,
        )
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-org block not allowed")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ScheduleBlackout.from_orm(blackout)


@router.post("/v1/admin/bookings/bulk", response_model=BulkBookingsResponse)
async def bulk_update_bookings(
    request: Request,
    payload: BulkBookingsRequest,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> BulkBookingsResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    idempotency = await require_idempotency(request, session, org_id, "bulk_update_bookings")
    if isinstance(idempotency, Response):
        return idempotency
    if idempotency.existing_response:
        return idempotency.existing_response
    adapter = _email_adapter(request)
    result = await ops_service.bulk_update_bookings(
        session,
        org_id,
        payload.booking_ids,
        team_id=payload.team_id,
        status=payload.status,
        send_reminder=payload.send_reminder,
        adapter=adapter,
    )
    response_body = BulkBookingsResponse(**result)
    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="bulk_update_bookings",
        resource_type="booking",
        resource_id=",".join(payload.booking_ids),
        before=None,
        after=response_body.model_dump(mode="json"),
    )
    await idempotency.save_response(
        session,
        status_code=status.HTTP_200_OK,
        body=response_body.model_dump(mode="json"),
    )
    await session.commit()
    return response_body


async def _load_lead(session: AsyncSession, org_id, lead_id: str | None) -> Lead | None:
    if not lead_id:
        return None
    result = await session.execute(select(Lead).where(Lead.lead_id == lead_id, Lead.org_id == org_id))
    return result.scalar_one_or_none()


async def _load_booking_with_lead(session: AsyncSession, org_id, booking_id: str | None) -> tuple[Booking | None, Lead | None]:
    stmt = select(Booking, Lead).join(Lead, Lead.lead_id == Booking.lead_id, isouter=True).where(
        Booking.org_id == org_id
    )
    if booking_id:
        stmt = stmt.where(Booking.booking_id == booking_id)
    stmt = stmt.order_by(Booking.created_at.desc()).limit(1)
    result = await session.execute(stmt)
    row = result.one_or_none()
    if not row:
        return None, None
    booking, lead = row
    return booking, lead


async def _load_invoice_with_lead(session: AsyncSession, org_id, invoice_id: str | None) -> tuple[Invoice | None, Lead | None]:
    stmt = select(Invoice, Lead).join(Lead, Lead.lead_id == Invoice.customer_id, isouter=True).where(
        Invoice.org_id == org_id
    )
    if invoice_id:
        stmt = stmt.where(Invoice.invoice_id == invoice_id)
    stmt = stmt.order_by(Invoice.created_at.desc()).limit(1)
    result = await session.execute(stmt)
    row = result.one_or_none()
    if not row:
        return None, None
    invoice, lead = row
    return invoice, lead


async def _preview_inputs(
    session: AsyncSession,
    org_id,
    lead_id: str | None,
    booking_id: str | None,
    invoice_id: str | None,
) -> tuple[Booking | None, Lead | None, Invoice | None]:
    booking, lead = await _load_booking_with_lead(session, org_id, booking_id)
    invoice, invoice_lead = await _load_invoice_with_lead(session, org_id, invoice_id)
    if lead is None:
        lead = invoice_lead or await _load_lead(session, org_id, lead_id)
    if booking and lead is None:
        lead = await _load_lead(session, org_id, booking.lead_id)
    return booking, lead, invoice


@router.get("/v1/admin/messaging/templates", response_model=list[TemplatePreviewResponse])
async def list_messaging_templates(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> list[TemplatePreviewResponse]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    templates = await ops_service.list_templates()

    booking, lead = None, None
    invoice = None
    sample_booking, lead_candidate = await _load_booking_with_lead(session, org_id, None)
    if sample_booking:
        booking, lead = sample_booking, lead_candidate
    if lead is None:
        lead = await _load_lead(session, org_id, None)
    invoice, invoice_lead = await _load_invoice_with_lead(session, org_id, None)
    if lead is None:
        lead = invoice_lead

    previews: list[TemplatePreviewResponse] = []
    for meta in templates:
        try:
            subject, body = await ops_service.render_template_preview(meta["template"], booking, lead, invoice)
        except Exception:
            subject = "Preview unavailable"
            body = "Provide a lead/booking/invoice to render this template."
        previews.append(
            TemplatePreviewResponse(
                template=meta["template"],
                version=meta["version"],
                subject=subject,
                body=body,
            )
        )
    return previews


@router.post("/v1/admin/messaging/templates/preview", response_model=TemplatePreviewResponse)
async def preview_template(
    payload: TemplatePreviewRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> TemplatePreviewResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    booking, lead, invoice = await _preview_inputs(session, org_id, payload.lead_id, payload.booking_id, payload.invoice_id)
    try:
        subject, body = await ops_service.render_template_preview(payload.template, booking, lead, invoice)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TemplatePreviewResponse(template=payload.template, version="v1", subject=subject, body=body)


@router.post("/v1/admin/messaging/events/{event_id}/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_email_event(
    event_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> dict[str, str]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    rate_limited = await enforce_org_action_rate_limit(request, org_id, "resend_email")
    if rate_limited:
        return rate_limited
    idempotency = await require_idempotency(request, session, org_id, "resend_email_event")
    if isinstance(idempotency, Response):
        return idempotency
    if idempotency.existing_response:
        return idempotency.existing_response
    adapter = _email_adapter(request)
    try:
        result = await ops_service.resend_email_event(session, adapter, org_id, event_id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email event not found")

    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="messaging_resend_email",
        resource_type="email_event",
        resource_id=str(event_id),
        before=None,
        after=result,
    )
    await idempotency.save_response(
        session,
        status_code=status.HTTP_202_ACCEPTED,
        body=result,
    )
    await session.commit()
    return result


def _job_status_response(record: JobHeartbeat) -> JobStatusResponse:
    return JobStatusResponse(
        name=record.name,
        last_heartbeat=record.last_heartbeat,
        runner_id=record.runner_id,
        last_success_at=record.last_success_at,
        last_error=record.last_error,
        last_error_at=record.last_error_at,
        consecutive_failures=record.consecutive_failures or 0,
    )


@router.get("/v1/admin/jobs/status", response_model=list[JobStatusResponse])
async def list_job_statuses(
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_viewer),
) -> list[JobStatusResponse]:
    result = await session.execute(select(JobHeartbeat).order_by(JobHeartbeat.name))
    records = result.scalars().all()
    return [_job_status_response(record) for record in records]


async def _resolve_export_payload(
    session: AsyncSession, event: ExportEvent, org_id: uuid.UUID | None
) -> dict:
    if event.payload:
        return event.payload
    if not event.lead_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="export_payload_unavailable",
        )
    stmt = select(Lead).where(Lead.lead_id == event.lead_id)
    if org_id:
        stmt = stmt.where(Lead.org_id == org_id)
    result = await session.execute(stmt)
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found for export event")
    return export_payload_from_lead(lead)


@router.get(
    "/v1/admin/export-dead-letter",
    response_model=export_schemas.ExportDeadLetterListResponse,
)
async def list_export_dead_letter(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _principal: AdminIdentity = Depends(require_viewer),
) -> export_schemas.ExportDeadLetterListResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    filters = _org_scope_filters(org_id, ExportEvent)
    count_stmt = select(func.count()).select_from(ExportEvent).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    result = await session.execute(
        select(ExportEvent)
        .where(*filters)
        .order_by(ExportEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    events = result.scalars().all()
    return export_schemas.ExportDeadLetterListResponse(
        items=[
            ExportEventResponse(
                event_id=event.event_id,
                lead_id=event.lead_id,
                mode=event.mode,
                target_url=event.target_url,
                target_url_host=event.target_url_host,
                payload=event.payload,
                attempts=event.attempts,
                last_error_code=event.last_error_code,
                created_at=event.created_at,
                replay_count=event.replay_count or 0,
                last_replayed_at=event.last_replayed_at,
                last_replayed_by=event.last_replayed_by,
            )
            for event in events
        ],
        total=total,
    )


@router.post(
    "/v1/admin/queue/dlq/replay",
    response_model=DLQBatchReplayResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_dlq_batch(
    request: Request,
    confirm: bool = Query(
        False,
        description="Explicit confirmation flag; must be true to replay DLQ items in batch.",
    ),
    limit: int = Query(10, ge=1, le=100, description="Maximum DLQ items to replay in one batch"),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> DLQBatchReplayResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    org_uuid = uuid.UUID(str(org_id)) if org_id else settings.default_org_id
    correlation_id = request.headers.get("X-Correlation-ID") or getattr(request.state, "request_id", None)
    update_log_context(correlation_id=correlation_id, org_id=str(org_uuid), replay_kind="dlq_batch")

    if not confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm_batch_replay_required")

    rate_limited = await enforce_org_action_rate_limit(request, org_uuid, "dlq_batch_replay")
    if rate_limited:
        return rate_limited

    idempotency = await require_idempotency(request, session, org_uuid, "dlq_batch_replay")
    if isinstance(idempotency, Response):
        return idempotency
    if idempotency.existing_response:
        return idempotency.existing_response

    adapter = _email_adapter(request)
    result = await run_dlq_auto_replay(
        session,
        adapter,
        org_id=org_uuid,
        export_transport=getattr(request.app.state, "export_transport", None),
        export_resolver=getattr(request.app.state, "export_resolver", None),
        max_per_org=limit,
        correlation_id=correlation_id,
    )
    response_body = DLQBatchReplayResponse(**result, correlation_id=correlation_id)
    request.state.explicit_admin_audit = True
    logger.info(
        "dlq_batch_replay",
        extra={
            "extra": {
                "org_id": str(org_uuid),
                "limit": limit,
                "correlation_id": correlation_id,
                "processed": result.get("processed", 0),
                "sent": result.get("sent", 0),
                "failed": result.get("failed", 0),
            }
        },
    )
    await audit_service.record_action(
        session,
        identity=identity,
        action="dlq_batch_replay",
        resource_type="dlq",
        resource_id=str(org_uuid),
        before=None,
        after=response_body.model_dump(mode="json"),
    )
    await idempotency.save_response(
        session,
        status_code=status.HTTP_202_ACCEPTED,
        body=response_body.model_dump(mode="json"),
    )
    await session.commit()
    return response_body


@router.post(
    "/v1/admin/export-dead-letter/{event_id}/replay",
    response_model=ExportReplayResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_export_dead_letter(
    event_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> ExportReplayResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    correlation_id = request.headers.get("X-Correlation-ID") or getattr(request.state, "request_id", None)
    update_log_context(correlation_id=correlation_id, replay_event_id=event_id, replay_kind="export_dlq")
    rate_limited = await enforce_org_action_rate_limit(request, org_id, "export_replay")
    if rate_limited:
        return rate_limited
    idempotency = await require_idempotency(request, session, org_id, "export_replay")
    if isinstance(idempotency, Response):
        return idempotency
    if idempotency.existing_response:
        return idempotency.existing_response
    org_uuid = uuid.UUID(str(org_id)) if org_id else None
    result = await session.execute(
        select(ExportEvent).where(ExportEvent.event_id == event_id, *_org_scope_filters(org_uuid, ExportEvent))
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export event not found")

    logger.info(
        "dlq_export_replay_request",
        extra={
            "extra": {
                "event_id": event_id,
                "org_id": str(org_uuid) if org_uuid else None,
                "correlation_id": correlation_id,
            }
        },
    )

    payload = await _resolve_export_payload(session, event, org_uuid)
    target_url = event.target_url or settings.export_webhook_url
    if not target_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="export_target_missing")

    export_resolver = getattr(request.app.state, "export_resolver", None)
    is_valid, reason = await validate_webhook_url(target_url, resolver=export_resolver)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid_export_target:{reason}")

    transport = getattr(request.app.state, "export_transport", None)
    success, attempts, last_error_code = await send_export_with_retry(
        target_url, payload, transport=transport
    )
    now = datetime.now(tz=timezone.utc)
    event.payload = payload
    event.target_url = target_url
    event.target_url_host = urlparse(target_url).hostname
    event.attempts = attempts
    event.last_error_code = None if success else last_error_code
    event.replay_count = (event.replay_count or 0) + 1
    event.last_replayed_at = now
    event.last_replayed_by = identity.username
    await session.commit()

    response_body = ExportReplayResponse(
        event_id=event.event_id,
        success=success,
        attempts=attempts,
        last_error_code=event.last_error_code,
        last_replayed_at=event.last_replayed_at,
        last_replayed_by=event.last_replayed_by or identity.username,
    )
    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="export_replay",
        resource_type="export_event",
        resource_id=event_id,
        before=None,
        after=response_body.model_dump(mode="json"),
    )
    await idempotency.save_response(
        session,
        status_code=status.HTTP_202_ACCEPTED,
        body=response_body.model_dump(mode="json"),
    )
    await session.commit()
    return response_body


@router.get("/v1/admin/outbox/dead-letter", response_model=List[OutboxEventResponse])
async def list_outbox_dead_letter(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    _principal: AdminIdentity = Depends(require_viewer),
) -> List[OutboxEventResponse]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    org_uuid = uuid.UUID(str(org_id)) if org_id else None
    result = await session.execute(
        select(OutboxEvent)
        .where(OutboxEvent.status == "dead", *_org_scope_filters(org_uuid, OutboxEvent))
        .order_by(OutboxEvent.created_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()
    return [
        OutboxEventResponse(
            event_id=record.event_id,
            kind=record.kind,
            status=record.status,
            attempts=record.attempts,
            last_error=record.last_error,
            next_attempt_at=record.next_attempt_at,
            created_at=record.created_at,
            dedupe_key=record.dedupe_key,
        )
        for record in records
    ]


@router.post(
    "/v1/admin/outbox/{event_id}/replay",
    response_model=OutboxReplayResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_outbox_dead_letter(
    event_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: AdminIdentity = Depends(require_admin),
) -> OutboxReplayResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    correlation_id = request.headers.get("X-Correlation-ID") or getattr(request.state, "request_id", None)
    update_log_context(correlation_id=correlation_id, replay_event_id=event_id, replay_kind="outbox_dlq")
    rate_limited = await enforce_org_action_rate_limit(request, org_id, "outbox_replay")
    if rate_limited:
        return rate_limited
    idempotency = await require_idempotency(request, session, org_id, "outbox_replay")
    if isinstance(idempotency, Response):
        return idempotency
    if idempotency.existing_response:
        return idempotency.existing_response
    org_uuid = uuid.UUID(str(org_id)) if org_id else None
    result = await session.execute(
        select(OutboxEvent).where(OutboxEvent.event_id == event_id, *_org_scope_filters(org_uuid, OutboxEvent))
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outbox event not found")
    logger.info(
        "dlq_outbox_replay_request",
        extra={
            "extra": {
                "event_id": event_id,
                "org_id": str(org_uuid) if org_uuid else None,
                "correlation_id": correlation_id,
            }
        },
    )
    await replay_outbox_event(session, event)
    response_body = OutboxReplayResponse(
        event_id=event.event_id,
        status=event.status,
        next_attempt_at=event.next_attempt_at,
        attempts=event.attempts,
        last_error=event.last_error,
    )
    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=admin,
        action="outbox_replay",
        resource_type="outbox_event",
        resource_id=str(event_id),
        before=None,
        after=response_body.model_dump(mode="json"),
    )
    await idempotency.save_response(
        session,
        status_code=status.HTTP_202_ACCEPTED,
        body=response_body.model_dump(mode="json"),
    )
    await session.commit()
    return response_body


@router.post(
    "/v1/admin/data/export", response_model=data_rights_schemas.DataExportResponse
)
async def export_client_bundle(
    payload: data_rights_schemas.DataExportRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: AdminIdentity = Depends(require_admin),
) -> data_rights_schemas.DataExportResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    try:
        bundle = await data_rights_service.export_client_data(
            session, org_id, lead_id=payload.lead_id, email=payload.email
        )
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=admin,
        action="data_export",
        resource_type="lead",
        resource_id=payload.lead_id or payload.email or "unknown",
        before=None,
        after={
            "counts": {
                "leads": len(bundle.get("leads", [])),
                "bookings": len(bundle.get("bookings", [])),
                "invoices": len(bundle.get("invoices", [])),
                "payments": len(bundle.get("payments", [])),
                "photos": len(bundle.get("photos", [])),
            }
        },
    )
    await session.commit()
    return data_rights_schemas.DataExportResponse(**bundle)


@router.post(
    "/v1/admin/data-deletion/requests",
    response_model=data_rights_schemas.DataDeletionResponse,
)
async def request_data_deletion(
    payload: data_rights_schemas.DataDeletionRequestPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    admin: AdminIdentity = Depends(require_admin),
) -> data_rights_schemas.DataDeletionResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    try:
        deletion_request, matched = await data_rights_service.request_data_deletion(
            session,
            org_id,
            lead_id=payload.lead_id,
            email=payload.email,
            reason=payload.reason,
            requested_by=admin.username,
        )
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.detail) from exc
    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=admin,
        action="data_deletion_requested",
        resource_type="lead",
        resource_id=payload.lead_id or payload.email or "unknown",
        before=None,
        after={"request_id": str(deletion_request.request_id), "matched": matched},
    )
    await session.commit()
    return data_rights_schemas.DataDeletionResponse(
        request_id=str(deletion_request.request_id),
        status=deletion_request.status,
        matched_leads=matched,
        pending_deletions=matched,
        requested_at=deletion_request.requested_at,
    )


@router.post("/v1/admin/retention/cleanup")
async def run_retention_cleanup(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
) -> dict[str, int]:
    storage = getattr(request.app.state, "storage_backend", None) or new_storage_backend()
    return await cleanup_retention(session, storage_backend=storage)


def _admin_subscription_response(model: Subscription) -> subscription_schemas.AdminSubscriptionListItem:
    return subscription_schemas.AdminSubscriptionListItem(
        subscription_id=model.subscription_id,
        client_id=model.client_id,
        status=model.status,
        status_reason=model.status_reason,
        frequency=model.frequency,
        next_run_at=model.next_run_at,
        preferred_weekday=model.preferred_weekday,
        preferred_day_of_month=model.preferred_day_of_month,
        base_service_type=model.base_service_type,
        base_price=model.base_price,
        created_at=model.created_at,
    )


async def _get_org_subscription(
    session: AsyncSession, subscription_id: str, org_id: uuid.UUID
) -> Subscription | None:
    subscription = await session.get(Subscription, subscription_id)
    if not subscription or subscription.org_id != org_id:
        return None
    return subscription


@router.get(
    "/v1/admin/subscriptions",
    response_model=list[subscription_schemas.AdminSubscriptionListItem],
)
async def list_subscriptions_admin(
    request: Request,
    identity: AdminIdentity = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[subscription_schemas.AdminSubscriptionListItem]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    stmt = (
        select(Subscription)
        .where(Subscription.org_id == org_id)
        .order_by(Subscription.created_at.desc())
    )
    result = await session.execute(stmt)
    subscriptions = result.scalars().all()
    return [_admin_subscription_response(sub) for sub in subscriptions]


@router.patch(
    "/v1/admin/subscriptions/{subscription_id}",
    response_model=subscription_schemas.AdminSubscriptionListItem,
)
async def update_subscription_admin(
    subscription_id: str,
    payload: subscription_schemas.AdminSubscriptionUpdateRequest,
    request: Request,
    _identity: AdminIdentity = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> subscription_schemas.AdminSubscriptionListItem:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    subscription = await _get_org_subscription(session, subscription_id, org_id)
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    try:
        await subscription_service.update_subscription(session, subscription, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(subscription)
    return _admin_subscription_response(subscription)


@router.get(
    "/v1/admin/feature-flags", response_model=config_schemas.FeatureFlagResponse
)
async def feature_flags(
    _identity: AdminIdentity = Depends(require_admin),
) -> config_schemas.FeatureFlagResponse:
    flags = [
        config_schemas.FeatureFlag(
            key="exports",
            enabled=settings.export_mode != "off",
            description="Outbound exports and webhooks",
            rollout=settings.export_mode,
        ),
        config_schemas.FeatureFlag(
            key="deposits",
            enabled=settings.deposits_enabled,
            description="Deposit collection enabled for bookings",
        ),
        config_schemas.FeatureFlag(
            key="strict_policy_mode",
            enabled=getattr(settings, "strict_policy_mode", False),
            description="Enforces strict client/config policies",
        ),
    ]
    return config_schemas.FeatureFlagResponse(flags=flags)


@router.get(
    "/v1/admin/config", response_model=config_schemas.ConfigViewerResponse
)
async def config_viewer(
    _identity: AdminIdentity = Depends(require_permission_keys("settings.manage")),
) -> config_schemas.ConfigViewerResponse:
    entries = _config_entries_from_settings()
    return config_schemas.ConfigViewerResponse(entries=entries)


@router.post(
    "/v1/admin/subscriptions/run",
    response_model=subscription_schemas.SubscriptionRunResult,
)
async def run_subscriptions(
    http_request: Request,
    identity: AdminIdentity = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> subscription_schemas.SubscriptionRunResult:
    adapter = _email_adapter(http_request)
    org_id = getattr(http_request.state, "org_id", None) or entitlements.resolve_org_id(http_request)
    result = await subscription_service.generate_due_orders(
        session, email_adapter=adapter, org_id=org_id
    )
    await session.commit()
    return subscription_schemas.SubscriptionRunResult(
        processed=result.processed, created_orders=result.created_orders
    )


def _normalize_range(
    start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    now = datetime.now(tz=timezone.utc)
    normalized_start = start or datetime.fromtimestamp(0, tz=timezone.utc)
    normalized_end = end or now
    if normalized_start.tzinfo is None:
        normalized_start = normalized_start.replace(tzinfo=timezone.utc)
    else:
        normalized_start = normalized_start.astimezone(timezone.utc)
    if normalized_end.tzinfo is None:
        normalized_end = normalized_end.replace(tzinfo=timezone.utc)
    else:
        normalized_end = normalized_end.astimezone(timezone.utc)
    if normalized_end < normalized_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date range")
    return normalized_start, normalized_end


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _org_scope_condition(entity: object, org_id: uuid.UUID, allow_null: bool = False):
    """Return an org_id filter for a given ORM entity.

    Ensures every query touching multiple tables consistently constrains each table to the
    caller's organization. `allow_null=True` is reserved for joins where the condition is
    applied in the ON clause rather than filtering out parent rows.
    """

    column = getattr(entity, "org_id", None)
    if column is None:
        raise RuntimeError(f"Entity {entity} is missing org_id for scoping")
    if allow_null:
        return column == org_id
    return column == org_id


def _org_scope_filters(org_id: uuid.UUID, *entities: object) -> tuple:
    seen = set()
    filters = []
    for entity in entities:
        if entity in seen:
            continue
        seen.add(entity)
        filters.append(_org_scope_condition(entity, org_id))
    return tuple(filters)


SECRET_KEYWORDS = ("secret", "password", "token", "key", "credential")
CONFIG_WHITELIST = (
    "app_env",
    "strict_cors",
    "strict_policy_mode",
    "export_mode",
    "deposits_enabled",
    "order_storage_backend",
    "photo_download_redirect_status",
    "metrics_enabled",
    "metrics_token",
    "job_heartbeat_required",
    "auth_secret_key",
    "client_portal_secret",
    "worker_portal_secret",
    "photo_token_secret",
    "order_photo_signing_secret",
    "stripe_secret_key",
    "stripe_webhook_secret",
    "sendgrid_api_key",
    "smtp_password",
    "cf_images_api_token",
    "cf_images_signing_key",
)


def _redact_config_value(key: str, value: object | None) -> tuple[object | None, bool]:
    lowered = key.lower()
    redacted = any(token in lowered for token in SECRET_KEYWORDS)
    if redacted:
        return ("<redacted>" if value else None), True
    return value, False


def _config_entries_from_settings() -> list[config_schemas.ConfigEntry]:
    raw = settings.model_dump()
    entries: list[config_schemas.ConfigEntry] = []
    for key in CONFIG_WHITELIST:
        value = raw.get(key)
        redacted_value, is_redacted = _redact_config_value(key, value)
        entries.append(
            config_schemas.ConfigEntry(
                key=key, value=redacted_value, redacted=is_redacted, source="settings"
            )
        )
    return entries


def _normalize_date_range(start: date | None, end: date | None) -> tuple[date, date]:
    range_start = start or date(1970, 1, 1)
    range_end = end or date.today()
    if range_end < range_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date range")
    return range_start, range_end


def _csv_line(key: str, value: object) -> str:
    return f"{ops_service.safe_csv_value(key)},{ops_service.safe_csv_value(value)}"


def _sanitize_row(values: Iterable[object]) -> list[str]:
    return [ops_service.safe_csv_value(value) for value in values]


@router.get("/v1/admin/metrics", response_model=analytics_schemas.AdminMetricsResponse)
async def get_admin_metrics(
    request: Request,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    format: str | None = Query(default=None, pattern="^(json|csv)$"),
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
):
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_range(from_ts, to_ts)
    if not settings.metrics_enabled:
        return analytics_schemas.AdminMetricsResponse(
            range_start=start,
            range_end=end,
            conversions=analytics_schemas.ConversionMetrics(
                lead_created=0,
                booking_created=0,
                booking_confirmed=0,
                job_completed=0,
            ),
            revenue=analytics_schemas.RevenueMetrics(average_estimated_revenue_cents=None),
            accuracy=analytics_schemas.DurationAccuracy(
                sample_size=0,
                average_delta_minutes=None,
                average_actual_duration_minutes=None,
                average_estimated_duration_minutes=None,
            ),
            financial=analytics_schemas.FinancialKpis(
                total_revenue_cents=0,
                revenue_per_day_cents=0.0,
                margin_cents=0,
                average_order_value_cents=None,
            ),
            operational=analytics_schemas.OperationalKpis(
                crew_utilization=None,
                cancellation_rate=0.0,
                retention_30_day=0.0,
                retention_60_day=0.0,
                retention_90_day=0.0,
            ),
        )
    conversions = await conversion_counts(session, start, end, org_id=org_id)
    avg_revenue = await average_revenue_cents(session, start, end, org_id=org_id)
    avg_estimated, avg_actual, avg_delta, sample_size = await duration_accuracy(
        session, start, end, org_id=org_id
    )
    kpis = await kpi_aggregates(session, start, end, org_id=org_id)

    response_body = analytics_schemas.AdminMetricsResponse(
        range_start=start,
        range_end=end,
        conversions=analytics_schemas.ConversionMetrics(
            lead_created=conversions.get(EventType.lead_created, 0),
            booking_created=conversions.get(EventType.booking_created, 0),
            booking_confirmed=conversions.get(EventType.booking_confirmed, 0),
            job_completed=conversions.get(EventType.job_completed, 0),
        ),
        revenue=analytics_schemas.RevenueMetrics(
            average_estimated_revenue_cents=avg_revenue,
        ),
        accuracy=analytics_schemas.DurationAccuracy(
            sample_size=sample_size,
            average_estimated_duration_minutes=avg_estimated,
            average_actual_duration_minutes=avg_actual,
            average_delta_minutes=avg_delta,
        ),
        financial=analytics_schemas.FinancialKpis(**kpis["financial"]),
        operational=analytics_schemas.OperationalKpis(**kpis["operational"]),
    )

    if format == "csv":
        lines = [
            _csv_line("range_start", response_body.range_start.isoformat()),
            _csv_line("range_end", response_body.range_end.isoformat()),
            _csv_line("lead_created", response_body.conversions.lead_created),
            _csv_line("booking_created", response_body.conversions.booking_created),
            _csv_line("booking_confirmed", response_body.conversions.booking_confirmed),
            _csv_line("job_completed", response_body.conversions.job_completed),
            _csv_line("average_estimated_revenue_cents", response_body.revenue.average_estimated_revenue_cents),
            _csv_line("average_estimated_duration_minutes", response_body.accuracy.average_estimated_duration_minutes),
            _csv_line("average_actual_duration_minutes", response_body.accuracy.average_actual_duration_minutes),
            _csv_line("average_delta_minutes", response_body.accuracy.average_delta_minutes),
            _csv_line("accuracy_sample_size", response_body.accuracy.sample_size),
            _csv_line("total_revenue_cents", response_body.financial.total_revenue_cents),
            _csv_line("revenue_per_day_cents", response_body.financial.revenue_per_day_cents),
            _csv_line("margin_cents", response_body.financial.margin_cents),
            _csv_line("average_order_value_cents", response_body.financial.average_order_value_cents),
            _csv_line("crew_utilization", response_body.operational.crew_utilization),
            _csv_line("cancellation_rate", response_body.operational.cancellation_rate),
            _csv_line("retention_30_day", response_body.operational.retention_30_day),
            _csv_line("retention_60_day", response_body.operational.retention_60_day),
            _csv_line("retention_90_day", response_body.operational.retention_90_day),
        ]
        return Response("\n".join(lines), media_type="text/csv")

    return response_body


@router.get(
    "/v1/admin/analytics/funnel",
    response_model=analytics_schemas.FunnelAnalyticsResponse,
)
async def get_funnel_analytics(
    request: Request,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_finance),
) -> analytics_schemas.FunnelAnalyticsResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_range(from_ts, to_ts)
    counts = await funnel_summary(session, start, end, org_id=org_id)
    return analytics_schemas.FunnelAnalyticsResponse(
        range_start=start,
        range_end=end,
        counts=analytics_schemas.FunnelCounts(**counts),
        conversion_rates=analytics_schemas.FunnelConversionRates(
            lead_to_booking=_rate(counts["bookings"], counts["leads"]),
            booking_to_completed=_rate(counts["completed"], counts["bookings"]),
            completed_to_paid=_rate(counts["paid"], counts["completed"]),
            lead_to_paid=_rate(counts["paid"], counts["leads"]),
        ),
    )


@router.get(
    "/v1/admin/analytics/nps", response_model=analytics_schemas.NpsAnalyticsResponse
)
async def get_nps_analytics(
    request: Request,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_finance),
) -> analytics_schemas.NpsAnalyticsResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_range(from_ts, to_ts)
    total, avg_score, promoters, passives, detractors = await nps_distribution(
        session, start, end, org_id=org_id
    )
    trends = await nps_trends(session, start, end, org_id=org_id)

    def _trend_points(rows: list[tuple[datetime, float | None, int]]):
        return [
            analytics_schemas.NpsTrendPoint(
                period_start=period,
                average_score=score,
                response_count=count,
            )
            for period, score, count in rows
        ]

    distribution = analytics_schemas.NpsDistribution(
        total_responses=total,
        average_score=avg_score,
        promoters=promoters,
        passives=passives,
        detractors=detractors,
        promoter_rate=_rate(promoters, total),
        passive_rate=_rate(passives, total),
        detractor_rate=_rate(detractors, total),
    )

    return analytics_schemas.NpsAnalyticsResponse(
        range_start=start,
        range_end=end,
        distribution=distribution,
        trends=analytics_schemas.NpsTrends(
            weekly=_trend_points(trends.get("weekly", [])),
            monthly=_trend_points(trends.get("monthly", [])),
        ),
    )


@router.get(
    "/v1/admin/analytics/cohorts",
    response_model=analytics_schemas.CohortAnalyticsResponse,
)
async def get_cohort_analytics(
    request: Request,
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_finance),
) -> analytics_schemas.CohortAnalyticsResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_range(from_ts, to_ts)
    cohorts = await cohort_repeat_rates(session, start, end, org_id=org_id)
    cohort_payload = [
        analytics_schemas.CohortBreakdown(
            cohort_month=cohort_month,
            customers=customers,
            repeat_customers=repeat,
            repeat_rate=_rate(repeat, customers),
        )
        for cohort_month, customers, repeat in cohorts
    ]
    return analytics_schemas.CohortAnalyticsResponse(
        range_start=start, range_end=end, cohorts=cohort_payload
    )


@router.get("/v1/admin/reports/gst", response_model=invoice_schemas.GstReportResponse)
async def admin_gst_report(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_finance),
) -> invoice_schemas.GstReportResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_date_range(from_date, to_date)
    stmt = (
        select(
            func.count(Invoice.invoice_id),
            func.coalesce(func.sum(Invoice.taxable_subtotal_cents), 0),
            func.coalesce(func.sum(Invoice.tax_cents), 0),
        )
        .where(
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
            Invoice.status.notin_(
                [invoice_statuses.INVOICE_STATUS_VOID, invoice_statuses.INVOICE_STATUS_DRAFT]
            ),
            *_org_scope_filters(org_id, Invoice),
        )
        .select_from(Invoice)
    )
    result = await session.execute(stmt)
    invoice_count, subtotal_cents, tax_cents = result.one()
    return invoice_schemas.GstReportResponse(
        range_start=start,
        range_end=end,
        invoice_count=int(invoice_count or 0),
        taxable_subtotal_cents=int(subtotal_cents or 0),
        tax_cents=int(tax_cents or 0),
    )


@router.get(
    "/v1/admin/finance/reconcile/invoices",
    response_model=invoice_schemas.InvoiceReconcileListResponse,
)
async def list_invoice_reconcile_items(
    request: Request,
    status: Literal["mismatch", "all"] = Query("mismatch"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
) -> invoice_schemas.InvoiceReconcileListResponse:
    org_id = entitlements.resolve_org_id(request)
    cases, total = await invoice_service.list_invoice_reconcile_items(
        session,
        org_id,
        include_all=status == "all",
        limit=limit,
        offset=offset,
    )
    return invoice_schemas.InvoiceReconcileListResponse(items=cases, total=total)


@router.post(
    "/v1/admin/finance/invoices/{invoice_id}/reconcile",
    response_model=invoice_schemas.InvoiceReconcilePlan | invoice_schemas.InvoiceReconcileResponse,
)
async def reconcile_invoice(
    request: Request,
    invoice_id: str,
    dry_run: bool = Query(default=False, alias="dry_run"),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_permission_keys("payments.record")),
) -> invoice_schemas.InvoiceReconcilePlan | invoice_schemas.InvoiceReconcileResponse:
    org_id = entitlements.resolve_org_id(request)
    invoice, before, after = await invoice_service.reconcile_invoice(
        session, org_id, invoice_id, dry_run=dry_run
    )
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    if dry_run:
        return invoice_schemas.InvoiceReconcilePlan(
            dry_run=True,
            before=invoice_schemas.InvoiceReconcileResponse(**before),
            after=invoice_schemas.InvoiceReconcileResponse(**after),
            planned_operations=invoice_service.describe_reconcile_operations(before, after),
        )

    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        org_id=org_id,
        action="finance_reconcile",
        resource_type="invoice",
        resource_id=invoice.invoice_id,
        before=before,
        after=after,
    )
    await session.commit()
    return invoice_schemas.InvoiceReconcileResponse(**after)


@router.get(
    "/v1/admin/finance/reconcile/stripe-events",
    response_model=invoice_schemas.StripeEventListResponse,
)
async def list_stripe_events(
    request: Request,
    invoice_id: str | None = Query(default=None),
    booking_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_permission_keys("finance.view")),
) -> invoice_schemas.StripeEventListResponse:
    org_id = entitlements.resolve_org_id(request)
    items, total = await invoice_service.list_stripe_events(
        session,
        org_id,
        invoice_id=invoice_id,
        booking_id=booking_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return invoice_schemas.StripeEventListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/v1/admin/exports/accounting.csv")
async def export_accounting(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    status: list[str] | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_finance),
) -> Response:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_date_range(from_date, to_date)
    status_filter: set[str] | None = None
    if status:
        try:
            status_filter = {invoice_statuses.normalize_status(value) for value in status}
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_status") from exc

    rows = await invoice_service.accounting_export_rows(
        session, org_id, start=start, end=end, statuses_filter=status_filter
    )
    csv_content = invoice_service.build_accounting_export_csv(rows)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=accounting.csv"},
    )


@router.get("/v1/admin/exports/sales-ledger.csv")
async def export_sales_ledger(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_finance),
) -> Response:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_date_range(from_date, to_date)
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.payments))
        .where(
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
            Invoice.status.notin_(
                [invoice_statuses.INVOICE_STATUS_VOID, invoice_statuses.INVOICE_STATUS_DRAFT]
            ),
            *_org_scope_filters(org_id, Invoice),
        )
        .order_by(Invoice.issue_date.asc(), Invoice.invoice_number.asc())
    )
    result = await session.execute(stmt)
    invoices = result.scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        _sanitize_row(
            [
                "invoice_number",
                "issue_date",
                "due_date",
                "status",
                "currency",
                "subtotal_cents",
                "tax_cents",
                "total_cents",
                "paid_cents",
                "balance_due_cents",
                "customer_id",
                "booking_id",
            ]
        )
    )
    for invoice in invoices:
        paid_cents = sum(
            payment.amount_cents
            for payment in invoice.payments
            if payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED
        )
        balance_due_cents = max(invoice.total_cents - paid_cents, 0)
        writer.writerow(
            _sanitize_row(
                [
                    invoice.invoice_number,
                    invoice.issue_date.isoformat(),
                    invoice.due_date.isoformat() if invoice.due_date else "",
                    invoice.status,
                    invoice.currency,
                    invoice.subtotal_cents,
                    invoice.tax_cents,
                    invoice.total_cents,
                    paid_cents,
                    balance_due_cents,
                    invoice.customer_id or "",
                    invoice.order_id or "",
                ]
            )
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sales-ledger.csv"},
    )


@router.get("/v1/admin/exports/payments.csv")
async def export_payments_ledger(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_finance),
) -> Response:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_date_range(from_date, to_date)
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
    timestamp_expr = func.coalesce(Payment.received_at, Payment.created_at).label("ts")
    stmt = (
        select(Payment, Invoice.invoice_number, Invoice.order_id, timestamp_expr)
        .join(Invoice, Payment.invoice_id == Invoice.invoice_id, isouter=True)
        .where(
            timestamp_expr >= start_dt,
            timestamp_expr <= end_dt,
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            Payment.invoice_id.isnot(None),
            *_org_scope_filters(org_id, Payment, Invoice),
        )
        .order_by(timestamp_expr.asc(), Payment.created_at.asc(), Payment.payment_id.asc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        _sanitize_row(
            [
                "payment_id",
                "invoice_number",
                "booking_id",
                "provider",
                "method",
                "status",
                "amount_cents",
                "currency",
                "received_at",
                "created_at",
            ]
        )
    )

    for payment, invoice_number, invoice_order_id, _payment_ts in rows:
        writer.writerow(
            _sanitize_row(
                [
                    payment.payment_id,
                    invoice_number or "",
                    payment.booking_id or invoice_order_id or "",
                    payment.provider,
                    payment.method,
                    payment.status,
                    payment.amount_cents,
                    payment.currency,
                    payment.received_at.isoformat() if payment.received_at else "",
                    payment.created_at.isoformat(),
                ]
            )
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments.csv"},
    )


@router.get("/v1/admin/exports/deposits.csv")
async def export_deposits_ledger(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_finance),
) -> Response:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_date_range(from_date, to_date)
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
    timestamp_expr = func.coalesce(Payment.received_at, Payment.created_at).label("ts")
    stmt = (
        select(Payment, timestamp_expr)
        .where(
            timestamp_expr >= start_dt,
            timestamp_expr <= end_dt,
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            Payment.invoice_id.is_(None),
            Payment.booking_id.isnot(None),
            *_org_scope_filters(org_id, Payment),
        )
        .order_by(timestamp_expr.asc(), Payment.created_at.asc(), Payment.payment_id.asc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        _sanitize_row(
            [
                "payment_id",
                "booking_id",
                "provider",
                "method",
                "amount_cents",
                "currency",
                "received_at",
                "created_at",
            ]
        )
    )

    for payment, _payment_ts in rows:
        writer.writerow(
            _sanitize_row(
                [
                    payment.payment_id,
                    payment.booking_id or "",
                    payment.provider,
                    payment.method,
                    payment.amount_cents,
                    payment.currency,
                    payment.received_at.isoformat() if payment.received_at else "",
                    payment.created_at.isoformat(),
                ]
            )
        )

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=deposits.csv"},
    )


def _resolve_worker_rate(worker: Worker | None) -> int:
    if worker and worker.hourly_rate_cents is not None:
        return worker.hourly_rate_cents
    return settings.default_worker_hourly_rate_cents


def _actual_minutes(booking: Booking) -> int:
    if booking.actual_seconds is not None:
        return int(math.ceil(booking.actual_seconds / 60))
    if booking.actual_duration_minutes is not None:
        return booking.actual_duration_minutes
    return booking.duration_minutes


@router.get("/v1/admin/reports/pnl", response_model=invoice_schemas.PnlReportResponse)
async def admin_pnl_report(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_finance),
) -> invoice_schemas.PnlReportResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    start, end = _normalize_date_range(from_date, to_date)
    stmt = (
        select(Invoice, Booking, Worker)
        .join(Booking, Invoice.order_id == Booking.booking_id)
        .join(
            Worker,
            and_(Booking.assigned_worker_id == Worker.worker_id, Worker.org_id == org_id),
            isouter=True,
        )
        .where(
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
            Invoice.status.notin_(
                [invoice_statuses.INVOICE_STATUS_VOID, invoice_statuses.INVOICE_STATUS_DRAFT]
            ),
            Booking.status.in_(["DONE", "CONFIRMED"]),
            *_org_scope_filters(org_id, Invoice, Booking),
        )
        .order_by(Invoice.issue_date.asc(), Invoice.invoice_number.asc())
    )
    result = await session.execute(stmt)
    rows: list[invoice_schemas.PnlRow] = []
    for invoice, booking, worker in result.all():
        worker_rate_cents = _resolve_worker_rate(worker)
        minutes = _actual_minutes(booking)
        labour_cents = int(
            (Decimal(worker_rate_cents) * Decimal(minutes) / Decimal(60))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        payment_fees_cents = 0
        revenue_cents = invoice.subtotal_cents
        margin_cents = revenue_cents - labour_cents - payment_fees_cents
        margin_pct = round((margin_cents / revenue_cents) * 100, 4) if revenue_cents else None

        rows.append(
            invoice_schemas.PnlRow(
                booking_id=booking.booking_id,
                invoice_number=invoice.invoice_number,
                revenue_cents=revenue_cents,
                labour_cents=labour_cents,
                payment_fees_cents=payment_fees_cents,
                margin_cents=margin_cents,
                margin_pct=margin_pct,
                worker_rate_cents=worker_rate_cents,
                actual_minutes=minutes,
            )
        )

    return invoice_schemas.PnlReportResponse(range_start=start, range_end=end, rows=rows)


@router.post("/v1/admin/pricing/reload", status_code=status.HTTP_202_ACCEPTED)
async def reload_pricing(
    _admin: AdminIdentity = Depends(require_permission_keys("pricing.manage")),
) -> dict[str, str]:
    load_pricing_config(settings.pricing_config_path)
    return {"status": "reloaded"}


@router.get("/v1/admin/bookings", response_model=list[booking_schemas.AdminBookingListItem])
async def list_bookings(
    request: Request,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    status_filter: str | None = Query(default=None, alias="status"),
    include_archived: bool = Query(default=False, alias="include_archived"),
    include_cancelled: bool = Query(default=False, alias="include_cancelled"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_viewer),
):
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    today = datetime.now(tz=booking_service.LOCAL_TZ).date()
    start_date = from_date or today
    end_date = to_date or start_date
    start_dt = datetime.combine(start_date, time.min, tzinfo=booking_service.LOCAL_TZ).astimezone(timezone.utc)
    end_dt = datetime.combine(end_date, time.max, tzinfo=booking_service.LOCAL_TZ).astimezone(timezone.utc)
    if end_dt < start_dt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date range")

    stmt = select(Booking, Lead).outerjoin(
        Lead, and_(Lead.lead_id == Booking.lead_id, Lead.org_id == org_id)
    ).where(
        Booking.starts_at >= start_dt,
        Booking.starts_at <= end_dt,
        Booking.org_id == org_id,
    )
    stmt = _apply_booking_active_filters(
        stmt, include_archived=include_archived, include_cancelled=include_cancelled
    )
    if status_filter:
        stmt = stmt.where(Booking.status == status_filter.upper())
    stmt = stmt.order_by(Booking.starts_at.asc())
    result = await session.execute(stmt)
    return [
        booking_schemas.AdminBookingListItem(
            booking_id=booking.booking_id,
            lead_id=booking.lead_id,
            starts_at=booking.starts_at,
            duration_minutes=booking.duration_minutes,
            status=booking.status,
            lead_name=lead.name if lead else None,
            lead_email=lead.email if lead else None,
        )
        for booking, lead in result.all()
    ]


@router.patch("/v1/admin/bookings/{booking_id}", response_model=ScheduleBooking)
async def update_booking(
    booking_id: str,
    payload: booking_schemas.AdminBookingUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_any_permission_keys("bookings.assign", "bookings.edit")),
) -> ScheduleBooking:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    booking_result = await session.execute(
        select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    if booking.status in {"DONE", "CANCELLED"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking is no longer active")

    fields_set = payload.model_fields_set
    if not fields_set:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No updates provided")

    new_starts_at = payload.starts_at if "starts_at" in fields_set and payload.starts_at else booking.starts_at
    if new_starts_at is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="starts_at is required")

    duration_minutes = booking.duration_minutes
    if "ends_at" in fields_set:
        if payload.ends_at is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ends_at is required")
        duration_minutes = int((payload.ends_at - new_starts_at).total_seconds() // 60)
        if duration_minutes <= 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid time range")

    target_team_id = payload.team_id if "team_id" in fields_set and payload.team_id is not None else booking.team_id
    team = await session.get(Team, target_team_id)
    if team is None or team.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    worker_id_provided = "worker_id" in fields_set
    target_worker_id = booking.assigned_worker_id
    if worker_id_provided:
        target_worker_id = payload.worker_id
        if target_worker_id is not None:
            worker = await session.get(Worker, target_worker_id)
            if worker is None or worker.org_id != org_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
            if worker.team_id != target_team_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Worker must be on the same team")

    if not worker_id_provided and target_team_id != booking.team_id and booking.assigned_worker_id is not None:
        target_worker_id = None
        worker_id_provided = True

    ends_at = new_starts_at + timedelta(minutes=duration_minutes)
    try:
        conflicts = await ops_service.check_schedule_conflicts(
            session,
            org_id,
            starts_at=new_starts_at,
            ends_at=ends_at,
            team_id=target_team_id,
            booking_id=booking.booking_id,
            worker_id=target_worker_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if conflicts:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": {
                    "message": "conflict_with_existing_booking",
                    "conflicts": jsonable_encoder(conflicts),
                }
            },
        )

    before_state = {
        "starts_at": booking.starts_at.isoformat() if booking.starts_at else None,
        "duration_minutes": booking.duration_minutes,
        "team_id": booking.team_id,
        "assigned_worker_id": booking.assigned_worker_id,
    }

    booking.starts_at = new_starts_at
    booking.duration_minutes = duration_minutes
    booking.team_id = target_team_id
    if worker_id_provided:
        booking.assigned_worker_id = target_worker_id
        worker_ids = [target_worker_id] if target_worker_id is not None else []
        await _sync_booking_workers(session, booking.booking_id, worker_ids, replace=True)

    request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="booking_update",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before_state,
        after={
            "starts_at": booking.starts_at.isoformat() if booking.starts_at else None,
            "duration_minutes": booking.duration_minutes,
            "team_id": booking.team_id,
            "assigned_worker_id": booking.assigned_worker_id,
        },
    )
    await session.commit()

    schedule_payload = await ops_service.fetch_schedule_booking(session, org_id, booking.booking_id)
    return ScheduleBooking(**schedule_payload)


@router.post("/v1/admin/bookings/{booking_id}/confirm", response_model=booking_schemas.BookingResponse)
async def confirm_booking(
    http_request: Request,
    booking_id: str,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
):
    org_id = getattr(http_request.state, "org_id", None) or entitlements.resolve_org_id(http_request)
    booking_result = await session.execute(
        select(Booking)
        .where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        .options(selectinload(Booking.worker_assignments))
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    before_state = booking_schemas.BookingResponse(
        booking_id=booking.booking_id,
        status=booking.status,
        starts_at=booking.starts_at,
        duration_minutes=booking.duration_minutes,
        actual_duration_minutes=booking.actual_duration_minutes,
        deposit_required=booking.deposit_required,
        deposit_cents=booking.deposit_cents,
        deposit_policy=booking.deposit_policy,
        deposit_status=booking.deposit_status,
        checkout_url=None,
        risk_score=booking.risk_score,
        risk_band=booking.risk_band,
        risk_reasons=booking.risk_reasons,
        cancellation_exception=booking.cancellation_exception,
        cancellation_exception_note=booking.cancellation_exception_note,
    ).model_dump(mode="json")

    try:
        booking_service.assert_valid_booking_transition(booking.status, "CONFIRMED")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if booking.deposit_required and booking.deposit_status != "paid":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Deposit required before confirmation"
        )

    lead = await session.get(Lead, booking.lead_id) if booking.lead_id else None
    if booking.status != "CONFIRMED":
        booking.status = "CONFIRMED"
        try:
            await log_event(
                session,
                event_type=EventType.booking_confirmed,
                booking=booking,
                lead=lead,
                estimated_revenue_cents=estimated_revenue_from_lead(lead),
                estimated_duration_minutes=estimated_duration_from_booking(booking),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "analytics_log_failed",
                extra={
                    "extra": {
                        "event_type": "booking_confirmed",
                        "booking_id": booking.booking_id,
                        "lead_id": booking.lead_id,
                        "reason": type(exc).__name__,
                    }
                },
            )
    if lead:
        try:
            await grant_referral_credit(session, lead)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "referral_credit_failed",
                extra={
                    "extra": {
                        "booking_id": booking.booking_id,
                        "lead_id": lead.lead_id,
                        "reason": type(exc).__name__,
                    }
                },
            )
    response_body = booking_schemas.BookingResponse(
        booking_id=booking.booking_id,
        status=booking.status,
        starts_at=booking.starts_at,
        duration_minutes=booking.duration_minutes,
        actual_duration_minutes=booking.actual_duration_minutes,
        deposit_required=booking.deposit_required,
        deposit_cents=booking.deposit_cents,
        deposit_policy=booking.deposit_policy,
        deposit_status=booking.deposit_status,
        checkout_url=None,
        risk_score=booking.risk_score,
        risk_band=booking.risk_band,
        risk_reasons=booking.risk_reasons,
        cancellation_exception=booking.cancellation_exception,
        cancellation_exception_note=booking.cancellation_exception_note,
    )
    http_request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="booking_confirm",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before_state,
        after=response_body.model_dump(mode="json"),
    )
    await session.commit()
    return response_body


@router.get("/v1/admin/observability", response_class=HTMLResponse)
async def admin_observability(
    request: Request,
    filters: list[str] = Query(default=[]),
    session: AsyncSession = Depends(get_db_session),
    store: BotStore = Depends(get_bot_store),
    _identity: AdminIdentity = Depends(require_viewer),
) -> HTMLResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    lang = resolve_lang(request)
    active_filters = {value.lower() for value in filters if value}
    lead_stmt = (
        select(Lead)
        .options(selectinload(Lead.bookings))
        .where(Lead.org_id == org_id)
        .order_by(Lead.created_at.desc())
        .limit(200)
    )
    leads = (await session.execute(lead_stmt)).scalars().all()
    cases = sorted(await store.list_cases(), key=lambda c: getattr(c, "created_at", 0), reverse=True)
    conversations = sorted(
        await store.list_conversations(), key=lambda c: getattr(c, "updated_at", 0), reverse=True
    )
    message_lookup: dict[str, list[object]] = {}
    for conversation in conversations:
        message_lookup[conversation.conversation_id] = await store.list_messages(conversation.conversation_id)

    content = "".join(
        [
            _render_filters(active_filters, lang),
            _render_section(tr(lang, "admin.sections.cases"), _render_cases(cases, active_filters, lang)),
            _render_section(tr(lang, "admin.sections.leads"), _render_leads(leads, active_filters, lang)),
            _render_section(
                tr(lang, "admin.sections.dialogs"),
                _render_dialogs(conversations, message_lookup, active_filters, lang),
            ),
        ]
    )
    return HTMLResponse(
        _wrap_page(
            request,
            content,
            title=tr(lang, "admin.observability.title"),
            active="observability",
            page_lang=lang,
        )
    )


@router.get("/v1/admin/observability/cases/{case_id}", response_class=HTMLResponse)
async def admin_case_detail(
    case_id: str,
    request: Request,
    store: BotStore = Depends(get_bot_store),
    _identity: AdminIdentity = Depends(require_viewer),
) -> HTMLResponse:
    lang = resolve_lang(request)
    cases = await store.list_cases()
    case = next((item for item in cases if getattr(item, "case_id", None) == case_id), None)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    payload = getattr(case, "payload", {}) or {}
    contact_fields = {}
    conversation_data = payload.get("conversation") or {}
    state_data = conversation_data.get("state") or {}
    if isinstance(state_data, dict):
        contact_fields = state_data.get("filled_fields") or {}
        if not isinstance(contact_fields, dict):
            contact_fields = {}
    contact_data = contact_fields.get("contact") if isinstance(contact_fields, dict) else None
    contact_data = contact_data if isinstance(contact_data, dict) else {}
    phone = contact_fields.get("phone") or contact_data.get("phone")
    email = contact_fields.get("email") or contact_data.get("email")

    transcript = payload.get("messages") or []
    if not transcript and getattr(case, "source_conversation_id", None):
        messages = await store.list_messages(case.source_conversation_id)
        transcript = [
            {
                "role": msg.role,
                "text": msg.text,
                "ts": msg.created_at,
            }
            for msg in messages
        ]

    transcript_html = "".join(
        """
        <div class="card">
          <div class="card-row">
            <div class="title">{role}</div>
            <div class="muted">{ts}</div>
          </div>
          <div>{text}</div>
        </div>
        """.format(
            role=html.escape(str(message.get("role", "") if isinstance(message, dict) else getattr(message, "role", ""))),
            ts=_format_ts(
                message.get("ts") if isinstance(message, dict) else getattr(message, "ts", getattr(message, "created_at", None))
            ),
            text=html.escape(
                str(message.get("text", "")) if isinstance(message, dict) else str(getattr(message, "text", ""))
            ),
        )
        for message in transcript
    )
    if not transcript_html:
        transcript_html = _render_empty(tr(lang, "admin.empty.transcript"))

    quick_actions: list[str] = []
    contact_quick_actions = {
        "phone": phone,
        "email": email,
    }
    for field, value in contact_quick_actions.items():
        if value:
            escaped_value = html.escape(str(value), quote=True)
            contact_label = tr(lang, f"admin.contact.{field}")
            if contact_label == f"admin.contact.{field}":
                contact_label = field.title()
            quick_actions.append(
                """
                <button class="btn" data-copy="{value}" onclick="navigator.clipboard.writeText(this.dataset.copy)">{copy_label} {label}</button>
                """.format(
                    value=escaped_value,
                    copy_label=html.escape(tr(lang, "admin.buttons.copy")),
                    label=html.escape(contact_label),
                )
            )
    quick_actions.append(
        f"<button class=\"btn\" onclick=\"alert('Mark contacted placeholder')\">{html.escape(tr(lang, 'admin.buttons.mark_contacted'))}</button>"
    )

    summary_block = """
        <div class="card">
          <div class="card-row">
            <div>
              <div class="title">{summary}</div>
              <div class="muted">{reason_label} {reason}</div>
            </div>
            <div class="muted">{created}</div>
          </div>
          <div class="card-row">
            <div class="muted">{conversation_label}: {conversation}</div>
            <div class="muted">{case_label}: {case_id}</div>
          </div>
          <div class="card-row">{actions}</div>
        </div>
    """.format(
        summary=html.escape(getattr(case, "summary", "Escalated case") or "Escalated case"),
        reason_label=html.escape(tr(lang, "admin.labels.reason")),
        reason=html.escape(getattr(case, "reason", "-")),
        created=_format_ts(getattr(case, "created_at", None)),
        conversation_label=html.escape(tr(lang, "admin.labels.conversation")),
        conversation=html.escape(getattr(case, "source_conversation_id", "")),
        case_label=html.escape(tr(lang, "admin.labels.case_id")),
        case_id=html.escape(getattr(case, "case_id", "")),
        actions="".join(quick_actions),
    )

    content = "".join(
        [
            summary_block,
            _render_section(tr(lang, "admin.sections.transcript"), transcript_html),
        ]
    )
    return HTMLResponse(
        _wrap_page(
            request,
            content,
            title=tr(lang, "admin.observability.title"),
            active="observability",
            page_lang=lang,
        )
    )


@router.post("/v1/admin/bookings/{booking_id}/cancel", response_model=booking_schemas.BookingResponse)
async def cancel_booking(
    http_request: Request,
    booking_id: str,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
):
    org_id = getattr(http_request.state, "org_id", None) or entitlements.resolve_org_id(http_request)
    booking_result = await session.execute(
        select(Booking)
        .where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        .options(selectinload(Booking.worker_assignments))
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    before_state = booking_schemas.BookingResponse(
        booking_id=booking.booking_id,
        status=booking.status,
        starts_at=booking.starts_at,
        duration_minutes=booking.duration_minutes,
        actual_duration_minutes=booking.actual_duration_minutes,
        deposit_required=booking.deposit_required,
        deposit_cents=booking.deposit_cents,
        deposit_policy=booking.deposit_policy,
        deposit_status=booking.deposit_status,
        checkout_url=None,
        risk_score=booking.risk_score,
        risk_band=booking.risk_band,
        risk_reasons=booking.risk_reasons,
        cancellation_exception=booking.cancellation_exception,
        cancellation_exception_note=booking.cancellation_exception_note,
    ).model_dump(mode="json")

    try:
        booking_service.assert_valid_booking_transition(booking.status, "CANCELLED")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    booking.status = "CANCELLED"
    response_body = booking_schemas.BookingResponse(
        booking_id=booking.booking_id,
        status=booking.status,
        starts_at=booking.starts_at,
        duration_minutes=booking.duration_minutes,
        actual_duration_minutes=booking.actual_duration_minutes,
        deposit_required=booking.deposit_required,
        deposit_cents=booking.deposit_cents,
        deposit_policy=booking.deposit_policy,
        deposit_status=booking.deposit_status,
        checkout_url=None,
        risk_score=booking.risk_score,
        risk_band=booking.risk_band,
        risk_reasons=booking.risk_reasons,
        cancellation_exception=booking.cancellation_exception,
        cancellation_exception_note=booking.cancellation_exception_note,
    )
    http_request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="booking_cancel",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before_state,
        after=response_body.model_dump(mode="json"),
    )
    await session.commit()
    return response_body


@router.post("/v1/admin/bookings/{booking_id}/reschedule", response_model=booking_schemas.BookingResponse)
async def reschedule_booking(
    http_request: Request,
    booking_id: str,
    payload: booking_schemas.BookingRescheduleRequest,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
):
    org_id = getattr(http_request.state, "org_id", None) or entitlements.resolve_org_id(http_request)
    booking_result = await session.execute(
        select(Booking)
        .where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        .options(selectinload(Booking.worker_assignments))
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    if booking.status in {"DONE", "CANCELLED"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking is no longer active")

    before_state = booking_schemas.BookingResponse(
        booking_id=booking.booking_id,
        status=booking.status,
        starts_at=booking.starts_at,
        duration_minutes=booking.duration_minutes,
        actual_duration_minutes=booking.actual_duration_minutes,
        deposit_required=booking.deposit_required,
        deposit_cents=booking.deposit_cents,
        deposit_policy=booking.deposit_policy,
        deposit_status=booking.deposit_status,
        checkout_url=None,
        risk_score=booking.risk_score,
        risk_band=booking.risk_band,
        risk_reasons=booking.risk_reasons,
        cancellation_exception=booking.cancellation_exception,
        cancellation_exception_note=booking.cancellation_exception_note,
    ).model_dump(mode="json")

    try:
        booking = await booking_service.reschedule_booking(
            session,
            booking,
            payload.starts_at,
            payload.duration_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    response_body = booking_schemas.BookingResponse(
        booking_id=booking.booking_id,
        status=booking.status,
        starts_at=booking.starts_at,
        duration_minutes=booking.duration_minutes,
        actual_duration_minutes=booking.actual_duration_minutes,
        deposit_required=booking.deposit_required,
        deposit_cents=booking.deposit_cents,
        deposit_policy=booking.deposit_policy,
        deposit_status=booking.deposit_status,
        checkout_url=None,
        risk_score=booking.risk_score,
        risk_band=booking.risk_band,
        risk_reasons=booking.risk_reasons,
        cancellation_exception=booking.cancellation_exception,
        cancellation_exception_note=booking.cancellation_exception_note,
    )
    http_request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="booking_reschedule",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before_state,
        after=response_body.model_dump(mode="json"),
    )
    await session.commit()
    return response_body


@router.post(
    "/v1/admin/bookings/{booking_id}/complete",
    response_model=booking_schemas.BookingResponse,
)
async def complete_booking(
    http_request: Request,
    booking_id: str,
    payload: booking_schemas.BookingCompletionRequest,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
):
    org_id = getattr(http_request.state, "org_id", None) or entitlements.resolve_org_id(http_request)
    existing_result = await session.execute(
        select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
    )
    existing = existing_result.scalar_one_or_none()
    before_state = None
    if existing:
        before_state = booking_schemas.BookingResponse(
            booking_id=existing.booking_id,
            status=existing.status,
            starts_at=existing.starts_at,
            duration_minutes=existing.duration_minutes,
            actual_duration_minutes=existing.actual_duration_minutes,
            deposit_required=existing.deposit_required,
            deposit_cents=existing.deposit_cents,
            deposit_policy=existing.deposit_policy,
            deposit_status=existing.deposit_status,
            checkout_url=None,
            risk_score=existing.risk_score,
            risk_band=existing.risk_band,
            risk_reasons=existing.risk_reasons,
            cancellation_exception=existing.cancellation_exception,
            cancellation_exception_note=existing.cancellation_exception_note,
        ).model_dump(mode="json")
    try:
        booking = await booking_service.mark_booking_completed(
            session, booking_id, payload.actual_duration_minutes, org_id=org_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    try:
        lead = await session.get(Lead, booking.lead_id) if booking.lead_id else None
        adapter = _email_adapter(http_request)
        if lead and lead.email:
            token = nps_service.issue_nps_token(
                booking.booking_id,
                client_id=booking.client_id,
                email=lead.email,
                secret=settings.client_portal_secret,
            )
            base_url = settings.public_base_url.rstrip("/") if settings.public_base_url else str(http_request.base_url).rstrip("/")
            survey_link = f"{base_url}/nps/{booking.booking_id}?token={token}"
            await email_service.send_nps_survey_email(
                session=session,
                adapter=adapter,
                booking=booking,
                lead=lead,
                survey_link=survey_link,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "nps_email_failed",
            extra={"extra": {"order_id": booking.booking_id, "reason": type(exc).__name__}},
        )

    response_body = booking_schemas.BookingResponse(
        booking_id=booking.booking_id,
        status=booking.status,
        starts_at=booking.starts_at,
        duration_minutes=booking.duration_minutes,
        actual_duration_minutes=booking.actual_duration_minutes,
        deposit_required=booking.deposit_required,
        deposit_cents=booking.deposit_cents,
        deposit_policy=booking.deposit_policy,
        deposit_status=booking.deposit_status,
        checkout_url=None,
        risk_score=booking.risk_score,
        risk_band=booking.risk_band,
        risk_reasons=booking.risk_reasons,
        cancellation_exception=booking.cancellation_exception,
        cancellation_exception_note=booking.cancellation_exception_note,
    )
    http_request.state.explicit_admin_audit = True
    await audit_service.record_action(
        session,
        identity=identity,
        action="booking_complete",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before_state,
        after=response_body.model_dump(mode="json"),
    )
    await session.commit()
    return response_body


def _invoice_response(invoice: Invoice) -> invoice_schemas.InvoiceResponse:
    data = invoice_service.build_invoice_response(invoice)
    return invoice_schemas.InvoiceResponse(**data)


def _ticket_response(ticket: SupportTicket) -> nps_schemas.TicketResponse:
    return nps_schemas.TicketResponse(
        id=ticket.id,
        order_id=ticket.order_id,
        client_id=ticket.client_id,
        status=ticket.status,
        priority=ticket.priority,
        subject=ticket.subject,
        body=ticket.body,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _invoice_list_item(invoice: Invoice) -> invoice_schemas.InvoiceListItem:
    data = invoice_service.build_invoice_list_item(invoice)
    return invoice_schemas.InvoiceListItem(**data)


OVERDUE_BUCKETS: tuple[str, ...] = ("critical", "attention", "recent")
OVERDUE_TEMPLATE_KEYS: dict[str, str] = {
    "critical": "final",
    "attention": "second",
    "recent": "gentle",
}
OVERDUE_TOP_LIMIT = 5


def _bucket_for_days_overdue(days_overdue: int) -> str | None:
    if days_overdue <= 0:
        return None
    if days_overdue > 14:
        return "critical"
    if days_overdue >= 7:
        return "attention"
    return "recent"


def _overdue_bucket_bounds(bucket: str, as_of: date) -> tuple[date | None, date | None]:
    if bucket == "recent":
        return as_of - timedelta(days=6), as_of - timedelta(days=1)
    if bucket == "attention":
        return as_of - timedelta(days=14), as_of - timedelta(days=7)
    if bucket == "critical":
        return None, as_of - timedelta(days=15)
    return None, None


async def _get_org_invoice(
    session: AsyncSession,
    invoice_id: str,
    org_id: uuid.UUID,
    *,
    options: tuple = (),
) -> Invoice | None:
    stmt = (
        select(Invoice)
        .options(*options)
        .where(Invoice.invoice_id == invoice_id, Invoice.org_id == org_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _query_invoice_list(
    *,
    session: AsyncSession,
    org_id: uuid.UUID,
    status_filter: str | None,
    customer_id: str | None,
    order_id: str | None,
    q: str | None,
    from_date: date | None = None,
    to_date: date | None = None,
    amount_min: int | None = None,
    amount_max: int | None = None,
    overdue_bucket: Literal["critical", "attention", "recent"] | None = None,
    as_of: date | None = None,
    page: int,
    page_size: int = 50,
) -> invoice_schemas.InvoiceListResponse:
    filters = []
    if status_filter:
        try:
            normalized_status = invoice_statuses.normalize_status(status_filter)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        filters.append(Invoice.status == normalized_status)
    if customer_id:
        filters.append(Invoice.customer_id == customer_id)
    if order_id:
        filters.append(Invoice.order_id == order_id)
    if from_date:
        filters.append(Invoice.issue_date >= from_date)
    if to_date:
        filters.append(Invoice.issue_date <= to_date)
    if amount_min is not None:
        filters.append(Invoice.total_cents >= amount_min)
    if amount_max is not None:
        filters.append(Invoice.total_cents <= amount_max)
    if overdue_bucket:
        as_of_date = as_of or date.today()
        start_date, end_date = _overdue_bucket_bounds(overdue_bucket, as_of_date)
        filters.append(Invoice.due_date.is_not(None))
        filters.append(Invoice.due_date < as_of_date)
        filters.append(
            Invoice.status.notin_(
                [invoice_statuses.INVOICE_STATUS_PAID, invoice_statuses.INVOICE_STATUS_VOID]
            )
        )
        if overdue_bucket == "critical":
            if end_date:
                filters.append(Invoice.due_date <= end_date)
        else:
            if start_date:
                filters.append(Invoice.due_date >= start_date)
            if end_date:
                filters.append(Invoice.due_date <= end_date)

    # Enhanced search: invoice number OR client name/email
    if q:
        search_term = q.lower()
        search_filters = [func.lower(Invoice.invoice_number).like(f"%{search_term}%")]
        # Join with Lead to search by client name/email
        lead_search = or_(
            func.lower(Lead.name).like(f"%{search_term}%"),
            func.lower(Lead.email).like(f"%{search_term}%"),
        )
        filters.append(
            or_(
                func.lower(Invoice.invoice_number).like(f"%{search_term}%"),
                and_(Invoice.customer_id.is_not(None), Invoice.customer_id == Lead.lead_id, lead_search),
            )
        )

    base_query = select(Invoice).outerjoin(Lead, Invoice.customer_id == Lead.lead_id).where(Invoice.org_id == org_id, *filters)
    # Count distinct invoices from the filtered subquery to avoid inflated counts from joins
    subq = base_query.subquery()
    count_stmt = select(func.count(func.distinct(subq.c.invoice_id)))
    total = int((await session.scalar(count_stmt)) or 0)

    stmt = (
        base_query.options(selectinload(Invoice.payments))
        .order_by(Invoice.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await session.execute(stmt)
    invoices = result.scalars().all()
    return invoice_schemas.InvoiceListResponse(
        invoices=[_invoice_list_item(inv) for inv in invoices],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/v1/admin/invoices", response_model=invoice_schemas.InvoiceListResponse)
async def list_invoices(
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: str | None = None,
    order_id: str | None = None,
    q: str | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    amount_min: int | None = None,
    amount_max: int | None = None,
    overdue_bucket: Literal["critical", "attention", "recent"] | None = Query(default=None),
    as_of: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    http_request: Request = None,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_permission_keys("invoices.view")),
    ) -> invoice_schemas.InvoiceListResponse:
    org_id = entitlements.resolve_org_id(http_request)
    return await _query_invoice_list(
        session=session,
        org_id=org_id,
        status_filter=status_filter,
        customer_id=customer_id,
        order_id=order_id,
        q=q,
        from_date=from_date,
        to_date=to_date,
        amount_min=amount_min,
        amount_max=amount_max,
        overdue_bucket=overdue_bucket,
        as_of=as_of,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/v1/admin/invoices/overdue_summary",
    response_model=invoice_schemas.OverdueSummaryResponse,
)
async def overdue_invoice_summary(
    http_request: Request,
    as_of: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_permission_keys("invoices.view")),
) -> invoice_schemas.OverdueSummaryResponse:
    org_id = entitlements.resolve_org_id(http_request)
    as_of_date = as_of or date.today()
    paid_subq = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(Payment.amount_cents), 0).label("paid_cents"),
        )
        .where(Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED)
        .group_by(Payment.invoice_id)
        .subquery()
    )
    stmt = (
        select(
            Invoice,
            Lead,
            func.coalesce(paid_subq.c.paid_cents, 0).label("paid_cents"),
        )
        .outerjoin(Lead, Invoice.customer_id == Lead.lead_id)
        .outerjoin(paid_subq, paid_subq.c.invoice_id == Invoice.invoice_id)
        .where(
            Invoice.org_id == org_id,
            Invoice.due_date.is_not(None),
            Invoice.due_date < as_of_date,
            Invoice.status.notin_(
                [invoice_statuses.INVOICE_STATUS_PAID, invoice_statuses.INVOICE_STATUS_VOID]
            ),
        )
    )
    rows = (await session.execute(stmt)).all()

    bucket_data = {
        bucket: {
            "total_count": 0,
            "total_amount_due": 0,
            "items": [],
        }
        for bucket in OVERDUE_BUCKETS
    }

    for invoice, lead, paid_cents in rows:
        if invoice.due_date is None:
            continue
        balance_due = max(invoice.total_cents - int(paid_cents or 0), 0)
        if balance_due <= 0:
            continue
        days_overdue = (as_of_date - invoice.due_date).days
        bucket = _bucket_for_days_overdue(days_overdue)
        if bucket is None:
            continue
        client_label = None
        client_email = None
        if lead is not None:
            client_label = lead.name or lead.email
            client_email = lead.email
        if client_label is None and invoice.customer_id:
            client_label = invoice.customer_id
        summary_item = invoice_schemas.OverdueInvoiceSummary(
            invoice_id=invoice.invoice_id,
            invoice_number=invoice.invoice_number,
            client=client_label,
            client_email=client_email,
            amount_due=balance_due,
            due_at=invoice.due_date,
            days_overdue=days_overdue,
            status=invoice.status,
        )
        bucket_entry = bucket_data[bucket]
        bucket_entry["total_count"] += 1
        bucket_entry["total_amount_due"] += balance_due
        bucket_entry["items"].append(summary_item)

    bucket_summaries: list[invoice_schemas.OverdueBucketSummary] = []
    for bucket in OVERDUE_BUCKETS:
        items = bucket_data[bucket]["items"]
        top_items = sorted(
            items,
            key=lambda item: (-item.days_overdue, -item.amount_due, item.due_at),
        )[:OVERDUE_TOP_LIMIT]
        bucket_summaries.append(
            invoice_schemas.OverdueBucketSummary(
                bucket=bucket,
                total_count=bucket_data[bucket]["total_count"],
                total_amount_due=bucket_data[bucket]["total_amount_due"],
                template_key=OVERDUE_TEMPLATE_KEYS[bucket],
                invoices=top_items,
            )
        )

    return invoice_schemas.OverdueSummaryResponse(as_of=as_of_date, buckets=bucket_summaries)


@router.post(
    "/v1/admin/invoices/overdue_remind",
    response_model=invoice_schemas.OverdueRemindResponse,
    status_code=status.HTTP_200_OK,
)
async def send_overdue_bucket_reminders(
    request: invoice_schemas.OverdueRemindRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_csrf),
    _admin: AdminIdentity = Depends(require_permission_keys("invoices.send")),
) -> invoice_schemas.OverdueRemindResponse:
    org_id = entitlements.resolve_org_id(http_request)
    as_of_date = date.today()
    adapter = _email_adapter(http_request)
    if adapter is None:
        return problem_details(
            request=http_request,
            status=status.HTTP_502_BAD_GATEWAY,
            title="Email Adapter Unavailable",
            detail="Email adapter unavailable for overdue reminders.",
        )

    paid_subq = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(Payment.amount_cents), 0).label("paid_cents"),
        )
        .where(Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED)
        .group_by(Payment.invoice_id)
        .subquery()
    )
    stmt = (
        select(
            Invoice,
            Lead,
            func.coalesce(paid_subq.c.paid_cents, 0).label("paid_cents"),
        )
        .outerjoin(Lead, Invoice.customer_id == Lead.lead_id)
        .outerjoin(paid_subq, paid_subq.c.invoice_id == Invoice.invoice_id)
        .where(
            Invoice.org_id == org_id,
            Invoice.due_date.is_not(None),
            Invoice.due_date < as_of_date,
            Invoice.status.notin_(
                [invoice_statuses.INVOICE_STATUS_PAID, invoice_statuses.INVOICE_STATUS_VOID]
            ),
        )
    )
    if request.invoice_ids:
        stmt = stmt.where(Invoice.invoice_id.in_(request.invoice_ids))
    else:
        start_date, end_date = _overdue_bucket_bounds(request.bucket, as_of_date)
        if request.bucket == "critical":
            if end_date:
                stmt = stmt.where(Invoice.due_date <= end_date)
        else:
            if start_date:
                stmt = stmt.where(Invoice.due_date >= start_date)
            if end_date:
                stmt = stmt.where(Invoice.due_date <= end_date)

    rows = (await session.execute(stmt)).all()
    rows_by_id = {invoice.invoice_id: (invoice, lead, paid_cents) for invoice, lead, paid_cents in rows}

    succeeded: list[str] = []
    failed: list[dict] = []

    invoice_ids = request.invoice_ids or list(rows_by_id.keys())
    for invoice_id in invoice_ids:
        row = rows_by_id.get(invoice_id)
        if row is None:
            failed.append({"invoice_id": invoice_id, "error": "Invoice not found"})
            continue
        invoice, lead, paid_cents = row
        if invoice.due_date is None:
            failed.append({"invoice_id": invoice_id, "error": "Invoice missing due date"})
            continue
        balance_due = max(invoice.total_cents - int(paid_cents or 0), 0)
        if balance_due <= 0:
            failed.append({"invoice_id": invoice_id, "error": "Invoice already settled"})
            continue
        days_overdue = (as_of_date - invoice.due_date).days
        bucket = _bucket_for_days_overdue(days_overdue)
        if bucket != request.bucket:
            failed.append({"invoice_id": invoice_id, "error": "Invoice not in requested bucket"})
            continue
        if lead is None or not lead.email:
            failed.append({"invoice_id": invoice_id, "error": "Invoice missing customer email"})
            continue

        token = await invoice_service.upsert_public_token(session, invoice, mark_sent=True)
        base_url = settings.public_base_url.rstrip("/") if settings.public_base_url else None
        if base_url:
            public_link = f"{base_url}/i/{token}"
            public_link_pdf = f"{base_url}/i/{token}.pdf"
        else:
            public_link = str(http_request.url_for("public_invoice_view", token=token))
            public_link_pdf = str(http_request.url_for("public_invoice_pdf", token=token))

        subject = f"Reminder: Invoice {invoice.invoice_number}"
        body = (
            f"Hi {lead.name},\n\n"
            f"This is a reminder about invoice {invoice.invoice_number}.\n"
            f"View online: {public_link}\n"
            f"Download PDF: {public_link_pdf}\n"
            f"Balance due: {_format_money(balance_due, invoice.currency)}\n\n"
            "If you have questions or already paid, please reply to this email."
        )
        try:
            delivered = await adapter.send_email(recipient=lead.email, subject=subject, body=body)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "overdue_bucket_reminder_failed",
                extra={"extra": {"invoice_id": invoice_id, "reason": type(exc).__name__}},
            )
            failed.append({"invoice_id": invoice_id, "error": "Email send error"})
            continue
        if not delivered:
            failed.append({"invoice_id": invoice_id, "error": "Email delivery failed"})
            continue
        if invoice.status == invoice_statuses.INVOICE_STATUS_DRAFT:
            invoice.status = invoice_statuses.INVOICE_STATUS_SENT
        succeeded.append(invoice_id)

    await session.commit()
    return invoice_schemas.OverdueRemindResponse(
        bucket=request.bucket,
        template_key=OVERDUE_TEMPLATE_KEYS[request.bucket],
        succeeded=succeeded,
        failed=failed,
    )


@router.get("/v1/admin/ui/invoices", response_class=HTMLResponse)
async def admin_invoice_list_ui(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    customer_id: str | None = Query(default=None),
    order_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    overdue_bucket: Literal["critical", "attention", "recent"] | None = Query(default=None),
    as_of: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_finance),
) -> HTMLResponse:
    org_id = entitlements.resolve_org_id(request)
    invoice_list = await _query_invoice_list(
        session=session,
        org_id=org_id,
        status_filter=status_filter,
        customer_id=customer_id,
        order_id=order_id,
        q=q,
        overdue_bucket=overdue_bucket,
        as_of=as_of,
        page=page,
    )

    def _cell(label: str, value: str) -> str:
        return f"<div class=\"muted small\">{html.escape(label)}: {html.escape(value)}</div>"

    rows: list[str] = []
    today = date.today()
    for invoice in invoice_list.invoices:
        overdue = invoice.status == invoice_statuses.INVOICE_STATUS_OVERDUE or (
            invoice.due_date and invoice.balance_due_cents > 0 and invoice.due_date < today
        )
        row_class = " class=\"row-highlight\"" if overdue else ""
        balance_class = "danger" if invoice.balance_due_cents > 0 else "success"
        rows.append(
            """
            <tr{row_class}>
              <td>
                <div class="title"><a href="/v1/admin/ui/invoices/{invoice_id}">{invoice_number}</a></div>
                {_id}
              </td>
              <td>{status}</td>
              <td>{issue}{due}</td>
              <td class="align-right">{total}<div class="muted small">Paid: {paid}</div></td>
              <td class="align-right {balance_class}">{balance}</td>
              <td>{order}{customer}</td>
              <td class="muted small">{created}</td>
            </tr>
            """.format(
                row_class=row_class,
                invoice_id=html.escape(invoice.invoice_id),
                invoice_number=html.escape(invoice.invoice_number),
                status=_status_badge(invoice.status),
                issue=_cell("Issue", _format_date(invoice.issue_date)),
                due=_cell("Due", _format_date(invoice.due_date)),
                total=_format_money(invoice.total_cents, invoice.currency),
                paid=_format_money(invoice.paid_cents, invoice.currency),
                balance=_format_money(invoice.balance_due_cents, invoice.currency),
                balance_class=balance_class,
                order=_cell("Order", invoice.order_id or "-"),
                customer=_cell("Customer", invoice.customer_id or "-"),
                created=_format_dt(invoice.created_at),
                _id=_cell("ID", invoice.invoice_id),
            )
        )

    table_body = "".join(rows) if rows else f"<tr><td colspan=7>{_render_empty('No invoices match these filters.')}</td></tr>"

    total_pages = max(math.ceil(invoice_list.total / invoice_list.page_size), 1)
    prev_page = invoice_list.page - 1 if invoice_list.page > 1 else None
    next_page = invoice_list.page + 1 if invoice_list.page < total_pages else None
    status_ui = status_filter.upper() if status_filter else None
    base_params = {
        "status": status_filter,
        "customer_id": customer_id,
        "order_id": order_id,
        "q": q,
    }

    pagination_parts = [
        "<div class=\"card-row\">",
        f"<div class=\"muted\">Page {invoice_list.page} of {total_pages} · {invoice_list.total} total</div>",
        "<div class=\"actions\">",
    ]
    if prev_page:
        prev_query = _build_query({**base_params, "page": prev_page})
        pagination_parts.append(f"<a class=\"btn secondary\" href=\"?{prev_query}\">Previous</a>")
    if next_page:
        next_query = _build_query({**base_params, "page": next_page})
        pagination_parts.append(f"<a class=\"btn secondary\" href=\"?{next_query}\">Next</a>")
    pagination_parts.append("</div></div>")
    pagination = "".join(pagination_parts)

    status_options = "".join(
        f'<option value="{html.escape(status)}" {"selected" if status_ui == status else ""}>{html.escape(status.title())}</option>'
        for status in sorted(invoice_statuses.INVOICE_STATUSES)
    )

    filters_html = f"""
        <form class=\"filters\" method=\"get\">
          <div class=\"form-group\">
            <label>Status</label>
            <select class=\"input\" name=\"status\">
              <option value=\"\">Any</option>
              {status_options}
            </select>
          </div>
          <div class=\"form-group\">
            <label>Customer ID</label>
            <input class=\"input\" type=\"text\" name=\"customer_id\" value=\"{html.escape(customer_id or '')}\" placeholder=\"lead id\" />
          </div>
          <div class=\"form-group\">
            <label>Order ID</label>
            <input class=\"input\" type=\"text\" name=\"order_id\" value=\"{html.escape(order_id or '')}\" placeholder=\"booking id\" />
          </div>
          <div class=\"form-group\">
            <label>Invoice #</label>
            <input class=\"input\" type=\"text\" name=\"q\" value=\"{html.escape(q or '')}\" placeholder=\"INV-2024-000001\" />
          </div>
          <div class=\"form-group\">
            <label>&nbsp;</label>
            <div class=\"actions\">
              <button class=\"btn\" type=\"submit\">Apply</button>
              <a class=\"btn secondary\" href=\"/v1/admin/ui/invoices\">Reset</a>
            </div>
          </div>
        </form>
    """

    content = "".join(
        [
            "<div class=\"card\">",
            f"<div class=\"card-row\"><div><div class=\"title with-icon\">{_icon('receipt')}<span>Invoices</span></div><div class=\"muted\">Search, filter and drill into invoices</div></div>",
            f"<div class=\"chip\">Total: {invoice_list.total}</div></div>",
            "<div class=\"muted small\">Invoices use English labels (Invoice, Subtotal, Tax, Total) regardless of your language preference.</div>",
            filters_html,
            "<table class=\"table\">",
            "<thead><tr><th>Invoice</th><th>Status</th><th>Dates</th><th>Total</th><th>Balance</th><th>Order/Customer</th><th>Created</th></tr></thead>",
            f"<tbody>{table_body}</tbody>",
            "</table>",
            pagination,
            "</div>",
        ]
    )
    return HTMLResponse(
        _wrap_page(
            request,
            content,
            title="Admin — Invoices",
            active="invoices",
            page_lang="en",
        )
    )


@router.get("/v1/admin/invoices/{invoice_id}", response_model=invoice_schemas.InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_finance),
) -> invoice_schemas.InvoiceResponse:
    org_id = entitlements.resolve_org_id(http_request)
    invoice = await _get_org_invoice(
        session,
        invoice_id,
        org_id,
        options=(
            selectinload(Invoice.items),
            selectinload(Invoice.payments),
            selectinload(Invoice.email_events),
        ),
    )
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    # Get customer and booking info
    customer = await invoice_service.fetch_customer(session, invoice)
    booking = None
    if invoice.order_id:
        booking_result = await session.execute(
            select(Booking).where(Booking.booking_id == invoice.order_id)
        )
        booking = booking_result.scalar_one_or_none()

    # Get or create public token for payment link
    public_link = None
    if invoice.status != invoice_statuses.INVOICE_STATUS_VOID:
        token, created = await invoice_service.get_or_create_public_token_hash(session, invoice)
        if created:
            await session.commit()
        base_url = settings.public_base_url.rstrip("/") if settings.public_base_url else None
        if base_url:
            public_link = f"{base_url}/i/{token}"
        else:
            public_link = str(http_request.url_for("public_invoice_view", token=token))

    # Build enhanced response
    data = invoice_service.build_invoice_detail_response(
        invoice, public_link=public_link, customer=customer, booking=booking
    )
    return invoice_schemas.InvoiceResponse(**data)


@router.get("/v1/admin/invoices/{invoice_id}/pdf", response_class=Response)
async def download_invoice_pdf_admin(
    invoice_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_permission_keys("invoices.view")),
) -> Response:
    """Download invoice PDF (admin endpoint with authentication)."""
    org_id = entitlements.resolve_org_id(http_request)
    invoice = await _get_org_invoice(
        session,
        invoice_id,
        org_id,
        options=(selectinload(Invoice.items), selectinload(Invoice.payments)),
    )
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    if invoice.status == invoice_statuses.INVOICE_STATUS_VOID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invoice is void")

    lead = await invoice_service.fetch_customer(session, invoice)
    document = await document_service.get_or_create_invoice_document(session, invoice=invoice, lead=lead)
    await session.commit()
    pdf_bytes = document_service.pdf_bytes(document)
    filename = f"{invoice.invoice_number}.pdf"
    headers = {"Content-Disposition": f"inline; filename=\"{filename}\""}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/v1/admin/ui/invoices/{invoice_id}", response_class=HTMLResponse)
async def admin_invoice_detail_ui(
    invoice_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_finance),
) -> HTMLResponse:
    org_id = entitlements.resolve_org_id(request)
    invoice_model = await _get_org_invoice(
        session,
        invoice_id,
        org_id,
        options=(selectinload(Invoice.items), selectinload(Invoice.payments)),
    )
    if invoice_model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    lead = await invoice_service.fetch_customer(session, invoice_model)
    invoice = _invoice_response(invoice_model)
    csrf_token = get_csrf_token(request)

    customer_bits: list[str] = []
    if lead:
        contact_parts = [part for part in [lead.email, lead.phone] if part]
        contact = " · ".join(contact_parts) if contact_parts else "-"
        customer_bits.append(f"<div class=\"title\">{html.escape(lead.name)}</div>")
        customer_bits.append(f"<div class=\"muted\">{html.escape(contact)}</div>")
        if lead.address:
            customer_bits.append(f"<div class=\"muted small\">{html.escape(lead.address)}</div>")
    else:
        customer_bits.append(f"<div class=\"title\">Customer</div>")
        customer_bits.append(f"<div class=\"muted\">ID: {html.escape(invoice.customer_id or '-')}</div>")
    customer_section = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\"><div class=\"title\">Customer</div>",
            f"<div class=\"muted small\">Invoice ID: {html.escape(invoice.invoice_id)} {_copy_button('Copy ID', invoice.invoice_id)}</div></div>",
            "<div class=\"stack\">",
            *customer_bits,
            f"<div class=\"muted small\">Order: {html.escape(invoice.order_id or '-')}</div>",
            "</div></div>",
        ]
    )

    items_rows = "".join(
        """
        <tr>
          <td>{desc}</td>
          <td class="align-right">{qty}</td>
          <td class="align-right">{unit}</td>
          <td class="align-right">{line}</td>
        </tr>
        """.format(
            desc=html.escape(item.description),
            qty=item.qty,
            unit=_format_money(item.unit_price_cents, invoice.currency),
            line=_format_money(item.line_total_cents, invoice.currency),
        )
        for item in invoice.items
    )
    if not items_rows:
        items_rows = f"<tr><td colspan=4>{_render_empty('No items recorded')}</td></tr>"

    payment_rows = "".join(
        """
        <tr>
          <td>{created}</td>
          <td>{provider}</td>
          <td>{method}</td>
          <td class="align-right">{amount}</td>
          <td>{status}</td>
          <td>{reference}</td>
        </tr>
        """.format(
            created=_format_dt(payment.created_at),
            provider=html.escape(payment.provider_ref or payment.provider or "-"),
            method=html.escape(payment.method),
            amount=_format_money(payment.amount_cents, payment.currency),
            status=html.escape(payment.status),
            reference=html.escape(payment.reference or "-"),
        )
        for payment in invoice.payments
    )
    if not payment_rows:
        payment_rows = f"<tr id=\"payments-empty\"><td colspan=6>{_render_empty('No payments yet')}</td></tr>"

    copy_number_btn = _copy_button("Copy number", invoice.invoice_number)
    status_badge = _status_badge(invoice.status).replace("<span", "<span id=\"status-badge\"", 1)
    overdue = invoice.status == invoice_statuses.INVOICE_STATUS_OVERDUE or (
        invoice.due_date and invoice.balance_due_cents > 0 and invoice.due_date < date.today()
    )
    balance_class = " danger" if invoice.balance_due_cents else ""
    due_class = " danger" if overdue else ""
    header = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div>",
            f"<div class=\"title\">Invoice {html.escape(invoice.invoice_number)}</div>",
            f"<div class=\"muted small\">{copy_number_btn} {_copy_button('Copy invoice ID', invoice.invoice_id)}</div>",
            "</div>",
            f"<div class=\"actions\">{status_badge}</div>",
            "</div>",
            "<div class=\"metric-grid\">",
            f"<div class=\"metric\"><div class=\"label\">Total</div><div id=\"total-amount\" class=\"value\">{_format_money(invoice.total_cents, invoice.currency)}</div></div>",
            f"<div class=\"metric\"><div class=\"label\">Paid</div><div id=\"paid-amount\" class=\"value\">{_format_money(invoice.paid_cents, invoice.currency)}</div></div>",
            f"<div class=\"metric\"><div class=\"label\">Balance due</div><div id=\"balance-due\" class=\"value{balance_class}\">{_format_money(invoice.balance_due_cents, invoice.currency)}</div></div>",
            f"<div class=\"metric\"><div class=\"label\">Due date</div><div id=\"due-date\" class=\"value{due_class}\">{_format_date(invoice.due_date)}</div></div>",
            "</div>",
            "<div class=\"card-row\">",
            "<div class=\"actions\">",
            "<button id=\"send-invoice-btn\" class=\"btn\" type=\"button\" onclick=\"sendInvoice()\">Send invoice</button>",
            "<span id=\"public-link-slot\"></span>",
            "</div>",
            "<div id=\"action-message\" class=\"muted small\"></div>",
            "</div>",
            "</div>",
        ]
    )

    csrf_input = render_csrf_input(csrf_token)

    payment_form = f"""
        <form id="payment-form" class="stack" onsubmit="recordPayment(event)">
          <div class="form-group">
            <label>Amount ({html.escape(invoice.currency)})</label>
            <input class="input" type="number" name="amount" step="0.01" min="0.01" placeholder="100.00" required />
          </div>
          <div class="form-group">
            <label>Method</label>
            <select class="input" name="method">
              <option value="cash">Cash</option>
              <option value="etransfer">E-transfer</option>
              <option value="card">Card</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div class="form-group">
            <label>Reference</label>
            <input class="input" type="text" name="reference" placeholder="Receipt or note" />
          </div>
          {csrf_input}
          <button class="btn" type="submit">Record payment</button>
        </form>
    """

    items_table = "".join(
        [
            "<div class=\"card section\">",
            "<div class=\"card-row\"><div class=\"title\">Line items</div>",
            f"<div class=\"muted small\">{len(invoice.items)} item(s)</div></div>",
            "<table class=\"table\"><thead><tr><th>Description</th><th class=\"align-right\">Qty</th><th class=\"align-right\">Unit</th><th class=\"align-right\">Line total</th></tr></thead>",
            f"<tbody>{items_rows}</tbody>",
            "</table>",
            "</div>",
        ]
    )

    payments_table = "".join(
        [
            "<div class=\"card section\">",
            "<div class=\"card-row\"><div class=\"title\">Payments</div><div class=\"muted small\">Including manual entries</div></div>",
            "<table class=\"table\"><thead><tr><th>Created</th><th>Provider</th><th>Method</th><th class=\"align-right\">Amount</th><th>Status</th><th>Reference</th></tr></thead>",
            f"<tbody id=\"payments-table-body\">{payment_rows}</tbody>",
            "</table>",
            "</div>",
        ]
    )

    totals_block = "".join(
        [
            "<div class=\"card section\">",
            "<div class=\"title\">Totals</div>",
            "<div class=\"stack\">",
            f"<div><strong>Subtotal:</strong> {_format_money(invoice.subtotal_cents, invoice.currency)}</div>",
            f"<div><strong>Tax:</strong> {_format_money(invoice.tax_cents, invoice.currency)}</div>",
            f"<div><strong>Total:</strong> {_format_money(invoice.total_cents, invoice.currency)}</div>",
            "</div>",
            "</div>",
        ]
    )

    notes_block = ""
    if invoice.notes:
        notes_block = "".join(
            [
                "<div class=\"card section\">",
                "<div class=\"title\">Notes</div>",
                f"<div class=\"note\">{html.escape(invoice.notes)}</div>",
                "</div>",
            ]
        )

    invoice_id_json = json.dumps(invoice.invoice_id)
    currency_json = json.dumps(invoice.currency)

    script = f"""
      <script>
        const invoiceId = {invoice_id_json};
        const currency = {currency_json};

        function formatMoney(cents) {{
          return `${{currency}} ${{(cents / 100).toFixed(2)}}`;
        }}

        function getCsrfToken() {{
          const tokenInput = document.querySelector('input[name="csrf_token"]');
          return tokenInput ? tokenInput.value : '';
        }}

        function isOverdue(invoice) {{
          if (!invoice.due_date) return false;
          const today = new Date().toISOString().slice(0, 10);
          return invoice.status === "OVERDUE" || (invoice.balance_due_cents > 0 && invoice.due_date < today);
        }}

        function applyInvoiceUpdate(invoice) {{
          const statusBadge = document.getElementById('status-badge');
          if (statusBadge) {{
            statusBadge.textContent = invoice.status;
            statusBadge.className = `badge badge-status status-${{invoice.status.toLowerCase()}}`;
          }}
          const paid = document.getElementById('paid-amount');
          const balance = document.getElementById('balance-due');
          if (paid) paid.textContent = formatMoney(invoice.paid_cents);
          if (balance) {{
            balance.textContent = formatMoney(invoice.balance_due_cents);
            balance.classList.toggle('danger', invoice.balance_due_cents > 0);
          }}
          const due = document.getElementById('due-date');
          if (due) {{
            if (invoice.due_date) {{
              due.textContent = invoice.due_date;
              due.classList.toggle('danger', isOverdue(invoice));
            }} else {{
              due.textContent = '-';
              due.classList.remove('danger');
            }}
          }}
        }}

        function showPublicLink(link) {{
          const slot = document.getElementById('public-link-slot');
          if (!slot || !link) return;
          slot.innerHTML = '';
          const anchor = document.createElement('a');
          anchor.href = link;
          anchor.target = '_blank';
          anchor.className = 'btn secondary small';
          anchor.textContent = 'Public link';
          slot.appendChild(anchor);
          const copy = document.createElement('button');
          copy.type = 'button';
          copy.className = 'btn secondary small';
          copy.textContent = 'Copy link';
          copy.onclick = () => navigator.clipboard.writeText(link);
          slot.appendChild(copy);
        }}


        async function sendInvoice() {{
          const button = document.getElementById('send-invoice-btn');
          const message = document.getElementById('action-message');
          button.disabled = true;
          message.textContent = 'Sending…';
          try {{
            const response = await fetch(`/v1/admin/invoices/${{invoiceId}}/send`, {{
              method: 'POST',
              credentials: 'same-origin',
              headers: {{ 'X-CSRF-Token': getCsrfToken() }},
            }});
            let data;
            let errorDetail;
            try {{
              data = await response.json();
            }} catch (_) {{
              errorDetail = await response.text();
            }}
            if (!response.ok) {{
              throw new Error((data && data.detail) || errorDetail || response.statusText || 'Send failed');
            }}
            if (!data) {{
              throw new Error(errorDetail || 'Send failed');
            }}
            applyInvoiceUpdate(data.invoice);
            showPublicLink(data.public_link);
            message.textContent = data.email_sent ? 'Invoice emailed' : 'Public link generated';
          }} catch (err) {{
            message.textContent = `Send failed: ${{err.message}}`;
          }} finally {{
            button.disabled = false;
          }}
        }}

        function appendPaymentRow(payment) {{
          const tbody = document.getElementById('payments-table-body');
          const empty = document.getElementById('payments-empty');
          if (empty) empty.remove();
          const row = document.createElement('tr');
          const cells = [
            {{ value: payment.created_at ? new Date(payment.created_at).toLocaleString() : '-' }},
            {{ value: payment.provider_ref || payment.provider || '-' }},
            {{ value: payment.method }},
            {{ value: formatMoney(payment.amount_cents), className: 'align-right' }},
            {{ value: payment.status }},
            {{ value: payment.reference || '-' }},
          ];
          cells.forEach(({{ value, className }}) => {{
            const td = document.createElement('td');
            if (className) td.className = className;
            td.textContent = value ?? '-';
            row.appendChild(td);
          }});
          tbody.appendChild(row);
        }}


        async function recordPayment(event) {{
          event.preventDefault();
          const form = event.target;
          const message = document.getElementById('action-message');
          const amount = parseFloat(form.amount.value);
          if (Number.isNaN(amount) || amount <= 0) {{
            message.textContent = 'Amount must be greater than zero';
            return;
          }}
          const payload = {{
            amount_cents: Math.round(amount * 100),
            method: form.method.value,
            reference: form.reference.value || null,
          }};
          message.textContent = 'Recording payment…';
          try {{
            const response = await fetch(`/v1/admin/invoices/${{invoiceId}}/record-payment`, {{
              method: 'POST',
              credentials: 'same-origin',
              headers: {{ 'Content-Type': 'application/json', 'X-CSRF-Token': form.csrf_token.value }},
              body: JSON.stringify(payload),
            }});
            let data;
            let errorDetail;
            try {{
              data = await response.json();
            }} catch (_) {{
              errorDetail = await response.text();
            }}
            if (!response.ok) {{
              throw new Error((data && data.detail) || errorDetail || response.statusText || 'Payment failed');
            }}
            if (!data) {{
              throw new Error(errorDetail || 'Payment failed');
            }}
            applyInvoiceUpdate(data.invoice);
            appendPaymentRow(data.payment);
            form.reset();
            message.textContent = 'Payment recorded';
          }} catch (err) {{
            message.textContent = `Payment failed: ${{err.message}}`;
          }}
        }}

      </script>
    """

    detail_layout = "".join(
        [
            header,
            customer_section,
            items_table,
            totals_block,
            payments_table,
            "<div class=\"card section\"><div class=\"title\">Record manual payment</div>",
            payment_form,
            "</div>",
            notes_block,
            script,
        ]
    )
    response = HTMLResponse(
        _wrap_page(
            request,
            detail_layout,
            title=f"Invoice {invoice.invoice_number}",
            active="invoices",
            page_lang="en",
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response


def _format_money(cents: int, currency: str) -> str:
    return f"{currency} {cents / 100:,.2f}"


def _format_date(value: date | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d")


def _ensure_timezone(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _status_badge(value: str) -> str:
    normalized = value.lower()
    warning = _icon("warning") if normalized == invoice_statuses.INVOICE_STATUS_OVERDUE.lower() else ""
    return f'<span class="badge badge-status status-{normalized}"><span class="with-icon">{warning}{html.escape(value)}</span></span>'


def _churn_badge(band: str, lang: str | None) -> str:
    normalized = band.strip().upper()
    class_map = {
        "LOW": "badge-low",
        "MEDIUM": "badge-medium",
        "HIGH": "badge-high",
    }
    badge_class = class_map.get(normalized, "badge-low")
    label = tr(lang, "admin.clients.churn_badge", band=normalized)
    return f'<span class="badge {badge_class}">{html.escape(label)}</span>'


def _note_type_label(note_type: str, lang: str | None) -> str:
    mapping = {
        ClientNote.NOTE_TYPE_NOTE: tr(lang, "admin.clients.note_type_note"),
        ClientNote.NOTE_TYPE_COMPLAINT: tr(lang, "admin.clients.note_type_complaint"),
        ClientNote.NOTE_TYPE_PRAISE: tr(lang, "admin.clients.note_type_praise"),
    }
    return mapping.get(note_type, note_type.title())


def _note_type_badge_class(note_type: str) -> str:
    return {
        ClientNote.NOTE_TYPE_NOTE: "note-badge note-badge-note",
        ClientNote.NOTE_TYPE_COMPLAINT: "note-badge note-badge-complaint",
        ClientNote.NOTE_TYPE_PRAISE: "note-badge note-badge-praise",
    }.get(note_type, "note-badge note-badge-note")


def _addon_response(model: addon_schemas.AddonDefinitionResponse | AddonDefinition) -> addon_schemas.AddonDefinitionResponse:
    if isinstance(model, addon_schemas.AddonDefinitionResponse):
        return model
    return addon_schemas.AddonDefinitionResponse(
        addon_id=model.addon_id,
        code=model.code,
        name=model.name,
        price_cents=model.price_cents,
        default_minutes=model.default_minutes,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@router.get(
    "/v1/admin/addons",
    response_model=list[addon_schemas.AddonDefinitionResponse],
)
async def list_addons(
    include_inactive: bool = True,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
) -> list[addon_schemas.AddonDefinitionResponse]:
    addons = await addon_service.list_definitions(session, include_inactive=include_inactive)
    return [_addon_response(addon) for addon in addons]


@router.post(
    "/v1/admin/addons",
    response_model=addon_schemas.AddonDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_addon(
    payload: addon_schemas.AddonDefinitionCreate,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
) -> addon_schemas.AddonDefinitionResponse:
    addon = await addon_service.create_definition(session, payload)
    await session.commit()
    await session.refresh(addon)
    return _addon_response(addon)


@router.patch(
    "/v1/admin/addons/{addon_id}",
    response_model=addon_schemas.AddonDefinitionResponse,
)
async def update_addon(
    addon_id: int,
    payload: addon_schemas.AddonDefinitionUpdate,
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
) -> addon_schemas.AddonDefinitionResponse:
    try:
        addon = await addon_service.update_definition(session, addon_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(addon)
    return _addon_response(addon)


@router.get(
    "/v1/admin/reasons",
    response_model=reason_schemas.ReasonListResponse,
)
async def admin_reason_report(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    kind: reason_schemas.ReasonKind | None = Query(None),
    format: str = Query("json"),
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
) -> Response | reason_schemas.ReasonListResponse:
    reasons = await reason_service.fetch_reasons(
        session, start=start, end=end, kind=kind
    )
    if format.lower() == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            _sanitize_row(
                [
                    "reason_id",
                    "order_id",
                    "kind",
                    "code",
                    "note",
                    "created_at",
                    "created_by",
                    "time_entry_id",
                    "invoice_item_id",
                ]
            )
        )
        for reason in reasons:
            writer.writerow(
                _sanitize_row(
                    [
                        reason.reason_id,
                        reason.order_id,
                        reason.kind,
                        reason.code,
                        reason.note or "",
                        reason.created_at.isoformat(),
                        reason.created_by or "",
                        reason.time_entry_id or "",
                        reason.invoice_item_id or "",
                    ]
                )
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=reasons.csv"},
        )

    return reason_schemas.ReasonListResponse(
        reasons=[reason_schemas.ReasonResponse.from_model(reason) for reason in reasons]
    )


@router.get(
    "/v1/admin/reports/addons",
    response_model=addon_schemas.AddonReportResponse,
)
async def admin_addon_report(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
    _admin: AdminIdentity = Depends(require_admin),
) -> addon_schemas.AddonReportResponse:
    report = await addon_service.addon_report(session, start=start, end=end)
    return addon_schemas.AddonReportResponse(addons=report)


def _copy_button(label: str, value: str, *, small: bool = True) -> str:
    size_class = " small" if small else ""
    return (
        """
        <button type="button" class="btn secondary{size}" data-copy="{value}" onclick="navigator.clipboard.writeText(this.dataset.copy)">{icon}<span>{label}</span></button>
        """
        .replace("{size}", size_class)
        .format(
            label=html.escape(label),
            value=html.escape(value, quote=True),
            icon=_icon("copy"),
        )
    )


def _build_query(params: dict[str, str | int | None]) -> str:
    filtered = {k: v for k, v in params.items() if v not in {None, ""}}
    return urlencode(filtered, doseq=True)


@router.post(
    "/v1/admin/invoices/{invoice_id}/send",
    response_model=invoice_schemas.InvoiceSendResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_invoice(
    invoice_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_csrf),
    _admin: AdminIdentity = Depends(require_permission_keys("invoices.edit")),
) -> invoice_schemas.InvoiceSendResponse:
    org_id = entitlements.resolve_org_id(http_request)
    invoice = await _get_org_invoice(
        session,
        invoice_id,
        org_id,
        options=(selectinload(Invoice.items), selectinload(Invoice.payments)),
    )
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    lead = await invoice_service.fetch_customer(session, invoice)
    if lead is None or not lead.email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invoice missing customer email")

    token = await invoice_service.upsert_public_token(session, invoice, mark_sent=True)
    base_url = settings.public_base_url.rstrip("/") if settings.public_base_url else None
    if base_url:
        public_link = f"{base_url}/i/{token}"
        public_link_pdf = f"{base_url}/i/{token}.pdf"
    else:
        public_link = str(http_request.url_for("public_invoice_view", token=token))
        public_link_pdf = str(http_request.url_for("public_invoice_pdf", token=token))

    adapter = _email_adapter(http_request)
    if adapter is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Email adapter unavailable")

    subject = f"Invoice {invoice.invoice_number}"
    body = (
        f"Hi {lead.name},\n\n"
        f"Here's your invoice ({invoice.invoice_number}).\n"
        f"View online: {public_link}\n"
        f"Download PDF: {public_link_pdf}\n"
        f"Total due: {_format_money(invoice.total_cents, invoice.currency)}\n\n"
        "If you have questions, reply to this email."
    )
    try:
        delivered = await adapter.send_email(recipient=lead.email, subject=subject, body=body)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "invoice_email_failed",
            extra={"extra": {"invoice_id": invoice.invoice_id, "reason": type(exc).__name__}},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Email send failed") from exc

    if not delivered:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Email send failed")

    if invoice.status == invoice_statuses.INVOICE_STATUS_DRAFT:
        invoice.status = invoice_statuses.INVOICE_STATUS_SENT

    await session.commit()
    refreshed = await session.get(
        Invoice,
        invoice.invoice_id,
        options=(selectinload(Invoice.items), selectinload(Invoice.payments)),
    )
    assert refreshed is not None
    await session.refresh(refreshed)
    invoice_response = invoice_schemas.InvoiceResponse(
        **invoice_service.build_invoice_response(refreshed)
    )
    return invoice_schemas.InvoiceSendResponse(
        invoice=invoice_response,
        public_link=public_link,
        email_sent=bool(delivered),
    )


@router.post(
    "/v1/admin/orders/{order_id}/invoice",
    response_model=invoice_schemas.InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice_from_order(
    order_id: str,
    http_request: Request,
    request: invoice_schemas.InvoiceCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_csrf),
    admin: AdminIdentity = Depends(require_permission_keys("invoices.edit")),
) -> invoice_schemas.InvoiceResponse:
    org_id = entitlements.resolve_org_id(http_request)
    order = await session.get(
        Booking, order_id, options=(selectinload(Booking.lead),)
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    addon_items = await addon_service.addon_invoice_items_for_order(session, order_id)
    base_items = list(request.items)
    all_items = [*base_items, *addon_items]

    expected_subtotal = reason_service.estimate_subtotal_from_lead(order.lead)
    requested_subtotal = sum(item.qty * item.unit_price_cents for item in base_items)
    if (
        expected_subtotal is not None
        and requested_subtotal != expected_subtotal
        and not await reason_service.has_reason(
            session, order_id, kind=reason_schemas.ReasonKind.PRICE_ADJUST
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PRICE_ADJUST reason required for invoice change",
        )

    try:
        invoice = await invoice_service.create_invoice_from_order(
            session=session,
            order=order,
            items=all_items,
            issue_date=request.issue_date,
            due_date=request.due_date,
            currency=request.currency,
            notes=request.notes,
            created_by=admin.username or admin.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.commit()
    result = await session.execute(
        select(Invoice)
        .options(selectinload(Invoice.items), selectinload(Invoice.payments))
        .where(Invoice.invoice_id == invoice.invoice_id)
    )
    fresh_invoice = result.scalar_one()
    return _invoice_response(fresh_invoice)


@router.post(
    "/v1/admin/invoices/{invoice_id}/mark-paid",
    response_model=invoice_schemas.ManualPaymentResult,
    status_code=status.HTTP_201_CREATED,
)
async def mark_invoice_paid(
    invoice_id: str,
    request: invoice_schemas.ManualPaymentRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_csrf),
    admin: AdminIdentity = Depends(require_permission_keys("payments.record")),
) -> invoice_schemas.ManualPaymentResult:
    org_id = entitlements.resolve_org_id(http_request)
    return await _record_manual_invoice_payment(invoice_id, request, session, org_id, admin)


@router.post(
    "/v1/admin/invoices/{invoice_id}/record-payment",
    response_model=invoice_schemas.ManualPaymentResult,
    status_code=status.HTTP_201_CREATED,
)
async def record_manual_invoice_payment(
    invoice_id: str,
    request: invoice_schemas.ManualPaymentRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_csrf),
    admin: AdminIdentity = Depends(require_permission_keys("payments.record")),
) -> invoice_schemas.ManualPaymentResult:
    org_id = entitlements.resolve_org_id(http_request)
    idempotency = None
    if http_request.headers.get("Idempotency-Key"):
        idempotency = await require_idempotency(http_request, session, org_id, "record_payment")
        if isinstance(idempotency, Response):
            return idempotency
        if idempotency.existing_response:
            return idempotency.existing_response
    result = await _record_manual_invoice_payment(invoice_id, request, session, org_id, admin)
    if idempotency:
        await idempotency.save_response(
            session,
            status_code=status.HTTP_201_CREATED,
            body=result.model_dump(mode="json"),
        )
    await session.commit()
    return result


async def _record_manual_invoice_payment(
    invoice_id: str,
    request: invoice_schemas.ManualPaymentRequest,
    session: AsyncSession,
    org_id: uuid.UUID,
    admin_identity: AdminIdentity | None = None,
) -> invoice_schemas.ManualPaymentResult:
    invoice = await _get_org_invoice(
        session,
        invoice_id,
        org_id,
        options=(selectinload(Invoice.items), selectinload(Invoice.payments)),
    )
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    before_snapshot = {
        "status": invoice.status,
        "payments": [payment.payment_id for payment in invoice.payments],
    }

    try:
        payment = await invoice_service.record_manual_payment(
            session=session,
            invoice=invoice,
            amount_cents=request.amount_cents,
            method=request.method,
            reference=request.reference,
            received_at=request.received_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.commit()
    await session.refresh(payment)
    refreshed_invoice = await session.get(
        Invoice,
        invoice_id,
        options=(selectinload(Invoice.items), selectinload(Invoice.payments)),
    )
    assert refreshed_invoice is not None
    await session.refresh(refreshed_invoice)
    payment_data = invoice_schemas.PaymentResponse(
        payment_id=payment.payment_id,
        provider=payment.provider,
        provider_ref=payment.provider_ref,
        method=payment.method,
        amount_cents=payment.amount_cents,
        currency=payment.currency,
        status=payment.status,
        received_at=payment.received_at,
        reference=payment.reference,
        created_at=payment.created_at,
    )
    response_body = invoice_schemas.ManualPaymentResult(
        invoice=_invoice_response(refreshed_invoice),
        payment=payment_data,
    )
    if admin_identity:
        await audit_service.record_action(
            session,
            identity=admin_identity,
            action="invoice_record_payment",
            resource_type="invoice",
            resource_id=invoice_id,
            before=before_snapshot,
            after=response_body.model_dump(mode="json"),
        )
    return response_body


@router.post(
    "/v1/admin/invoices/{invoice_id}/remind",
    response_model=invoice_schemas.InvoiceReminderResponse,
    status_code=status.HTTP_200_OK,
)
async def send_invoice_reminder(
    invoice_id: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_csrf),
    _admin: AdminIdentity = Depends(require_permission_keys("invoices.send")),
) -> invoice_schemas.InvoiceReminderResponse:
    """Send a reminder email for a single invoice."""
    org_id = entitlements.resolve_org_id(http_request)

    invoice = await _get_org_invoice(
        session,
        invoice_id,
        org_id,
        options=(
            selectinload(Invoice.items),
            selectinload(Invoice.payments),
            selectinload(Invoice.email_events),
        ),
    )
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    # Don't send reminders for void or paid invoices
    if invoice.status in {invoice_statuses.INVOICE_STATUS_VOID, invoice_statuses.INVOICE_STATUS_PAID}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot send reminder for {invoice.status} invoice",
        )

    lead = await invoice_service.fetch_customer(session, invoice)
    if lead is None or not lead.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invoice missing customer email"
        )

    adapter = _email_adapter(http_request)
    if adapter is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Email adapter unavailable")

    # Generate or get existing token
    token = await invoice_service.upsert_public_token(session, invoice, mark_sent=True)
    base_url = settings.public_base_url.rstrip("/") if settings.public_base_url else None
    if base_url:
        public_link = f"{base_url}/i/{token}"
        public_link_pdf = f"{base_url}/i/{token}.pdf"
    else:
        public_link = str(http_request.url_for("public_invoice_view", token=token))
        public_link_pdf = str(http_request.url_for("public_invoice_pdf", token=token))

    # Send reminder email
    subject = f"Reminder: Invoice {invoice.invoice_number}"
    balance = max(
        invoice.total_cents
        - sum(p.amount_cents for p in invoice.payments if p.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED),
        0,
    )
    body = (
        f"Hi {lead.name},\n\n"
        f"This is a reminder about invoice {invoice.invoice_number}.\n"
        f"View online: {public_link}\n"
        f"Download PDF: {public_link_pdf}\n"
        f"Balance due: {_format_money(balance, invoice.currency)}\n\n"
        "If you have questions or already paid, please reply to this email."
    )

    try:
        delivered = await adapter.send_email(recipient=lead.email, subject=subject, body=body)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "invoice_reminder_failed",
            extra={"extra": {"invoice_id": invoice_id, "reason": type(exc).__name__}},
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Email send failed") from exc

    if not delivered:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Email send failed")

    # Update invoice status if it was draft
    if invoice.status == invoice_statuses.INVOICE_STATUS_DRAFT:
        invoice.status = invoice_statuses.INVOICE_STATUS_SENT

    await session.commit()

    # Refresh invoice to get updated email_events
    refreshed = await session.get(
        Invoice,
        invoice_id,
        options=(
            selectinload(Invoice.items),
            selectinload(Invoice.payments),
            selectinload(Invoice.email_events),
        ),
    )
    assert refreshed is not None
    await session.refresh(refreshed)

    # Get customer and booking for detailed response
    customer = await invoice_service.fetch_customer(session, refreshed)
    booking = None
    if refreshed.order_id:
        booking_result = await session.execute(select(Booking).where(Booking.booking_id == refreshed.order_id))
        booking = booking_result.scalar_one_or_none()

    data = invoice_service.build_invoice_detail_response(
        refreshed, public_link=public_link, customer=customer, booking=booking
    )
    invoice_response = invoice_schemas.InvoiceResponse(**data)

    return invoice_schemas.InvoiceReminderResponse(
        invoice=invoice_response, email_sent=True, recipient=lead.email
    )


@router.post(
    "/v1/admin/invoices/bulk/remind",
    response_model=invoice_schemas.BulkRemindResult,
    status_code=status.HTTP_200_OK,
)
async def bulk_remind_invoices(
    request: invoice_schemas.BulkRemindRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_csrf),
    _admin: AdminIdentity = Depends(require_permission_keys("invoices.send")),
) -> invoice_schemas.BulkRemindResult:
    """Send email reminders for multiple invoices."""
    org_id = entitlements.resolve_org_id(http_request)
    succeeded: list[str] = []
    failed: list[dict] = []

    adapter = _email_adapter(http_request)
    if adapter is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Email adapter unavailable")

    for invoice_id in request.invoice_ids:
        try:
            invoice = await _get_org_invoice(
                session,
                invoice_id,
                org_id,
                options=(selectinload(Invoice.items), selectinload(Invoice.payments)),
            )
            if invoice is None:
                failed.append({"invoice_id": invoice_id, "error": "Invoice not found"})
                continue

            # Don't send reminders for void or paid invoices
            if invoice.status in {invoice_statuses.INVOICE_STATUS_VOID, invoice_statuses.INVOICE_STATUS_PAID}:
                failed.append({"invoice_id": invoice_id, "error": f"Cannot send reminder for {invoice.status} invoice"})
                continue

            lead = await invoice_service.fetch_customer(session, invoice)
            if lead is None or not lead.email:
                failed.append({"invoice_id": invoice_id, "error": "Invoice missing customer email"})
                continue

            # Generate or get existing token
            token = await invoice_service.upsert_public_token(session, invoice, mark_sent=True)
            base_url = settings.public_base_url.rstrip("/") if settings.public_base_url else None
            if base_url:
                public_link = f"{base_url}/i/{token}"
                public_link_pdf = f"{base_url}/i/{token}.pdf"
            else:
                public_link = str(http_request.url_for("public_invoice_view", token=token))
                public_link_pdf = str(http_request.url_for("public_invoice_pdf", token=token))

            # Send reminder email
            subject = f"Reminder: Invoice {invoice.invoice_number}"
            balance = max(invoice.total_cents - sum(p.amount_cents for p in invoice.payments if p.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED), 0)
            body = (
                f"Hi {lead.name},\n\n"
                f"This is a reminder about invoice {invoice.invoice_number}.\n"
                f"View online: {public_link}\n"
                f"Download PDF: {public_link_pdf}\n"
                f"Balance due: {_format_money(balance, invoice.currency)}\n\n"
                "If you have questions or already paid, please reply to this email."
            )
            try:
                delivered = await adapter.send_email(recipient=lead.email, subject=subject, body=body)
                if delivered:
                    if invoice.status == invoice_statuses.INVOICE_STATUS_DRAFT:
                        invoice.status = invoice_statuses.INVOICE_STATUS_SENT
                    succeeded.append(invoice_id)
                else:
                    failed.append({"invoice_id": invoice_id, "error": "Email delivery failed"})
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "bulk_remind_email_failed",
                    extra={"extra": {"invoice_id": invoice_id, "reason": type(exc).__name__}},
                )
                failed.append({"invoice_id": invoice_id, "error": "Email send error"})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "bulk_remind_invoice_failed",
                extra={"extra": {"invoice_id": invoice_id, "reason": type(exc).__name__}},
            )
            failed.append({"invoice_id": invoice_id, "error": str(exc)})

    await session.commit()
    return invoice_schemas.BulkRemindResult(succeeded=succeeded, failed=failed)


@router.post(
    "/v1/admin/invoices/bulk/mark_paid",
    response_model=invoice_schemas.BulkMarkPaidResult,
    status_code=status.HTTP_200_OK,
)
async def bulk_mark_paid_invoices(
    request: invoice_schemas.BulkMarkPaidRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_csrf),
    _admin: AdminIdentity = Depends(require_permission_keys("payments.record")),
) -> invoice_schemas.BulkMarkPaidResult:
    """Mark multiple invoices as paid with manual payments."""
    org_id = entitlements.resolve_org_id(http_request)
    succeeded: list[str] = []
    failed: list[dict] = []

    for invoice_id in request.invoice_ids:
        try:
            invoice = await _get_org_invoice(
                session,
                invoice_id,
                org_id,
                options=(selectinload(Invoice.items), selectinload(Invoice.payments)),
            )
            if invoice is None:
                failed.append({"invoice_id": invoice_id, "error": "Invoice not found"})
                continue

            normalized_status = invoice.status.strip().upper() if invoice.status else ""

            # Don't allow marking void invoices as paid
            if normalized_status == invoice_statuses.INVOICE_STATUS_VOID:
                failed.append({"invoice_id": invoice_id, "error": "Cannot mark void invoice as paid"})
                continue

            # Skip if already paid
            if normalized_status == invoice_statuses.INVOICE_STATUS_PAID:
                failed.append({"invoice_id": invoice_id, "error": "Invoice already paid"})
                continue

            # Calculate remaining balance by querying database directly for accuracy
            paid_result = await session.scalar(
                select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                    Payment.invoice_id == invoice.invoice_id,
                    Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                )
            )
            paid_cents = int(paid_result or 0)
            balance_due = max(invoice.total_cents - paid_cents, 0)

            # Skip if already paid
            if (
                paid_cents >= invoice.total_cents
                or balance_due == 0
                or invoice_service.outstanding_balance_cents(invoice) == 0
            ):
                failed.append({"invoice_id": invoice_id, "error": "Invoice already paid"})
                continue

            # Record manual payment for the remaining balance
            try:
                payment = await invoice_service.record_manual_payment(
                    session=session,
                    invoice=invoice,
                    amount_cents=balance_due,
                    method=request.method,
                    reference=request.note,
                    received_at=datetime.now(tz=timezone.utc),
                )
                succeeded.append(invoice_id)
            except ValueError as exc:
                failed.append({"invoice_id": invoice_id, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "bulk_mark_paid_invoice_failed",
                extra={"extra": {"invoice_id": invoice_id, "reason": type(exc).__name__}},
            )
            failed.append({"invoice_id": invoice_id, "error": str(exc)})

    await session.commit()
    return invoice_schemas.BulkMarkPaidResult(succeeded=succeeded, failed=failed)


@router.get("/api/admin/tickets", response_model=nps_schemas.TicketListResponse)
async def list_support_tickets(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    order_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_admin),
) -> nps_schemas.TicketListResponse:
    org_id = entitlements.resolve_org_id(request)
    try:
        tickets = await nps_service.list_tickets(
            session,
            org_id=org_id,
            status_filter=status_filter,
            priority_filter=priority,
            order_id=order_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return nps_schemas.TicketListResponse(tickets=[_ticket_response(ticket) for ticket in tickets])


@router.patch("/api/admin/tickets/{ticket_id}", response_model=nps_schemas.TicketResponse)
async def update_support_ticket(
    ticket_id: str,
    payload: nps_schemas.TicketUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_admin),
) -> nps_schemas.TicketResponse:
    org_id = entitlements.resolve_org_id(request)
    try:
        ticket = await nps_service.update_ticket_status(
            session, ticket_id, payload.status, org_id=org_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    await session.commit()
    await session.refresh(ticket)
    return _ticket_response(ticket)


def _render_team_form(
    lang: str | None,
    csrf_input: str,
    *,
    team: Team | None = None,
    action: str,
    submit_label: str,
) -> str:
    name = "" if team is None else team.name
    return f"""
    <div class=\"card\">
      <div class=\"card-row\">
        <div>
          <div class=\"title with-icon\">{_icon('users')}{html.escape(tr(lang, 'admin.teams.title'))}</div>
          <div class=\"muted\">{html.escape(tr(lang, 'admin.teams.subtitle'))}</div>
        </div>
      </div>
      <form class=\"stack\" method=\"post\" action=\"{action}\">
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.teams.name'))}</label>
          <input class=\"input\" type=\"text\" name=\"name\" required value=\"{html.escape(name)}\" />
        </div>
        {csrf_input}
        <button class=\"btn\" type=\"submit\">{html.escape(submit_label)}</button>
      </form>
    </div>
    """


def _team_counts_subqueries(org_id: uuid.UUID) -> tuple[sa.ScalarSelect, sa.ScalarSelect]:
    workers_count = (
        select(func.count())
        .select_from(Worker)
        .where(Worker.team_id == Team.team_id, Worker.org_id == org_id)
        .correlate(Team)
        .scalar_subquery()
    )
    bookings_count = (
        select(func.count())
        .select_from(Booking)
        .where(Booking.team_id == Team.team_id, Booking.org_id == org_id)
        .correlate(Team)
        .scalar_subquery()
    )
    return workers_count, bookings_count


def _render_team_edit_page(
    team: Team,
    *,
    workers_count: int,
    bookings_count: int,
    teams: list[Team],
    lang: str | None,
    csrf_input: str,
    message: str | None = None,
) -> str:
    message_html = ""
    if message:
        message_html = f"""
        <div class="card">
          <div class="card-row">
            <div class="muted">{html.escape(message)}</div>
          </div>
        </div>
        """

    archive_action = (
        f"/v1/admin/ui/teams/{team.team_id}/unarchive"
        if team.archived_at
        else f"/v1/admin/ui/teams/{team.team_id}/archive"
    )
    archive_label = tr(lang, "admin.teams.unarchive" if team.archived_at else "admin.teams.archive")
    archive_hint = tr(lang, "admin.teams.unarchive_hint" if team.archived_at else "admin.teams.archive_hint")
    archive_section = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.teams.archive_title"))}</div>
          <div class="muted">{html.escape(archive_hint)}</div>
        </div>
      </div>
      <form class="stack" method="post" action="{archive_action}">
        {csrf_input}
        <button class="btn danger" type="submit">{html.escape(archive_label)}</button>
      </form>
    </div>
    """

    delete_section = f"""
    <div class="card" id="delete">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.teams.delete_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.teams.delete_hint"))}</div>
        </div>
        <div class="actions">
          <a class="btn danger" href="/v1/admin/ui/teams/{team.team_id}/delete">
            {html.escape(tr(lang, "admin.teams.delete_action"))}
          </a>
        </div>
      </div>
      <div class="muted small">{html.escape(tr(lang, "admin.teams.delete_confirm_hint"))}</div>
    </div>
    """

    details = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, 'admin.teams.details_title'))}</div>
          <div class="muted">{html.escape(tr(lang, 'admin.teams.details_workers'))}: {workers_count}</div>
          <div class="muted">{html.escape(tr(lang, 'admin.teams.details_bookings'))}: {bookings_count}</div>
        </div>
      </div>
    </div>
    """
    return "".join(
        [
            message_html,
            _render_team_form(
                lang,
                csrf_input,
                team=team,
                action=f"/v1/admin/ui/teams/{team.team_id}/update",
                submit_label=tr(lang, "admin.teams.save"),
            ),
            details,
            archive_section,
            delete_section,
        ]
    )


def _render_team_delete_confirm_page(
    team: Team,
    *,
    workers_count: int,
    bookings_count: int,
    teams: list[Team],
    lang: str | None,
    csrf_input: str,
    message: str | None = None,
) -> str:
    message_html = ""
    if message:
        message_html = f"""
        <div class="card">
          <div class="card-row">
            <div class="muted">{html.escape(message)}</div>
          </div>
        </div>
        """

    details = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.teams.delete_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.teams.delete_description"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.teams.details_workers"))}: {workers_count}</div>
          <div class="muted">{html.escape(tr(lang, "admin.teams.details_bookings"))}: {bookings_count}</div>
        </div>
      </div>
    </div>
    """

    confirm_input = """
      <div class="form-group">
        <label>{label}</label>
        <input class="input" type="text" name="confirm" placeholder="DELETE" required />
      </div>
    """.format(label=html.escape(tr(lang, "admin.teams.delete_confirm_label")))

    delete_forms: list[str] = []
    if workers_count == 0 and bookings_count == 0:
        delete_forms.append(
            f"""
            <div class="card">
              <div class="card-row">
                <div>
                  <div class="title">{html.escape(tr(lang, "admin.teams.delete_empty_title"))}</div>
                  <div class="muted">{html.escape(tr(lang, "admin.teams.delete_empty_hint"))}</div>
                </div>
              </div>
              <form class="stack" method="post" action="/v1/admin/ui/teams/{team.team_id}/delete">
                <input type="hidden" name="strategy" value="delete" />
                {confirm_input}
                {csrf_input}
                <button class="btn danger" type="submit">{html.escape(tr(lang, "admin.teams.delete_action"))}</button>
              </form>
            </div>
            """
        )
    else:
        target_options = "".join(
            f'<option value="{candidate.team_id}">{html.escape(candidate.name)}</option>'
            for candidate in teams
            if candidate.team_id != team.team_id and candidate.archived_at is None
        )
        if target_options:
            delete_forms.append(
                f"""
                <div class="card">
                  <div class="card-row">
                    <div>
                      <div class="title">{html.escape(tr(lang, "admin.teams.reassign_title"))}</div>
                      <div class="muted">{html.escape(tr(lang, "admin.teams.reassign_hint"))}</div>
                    </div>
                  </div>
                  <form class="stack" method="post" action="/v1/admin/ui/teams/{team.team_id}/delete">
                    <input type="hidden" name="strategy" value="reassign" />
                    <div class="form-group">
                      <label>{html.escape(tr(lang, "admin.teams.reassign_target"))}</label>
                      <select class="input" name="target_team_id" required>{target_options}</select>
                    </div>
                    {confirm_input}
                    {csrf_input}
                    <button class="btn danger" type="submit">{html.escape(tr(lang, "admin.teams.reassign_action"))}</button>
                  </form>
                </div>
                """
            )
        else:
            delete_forms.append(
                f"""
                <div class="card">
                  <div class="card-row">
                    <div>
                      <div class="title">{html.escape(tr(lang, "admin.teams.reassign_title"))}</div>
                      <div class="muted">{html.escape(tr(lang, "admin.teams.reassign_missing"))}</div>
                    </div>
                  </div>
                </div>
                """
            )
        delete_forms.append(
            f"""
            <div class="card">
              <div class="card-row">
                <div>
                  <div class="title">{html.escape(tr(lang, "admin.teams.cascade_title"))}</div>
                  <div class="muted">{html.escape(tr(lang, "admin.teams.cascade_hint"))}</div>
                </div>
              </div>
              <form class="stack" method="post" action="/v1/admin/ui/teams/{team.team_id}/delete">
                <input type="hidden" name="strategy" value="cascade" />
                {confirm_input}
                {csrf_input}
                <button class="btn danger" type="submit">{html.escape(tr(lang, "admin.teams.cascade_action"))}</button>
              </form>
            </div>
            """
        )

    return "".join([message_html, details, *delete_forms])


@router.get("/v1/admin/teams", response_model=list[booking_schemas.TeamResponse])
async def list_teams(
    request: Request,
    include_archived: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> list[Team]:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    filters = [Team.org_id == org_id]
    if not include_archived:
        filters.append(Team.archived_at.is_(None))
    result = await session.execute(select(Team).where(*filters).order_by(Team.name))
    return result.scalars().all()


@router.post("/v1/admin/teams", response_model=booking_schemas.TeamResponse)
async def create_team(
    request: Request,
    payload: booking_schemas.TeamCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Team:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team name is required")

    existing = await session.scalar(
        select(Team.team_id).where(Team.org_id == org_id, func.lower(Team.name) == name.lower())
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team name already exists")

    team = Team(org_id=org_id, name=name)
    session.add(team)
    await session.flush()
    await audit_service.record_action(
        session,
        identity=identity,
        action="CREATE_TEAM",
        resource_type="team",
        resource_id=str(team.team_id),
        before=None,
        after={"name": team.name},
    )
    await session.commit()
    await session.refresh(team)
    return team


@router.get("/v1/admin/ui/teams", response_class=HTMLResponse)
async def admin_teams_list(
    request: Request,
    show: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    workers_count, bookings_count = _team_counts_subqueries(org_id)
    show_value = show or ""
    filters = [Team.org_id == org_id]
    if show_value == "archived":
        filters.append(Team.archived_at.is_not(None))
    else:
        filters.append(Team.archived_at.is_(None))
    team_rows = (
        await session.execute(
            select(Team, workers_count.label("workers_count"), bookings_count.label("bookings_count"))
            .where(*filters)
            .order_by(Team.name)
        )
    ).all()
    csrf_token = get_csrf_token(request)
    csrf_input = render_csrf_input(csrf_token)
    rows = "".join(
        """
        <tr>
          <td>{name}</td>
          <td class='muted'>{created}</td>
          <td>{workers_count}</td>
          <td>{bookings_count}</td>
          <td>
            <div class="actions">
              <a class="btn secondary small" href="/v1/admin/ui/teams/{team_id}/edit">{edit_label}</a>
              <form method="post" action="{archive_action}">
                {csrf_input}
                <button class="btn secondary small" type="submit">{archive_label}</button>
              </form>
              <a class="btn danger small" href="/v1/admin/ui/teams/{team_id}/delete">{delete_label}</a>
            </div>
          </td>
        </tr>
        """.format(
            name=html.escape(team.name),
            created=html.escape(_format_dt(team.created_at)),
            workers_count=workers_count_value or 0,
            bookings_count=bookings_count_value or 0,
            team_id=team.team_id,
            edit_label=html.escape(tr(lang, "admin.teams.edit")),
            delete_label=html.escape(tr(lang, "admin.teams.delete_action")),
            archive_action=(
                f"/v1/admin/ui/teams/{team.team_id}/unarchive"
                if team.archived_at
                else f"/v1/admin/ui/teams/{team.team_id}/archive"
            ),
            archive_label=html.escape(
                tr(lang, "admin.teams.unarchive" if team.archived_at else "admin.teams.archive")
            ),
            csrf_input=csrf_input,
        )
        for team, workers_count_value, bookings_count_value in team_rows
    )
    table = (
        f"<table class='table'><thead><tr><th>{html.escape(tr(lang, 'admin.teams.name'))}</th><th>{html.escape(tr(lang, 'admin.teams.created_at'))}</th><th>{html.escape(tr(lang, 'admin.teams.workers_count'))}</th><th>{html.escape(tr(lang, 'admin.teams.bookings_count'))}</th><th>{html.escape(tr(lang, 'admin.teams.actions'))}</th></tr></thead><tbody>{rows}</tbody></table>"
        if team_rows
        else _render_empty(tr(lang, "admin.teams.none"))
    )
    filter_form = f"""
    <form class="filters" method="get">
      <div class="form-group">
        <label>{html.escape(tr(lang, "admin.teams.status_label"))}</label>
        <select class="input" name="show">
          <option value="" {"selected" if show_value == "" else ""}>{html.escape(tr(lang, "admin.teams.status_active"))}</option>
          <option value="archived" {"selected" if show_value == "archived" else ""}>{html.escape(tr(lang, "admin.teams.status_archived"))}</option>
        </select>
      </div>
      <div class="form-group">
        <label>&nbsp;</label>
        <div class="actions">
          <button class="btn" type="submit">Apply</button>
        </div>
      </div>
    </form>
    """
    content = "".join(
        [
            "<div class='card'>",
            "<div class='card-row'>",
            f"<div><div class='title with-icon'>{_icon('users')}{html.escape(tr(lang, 'admin.teams.title'))}</div>",
            f"<div class='muted'>{html.escape(tr(lang, 'admin.teams.subtitle'))}</div></div>",
            "<div class='actions'>",
            f"<a class='btn' href='/v1/admin/ui/teams/new'>{_icon('plus')}{html.escape(tr(lang, 'admin.teams.create'))}</a>",
            "</div>",
            "</div>",
            filter_form,
            table,
            "</div>",
        ]
    )
    response = HTMLResponse(_wrap_page(request, content, title="Admin — Teams", active="teams", page_lang=lang))
    issue_csrf_token(request, response, csrf_token)
    return response


@router.get("/v1/admin/ui/teams/new", response_class=HTMLResponse)
async def admin_teams_new_form(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    csrf_token = get_csrf_token(request)
    response = HTMLResponse(
        _wrap_page(
            request,
            _render_team_form(
                lang,
                render_csrf_input(csrf_token),
                action="/v1/admin/ui/teams/create",
                submit_label=tr(lang, "admin.teams.create"),
            ),
            title="Admin — Teams",
            active="teams",
            page_lang=lang,
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/teams/create", response_class=HTMLResponse)
async def admin_teams_create(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team name is required")
    existing = await session.scalar(
        select(Team.team_id).where(Team.org_id == org_id, func.lower(Team.name) == name.lower())
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team name already exists")
    team = Team(org_id=org_id, name=name)
    session.add(team)
    await session.flush()
    await audit_service.record_action(
        session,
        identity=identity,
        action="CREATE_TEAM",
        resource_type="team",
        resource_id=str(team.team_id),
        before=None,
        after={"name": team.name},
    )
    await session.commit()
    return RedirectResponse("/v1/admin/ui/teams", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/v1/admin/ui/teams/{team_id}/edit", response_class=HTMLResponse)
async def admin_teams_edit_form(
    team_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    workers_count, bookings_count = _team_counts_subqueries(org_id)
    row = (
        await session.execute(
            select(
                Team,
                workers_count.label("workers_count"),
                bookings_count.label("bookings_count"),
            ).where(Team.team_id == team_id, Team.org_id == org_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    team, workers_count_value, bookings_count_value = row
    teams = (
        await session.execute(
            select(Team)
            .where(
                Team.org_id == org_id,
                or_(Team.archived_at.is_(None), Team.team_id == team.team_id),
            )
            .order_by(Team.name)
        )
    ).scalars().all()
    csrf_token = get_csrf_token(request)
    content = _render_team_edit_page(
        team,
        workers_count=workers_count_value or 0,
        bookings_count=bookings_count_value or 0,
        teams=teams,
        lang=lang,
        csrf_input=render_csrf_input(csrf_token),
    )
    response = HTMLResponse(_wrap_page(request, content, title="Admin — Teams", active="teams", page_lang=lang))
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/teams/{team_id}/update", response_class=HTMLResponse)
async def admin_teams_update(
    team_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team name is required")
    team = (
        await session.execute(
            select(Team).where(Team.team_id == team_id, Team.org_id == org_id)
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    existing = await session.scalar(
        select(Team.team_id).where(
            Team.org_id == org_id,
            func.lower(Team.name) == name.lower(),
            Team.team_id != team_id,
        )
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team name already exists")
    before = {"name": team.name}
    team.name = name
    await audit_service.record_action(
        session,
        identity=identity,
        action="UPDATE_TEAM",
        resource_type="team",
        resource_id=str(team.team_id),
        before=before,
        after={"name": team.name},
    )
    await session.commit()
    return RedirectResponse("/v1/admin/ui/teams", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/teams/{team_id}/archive", response_class=HTMLResponse)
async def admin_teams_archive(
    team_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    team = (
        await session.execute(
            select(Team).where(Team.team_id == team_id, Team.org_id == org_id)
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    before = {"archived_at": team.archived_at.isoformat() if team.archived_at else None}
    team.archived_at = datetime.now(timezone.utc)
    await audit_service.record_action(
        session,
        identity=identity,
        action="ARCHIVE_TEAM",
        resource_type="team",
        resource_id=str(team.team_id),
        before=before,
        after={"archived_at": team.archived_at.isoformat()},
    )
    await session.commit()
    return RedirectResponse("/v1/admin/ui/teams", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/teams/{team_id}/unarchive", response_class=HTMLResponse)
async def admin_teams_unarchive(
    team_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    team = (
        await session.execute(
            select(Team).where(Team.team_id == team_id, Team.org_id == org_id)
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    before = {"archived_at": team.archived_at.isoformat() if team.archived_at else None}
    team.archived_at = None
    await audit_service.record_action(
        session,
        identity=identity,
        action="UNARCHIVE_TEAM",
        resource_type="team",
        resource_id=str(team.team_id),
        before=before,
        after={"archived_at": None},
    )
    await session.commit()
    return RedirectResponse("/v1/admin/ui/teams", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/v1/admin/ui/teams/{team_id}/delete", response_class=HTMLResponse)
async def admin_teams_delete_confirm(
    team_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    workers_count, bookings_count = _team_counts_subqueries(org_id)
    row = (
        await session.execute(
            select(
                Team,
                workers_count.label("workers_count"),
                bookings_count.label("bookings_count"),
            ).where(Team.team_id == team_id, Team.org_id == org_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    team, workers_count_value, bookings_count_value = row
    teams = (
        await session.execute(
            select(Team)
            .where(
                Team.org_id == org_id,
                or_(Team.archived_at.is_(None), Team.team_id == team.team_id),
            )
            .order_by(Team.name)
        )
    ).scalars().all()
    csrf_token = get_csrf_token(request)
    content = _render_team_delete_confirm_page(
        team,
        workers_count=workers_count_value or 0,
        bookings_count=bookings_count_value or 0,
        teams=teams,
        lang=lang,
        csrf_input=render_csrf_input(csrf_token),
    )
    response = HTMLResponse(
        _wrap_page(request, content, title="Admin — Teams", active="teams", page_lang=lang)
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/teams/{team_id}/delete", response_class=HTMLResponse)
async def admin_teams_delete(
    team_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    strategy = (form.get("strategy") or "").strip()
    confirmation = (form.get("confirm") or "").strip().upper()
    if confirmation != "DELETE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deletion confirmation required")
    workers_count, bookings_count = _team_counts_subqueries(org_id)
    row = (
        await session.execute(
            select(
                Team,
                workers_count.label("workers_count"),
                bookings_count.label("bookings_count"),
            ).where(Team.team_id == team_id, Team.org_id == org_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    team, workers_count_value, bookings_count_value = row
    workers_count_value = workers_count_value or 0
    bookings_count_value = bookings_count_value or 0
    if strategy == "delete":
        if workers_count_value > 0 or bookings_count_value > 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team not empty")
    elif strategy == "reassign":
        target_team_id_raw = form.get("target_team_id")
        if not target_team_id_raw:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target team is required")
        target_team_id = int(target_team_id_raw)
        if target_team_id == team_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target team must be different")
        target_team = (
            await session.execute(
                select(Team).where(Team.team_id == target_team_id, Team.org_id == org_id)
            )
        ).scalar_one_or_none()
        if target_team is None or target_team.archived_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target team not found")
        await session.execute(
            sa.update(Worker)
            .where(Worker.team_id == team_id, Worker.org_id == org_id)
            .values(team_id=target_team_id)
        )
        await session.execute(
            sa.update(Booking)
            .where(Booking.team_id == team_id, Booking.org_id == org_id)
            .values(team_id=target_team_id)
        )
        before = {"team_id": team.team_id, "name": team.name, "target_team_id": target_team_id}
        await audit_service.record_action(
            session,
            identity=identity,
            action="REASSIGN_DELETE_TEAM",
            resource_type="team",
            resource_id=str(team.team_id),
            before=before,
            after={"deleted": True},
        )
    elif strategy == "cascade":
        booking_ids = (
            await session.execute(
                select(Booking.booking_id).where(Booking.team_id == team_id, Booking.org_id == org_id)
            )
        ).scalars().all()
        for booking_id in booking_ids:
            await hard_delete_booking(session, booking_id)
        worker_ids = (
            await session.execute(
                select(Worker.worker_id).where(Worker.team_id == team_id, Worker.org_id == org_id)
            )
        ).scalars().all()
        if worker_ids:
            await session.execute(
                sa.delete(BookingWorker).where(BookingWorker.worker_id.in_(worker_ids))
            )
            await session.execute(
                sa.update(Booking)
                .where(Booking.assigned_worker_id.in_(worker_ids), Booking.org_id == org_id)
                .values(assigned_worker_id=None)
            )
        await session.execute(
            sa.delete(Worker).where(Worker.team_id == team_id, Worker.org_id == org_id)
        )
        before = {"team_id": team.team_id, "name": team.name}
        await audit_service.record_action(
            session,
            identity=identity,
            action="CASCADE_DELETE_TEAM",
            resource_type="team",
            resource_id=str(team.team_id),
            before=before,
            after={"deleted": True},
        )
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deletion strategy required")

    await session.execute(sa.delete(TeamWorkingHours).where(TeamWorkingHours.team_id == team_id))
    await session.execute(sa.delete(TeamBlackout).where(TeamBlackout.team_id == team_id))

    before = {"name": team.name}
    await audit_service.record_action(
        session,
        identity=identity,
        action="DELETE_TEAM",
        resource_type="team",
        resource_id=str(team.team_id),
        before=before,
        after=None,
    )
    await session.delete(team)
    await session.commit()
    return RedirectResponse("/v1/admin/ui/teams", status_code=status.HTTP_303_SEE_OTHER)


def _worker_availability_indicator(
    worker: Worker,
    busy_until: datetime | None,
    lang: str | None,
) -> str:
    if worker.archived_at:
        label = tr(lang, "admin.workers.status_archived")
        return f"🔴 {html.escape(label)}"
    if not worker.is_active:
        label = tr(lang, "admin.workers.status_inactive")
        return f"🔴 {html.escape(label)}"
    if busy_until:
        return f"🟡 {html.escape(tr(lang, 'admin.workers.busy_now'))}"
    return f"🟢 {html.escape(tr(lang, 'admin.workers.free_now'))}"


_DANGEROUS_CSV_PREFIXES = ("=", "+", "-", "@", "\t")


def _safe_csv_value(value: object) -> str:
    text = "" if value is None else str(value)
    if not text:
        return ""
    if text.startswith(_DANGEROUS_CSV_PREFIXES):
        return f"'{text}"
    return text


def _resolve_worker_filters(
    *,
    status: str | None,
    show: str | None,
    availability: str | None,
    skill: list[str] | None,
) -> tuple[str, str, list[str]]:
    status_value = status or ("archived" if show == "archived" else "active")
    if status_value not in {"active", "archived", "all"}:
        status_value = "active"
    availability_value = availability or "all"
    if availability_value not in {"free", "busy", "all"}:
        availability_value = "all"
    selected_skills = [entry.strip() for entry in (skill or []) if entry and entry.strip()]
    return status_value, availability_value, selected_skills


def _resolve_worker_active_state(
    active_state: str | None, active_only: bool, status: str | None
) -> str:
    if active_only:
        return "active"
    if active_state in {"active", "inactive", "all"}:
        return active_state
    if status in {"archived", "all"}:
        return "all"
    return "active"


def _normalize_skill_filters(skill: list[str] | None) -> list[str]:
    return [entry.strip() for entry in (skill or []) if entry and entry.strip()]


def _worker_skill_filters(skills: list[str]) -> list[sa.ColumnElement[bool]]:
    filters: list[sa.ColumnElement[bool]] = []
    for skill in skills:
        normalized = skill.strip().lower()
        if not normalized:
            continue
        pattern = f'%"{normalized}"%'
        filters.append(func.lower(sa.cast(Worker.skills, sa.String)).like(pattern))
    return filters


_ALERT_SEVERITIES = {"low", "medium", "high"}


def _normalize_alert_severities(severities: list[str] | None) -> list[str]:
    return [entry for entry in (severities or []) if entry in _ALERT_SEVERITIES]


def _coerce_alert_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _coerce_alert_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _resolve_worker_alert_config(
    worker: Worker,
    overrides: dict[str, dict[str, object]],
) -> dict[str, float | int]:
    config: dict[str, float | int] = {
        "inactive_days": settings.worker_alert_inactive_days,
        "rating_drop_threshold": settings.worker_alert_rating_drop_threshold,
        "rating_drop_window": settings.worker_alert_rating_drop_review_window,
    }
    for skill in worker.skills or []:
        normalized = str(skill).strip().lower()
        if not normalized:
            continue
        override = overrides.get(normalized)
        if not override:
            continue
        inactive_days = _coerce_alert_int(override.get("inactive_days"))
        if inactive_days is not None:
            config["inactive_days"] = min(int(config["inactive_days"]), inactive_days)
        rating_drop_threshold = _coerce_alert_float(override.get("rating_drop_threshold"))
        if rating_drop_threshold is not None:
            config["rating_drop_threshold"] = min(
                float(config["rating_drop_threshold"]), rating_drop_threshold
            )
        rating_drop_window = _coerce_alert_int(override.get("rating_drop_window"))
        if rating_drop_window is not None:
            config["rating_drop_window"] = min(int(config["rating_drop_window"]), rating_drop_window)
    return config


def _alert_severity_badge(severity: str) -> str:
    normalized = severity if severity in _ALERT_SEVERITIES else "low"
    return (
        f'<span class="badge badge-{html.escape(normalized)}">'
        f"{html.escape(normalized.title())}"
        "</span>"
    )


AVAILABILITY_HEAVY_THRESHOLD_MINUTES = 240


def _parse_availability_start_date(week: str | None, start: str | None) -> date:
    if start:
        try:
            return date.fromisoformat(start)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid start date") from exc
    if week:
        match = re.match(r"^(?P<year>\d{4})-W(?P<week>\d{2})$", week)
        if not match:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid week format")
        year = int(match.group("year"))
        week_num = int(match.group("week"))
        try:
            return date.fromisocalendar(year, week_num, 1)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid week value") from exc
    today = datetime.now(timezone.utc).date()
    return today - timedelta(days=today.weekday())


def _availability_level(minutes: int) -> str:
    if minutes <= 0:
        return "free"
    if minutes > AVAILABILITY_HEAVY_THRESHOLD_MINUTES:
        return "heavy"
    return "light"


def _availability_week_value(start_date: date) -> str:
    iso_year, iso_week, _ = start_date.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _build_workers_export_query(
    *,
    q: str | None,
    active_only: bool,
    active_state: str | None,
    team_id: int | None,
    status: str | None,
    rating_min: float | None,
    rating_max: float | None,
    availability: str | None,
    skills: list[str],
    has_expiring_certs: bool = False,
) -> str:
    params: dict[str, str | list[str]] = {}
    if q:
        params["q"] = q
    if active_only:
        params["active_only"] = "1"
    elif active_state and active_state != "active":
        params["active_state"] = active_state
    if team_id:
        params["team_id"] = str(team_id)
    if status:
        params["status"] = status
    if rating_min is not None:
        params["rating_min"] = str(rating_min)
    if rating_max is not None:
        params["rating_max"] = str(rating_max)
    if availability and availability != "all":
        params["availability"] = availability
    if skills:
        params["skill"] = skills
    if has_expiring_certs:
        params["has_expiring_certs"] = "1"
    return urlencode(params, doseq=True)


def _workers_csv_response(workers: list[Worker], filename: str) -> Response:
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    headers = [
        "worker_id",
        "name",
        "phone",
        "email",
        "role",
        "team_id",
        "team_name",
        "is_active",
        "archived_at",
        "rating_avg",
        "rating_count",
        "skills",
        "created_at",
    ]
    writer.writerow(headers)
    for worker in workers:
        row_values = [
            worker.worker_id,
            worker.name,
            worker.phone,
            worker.email or "",
            worker.role or "",
            worker.team_id,
            getattr(worker.team, "name", "") if worker.team else "",
            worker.is_active,
            worker.archived_at.isoformat() if worker.archived_at else "",
            worker.rating_avg if worker.rating_avg is not None else "",
            worker.rating_count,
            ", ".join(worker.skills or []),
            worker.created_at.isoformat() if worker.created_at else "",
        ]
        writer.writerow([_safe_csv_value(value) for value in row_values])
    csv_content = csv_buffer.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _parse_worker_ids(form: dict) -> list[int]:
    raw_ids = []
    if hasattr(form, "getlist"):
        raw_ids = form.getlist("worker_ids") or form.getlist("worker_ids[]")
    if not raw_ids:
        raw_ids = [form.get("worker_ids"), form.get("worker_ids[]")]
    worker_ids: list[int] = []
    for raw_id in raw_ids:
        if raw_id in (None, ""):
            continue
        try:
            worker_ids.append(int(raw_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid worker id") from exc
    return list(dict.fromkeys(worker_ids))


def _normalize_worker_skills(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    parts = [part.strip() for part in raw.replace("\n", ",").split(",")]
    skills = [part for part in parts if part]
    return skills or None


def _render_worker_form(worker: Worker | None, teams: list[Team], lang: str | None, csrf_input: str) -> str:
    team_options = "".join(
        f'<option value="{team.team_id}" {"selected" if worker and worker.team_id == team.team_id else ""}>{html.escape(team.name)}</option>'
        for team in teams
    )
    hourly_rate = getattr(worker, "hourly_rate_cents", None)
    skills_value = ", ".join(worker.skills or []) if worker else ""
    rating_value = "" if worker is None or worker.rating_avg is None else f"{worker.rating_avg:.1f}"

    # Pre-compute password hint to avoid f-string backslash issue
    password_hint = '' if worker is None else f'<div class="muted">{html.escape(tr(lang, "admin.workers.password_hint"))}</div>'

    return f"""
    <div class=\"card\">
      <div class=\"card-row\">
        <div>
          <div class=\"title with-icon\">{_icon('users')}{html.escape(tr(lang, 'admin.workers.title'))}</div>
          <div class=\"muted\">{html.escape(tr(lang, 'admin.workers.subtitle'))}</div>
        </div>
      </div>
      <form class=\"stack\" method=\"post\">
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.workers.name'))}</label>
          <input class=\"input\" type=\"text\" name=\"name\" required value=\"{html.escape(getattr(worker, 'name', '') or '')}\" />
        </div>
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.workers.phone'))}</label>
          <input class=\"input\" type=\"text\" name=\"phone\" required value=\"{html.escape(getattr(worker, 'phone', '') or '')}\" />
        </div>
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.workers.password'))}</label>
          <input class=\"input\" type=\"password\" name=\"password\" minlength=\"8\" placeholder=\"{html.escape(tr(lang, 'admin.workers.password_placeholder'))}\" {'required' if worker is None else ''} />
          {password_hint}
        </div>
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.workers.email'))}</label>
          <input class=\"input\" type=\"email\" name=\"email\" value=\"{html.escape(getattr(worker, 'email', '') or '')}\" />
        </div>
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.workers.role'))}</label>
          <input class=\"input\" type=\"text\" name=\"role\" value=\"{html.escape(getattr(worker, 'role', '') or '')}\" />
        </div>
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.workers.hourly_rate'))}</label>
          <input class=\"input\" type=\"number\" name=\"hourly_rate_cents\" min=\"0\" step=\"50\" value=\"{'' if hourly_rate is None else hourly_rate}\" />
        </div>
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.workers.skills'))}</label>
          <input class=\"input\" type=\"text\" name=\"skills\" value=\"{html.escape(skills_value)}\" />
          <div class=\"muted\">Comma-separated skills (e.g., deep clean, windows).</div>
        </div>
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.workers.rating'))}</label>
          <input class=\"input\" type=\"number\" name=\"rating_avg\" min=\"0\" max=\"5\" step=\"0.1\" value=\"{html.escape(rating_value)}\" />
        </div>
        <div class=\"form-group\">
          <label>{html.escape(tr(lang, 'admin.workers.team'))}</label>
          <select class=\"input\" name=\"team_id\" required>{team_options}</select>
        </div>
        <div class=\"actions\">
          <label class=\"with-icon\"><input type=\"checkbox\" name=\"is_active\" {'' if worker and not worker.is_active else 'checked'} /> {html.escape(tr(lang, 'admin.workers.is_active'))}</label>
        </div>
        {csrf_input}
        <button class=\"btn\" type=\"submit\">{html.escape(tr(lang, 'admin.workers.save'))}</button>
      </form>
    </div>
    """


def _render_worker_delete_confirm_page(
    worker: Worker,
    *,
    crew_assignments_count: int,
    bookings_primary_count: int,
    lang: str | None,
    csrf_input: str,
    message: str | None = None,
) -> str:
    message_html = ""
    if message:
        message_html = f"""
        <div class="card">
          <div class="card-row">
            <div class="muted">{html.escape(message)}</div>
          </div>
        </div>
        """

    details = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.workers.delete_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.workers.delete_description"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.workers.delete_primary_count"))}: {bookings_primary_count}</div>
          <div class="muted">{html.escape(tr(lang, "admin.workers.delete_crew_count"))}: {crew_assignments_count}</div>
        </div>
      </div>
    </div>
    """
    confirm_input = """
      <div class="form-group">
        <label>{label}</label>
        <input class="input" type="text" name="confirm" placeholder="DELETE" required />
      </div>
    """.format(label=html.escape(tr(lang, "admin.workers.delete_confirm_label")))

    detach_form = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.workers.delete_detach_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.workers.delete_detach_hint"))}</div>
        </div>
      </div>
      <form class="stack" method="post" action="/v1/admin/ui/workers/{worker.worker_id}/delete">
        <input type="hidden" name="strategy" value="detach" />
        {confirm_input}
        {csrf_input}
        <button class="btn danger" type="submit">{html.escape(tr(lang, "admin.workers.delete_detach_action"))}</button>
      </form>
    </div>
    """
    cascade_form = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.workers.delete_cascade_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.workers.delete_cascade_hint"))}</div>
        </div>
      </div>
      <form class="stack" method="post" action="/v1/admin/ui/workers/{worker.worker_id}/delete">
        <input type="hidden" name="strategy" value="cascade" />
        {confirm_input}
        {csrf_input}
        <button class="btn danger" type="submit">{html.escape(tr(lang, "admin.workers.delete_cascade_action"))}</button>
      </form>
    </div>
    """
    return "".join([message_html, details, detach_form, cascade_form])


async def _list_workers(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    q: str | None,
    active_only: bool,
    active_state: str | None,
    team_id: int | None,
    status: str | None,
    rating_min: float | None,
    rating_max: float | None,
    skills: list[str],
    has_expiring_certs: bool = False,
    worker_ids: list[int] | None = None,
) -> list[Worker]:
    filters = [Worker.org_id == org_id]
    if status == "archived":
        filters.append(or_(Worker.archived_at.is_not(None), Worker.is_active.is_(False)))
    elif status == "active":
        filters.append(Worker.archived_at.is_(None))
        filters.append(Worker.is_active.is_(True))
    active_state_value = _resolve_worker_active_state(active_state, active_only, status)
    if active_state_value == "active":
        filters.append(Worker.is_active.is_(True))
    elif active_state_value == "inactive":
        filters.append(Worker.is_active.is_(False))
    if team_id:
        filters.append(Worker.team_id == team_id)
    if q:
        pattern = f"%{q.lower()}%"
        filters.append(
            or_(
                func.lower(Worker.name).like(pattern),
                func.lower(Worker.phone).like(pattern),
                func.lower(Worker.email).like(pattern),
            )
        )
    if rating_min is not None or rating_max is not None:
        filters.append(Worker.rating_avg.is_not(None))
    if rating_min is not None:
        filters.append(Worker.rating_avg >= rating_min)
    if rating_max is not None:
        filters.append(Worker.rating_avg <= rating_max)
    filters.extend(_worker_skill_filters(skills))
    if worker_ids:
        filters.append(Worker.worker_id.in_(worker_ids))
    if has_expiring_certs:
        today = datetime.now(timezone.utc).date()
        cutoff = today + timedelta(days=_CERT_EXPIRY_WARNING_DAYS)
        expiring_subquery = (
            select(WorkerCertificate.worker_id)
            .where(
                WorkerCertificate.org_id == org_id,
                WorkerCertificate.archived_at.is_(None),
                WorkerCertificate.expires_at.is_not(None),
                WorkerCertificate.expires_at <= cutoff,
            )
            .distinct()
            .subquery()
        )
        filters.append(Worker.worker_id.in_(select(expiring_subquery.c.worker_id)))
    stmt = select(Worker).where(*filters).options(selectinload(Worker.team)).order_by(Worker.created_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


async def _worker_busy_until_map(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_ids: list[int],
) -> dict[int, datetime]:
    if not worker_ids:
        return {}
    now = datetime.now(timezone.utc)
    stmt = (
        select(
            Booking.assigned_worker_id,
            Booking.starts_at,
            Booking.duration_minutes,
            BookingWorker.worker_id.label("crew_worker_id"),
        )
        .outerjoin(BookingWorker, BookingWorker.booking_id == Booking.booking_id)
        .where(
            Booking.org_id == org_id,
            Booking.status.in_(booking_service.BLOCKING_STATUSES),
            Booking.starts_at <= now,
            or_(
                Booking.assigned_worker_id.in_(worker_ids),
                BookingWorker.worker_id.in_(worker_ids),
            ),
        )
    )
    rows = (await session.execute(stmt)).all()
    busy_until_map: dict[int, datetime] = {}
    for assigned_worker_id, starts_at, duration_minutes, crew_worker_id in rows:
        if starts_at is None or duration_minutes is None:
            continue
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        ends_at = starts_at + timedelta(minutes=duration_minutes)
        if now >= ends_at:
            continue
        for worker_id in (assigned_worker_id, crew_worker_id):
            if worker_id is None:
                continue
            current = busy_until_map.get(worker_id)
            if current is None or ends_at > current:
                busy_until_map[worker_id] = ends_at
    return busy_until_map


_DASHBOARD_DATE_RANGES = {"last7": 7, "last30": 30}
_DASHBOARD_NEWBIE_DAYS = 14
_DASHBOARD_NEWBIE_COMPLETED_MAX = 1
_DASHBOARD_CANCELLATION_RATE_THRESHOLD = 0.3
_DASHBOARD_CANCELLATION_COUNT_THRESHOLD = 2
_DASHBOARD_CANCELLATION_MIN_TOTAL = 3


def _resolve_dashboard_range(preset: str | None) -> tuple[str, timedelta]:
    if preset not in _DASHBOARD_DATE_RANGES:
        preset = "last7"
    return preset, timedelta(days=_DASHBOARD_DATE_RANGES[preset])


def _booking_worker_assignments_subquery() -> sa.Subquery:
    assigned_stmt = select(
        Booking.booking_id.label("booking_id"),
        Booking.assigned_worker_id.label("worker_id"),
    ).where(Booking.assigned_worker_id.is_not(None))
    crew_stmt = select(
        BookingWorker.booking_id.label("booking_id"),
        BookingWorker.worker_id.label("worker_id"),
    )
    assignment_union = assigned_stmt.union_all(crew_stmt).subquery()
    return (
        select(assignment_union.c.booking_id, assignment_union.c.worker_id)
        .distinct()
        .subquery()
    )


def _workers_list_url(*, worker_ids: list[int], skills: list[str]) -> str:
    params: dict[str, list[str] | list[int]] = {}
    if worker_ids:
        params["worker_id"] = worker_ids
    if skills:
        params["skill"] = skills
    query = urlencode(params, doseq=True)
    if not query:
        return "/v1/admin/ui/workers"
    return f"/v1/admin/ui/workers?{query}"


def _render_worker_table(
    *,
    headers: list[str],
    rows: list[str],
    empty_label: str,
) -> str:
    if not rows:
        rows = [f"<tr><td colspan=\"{len(headers)}\" class=\"muted\">{html.escape(empty_label)}</td></tr>"]
    header_html = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    return f"""
    <table class="table">
      <thead><tr>{header_html}</tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


@router.get("/v1/admin/ui/workers/dashboard", response_class=HTMLResponse)
async def admin_workers_dashboard(
    request: Request,
    skill: list[str] | None = Query(default=None),
    date_range: str | None = Query(default=None, alias="date_range"),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = _resolve_admin_org(request, identity)
    selected_skills = _normalize_skill_filters(skill)
    range_value, range_delta = _resolve_dashboard_range(date_range)
    now = datetime.now(timezone.utc)
    range_start = now - range_delta
    assignment_subquery = _booking_worker_assignments_subquery()

    worker_skill_filters = _worker_skill_filters(selected_skills)
    base_worker_filters = [
        Worker.org_id == org_id,
        Worker.archived_at.is_(None),
        *worker_skill_filters,
    ]

    skill_rows = (
        await session.execute(select(Worker.skills).where(Worker.org_id == org_id))
    ).scalars().all()
    all_skills = sorted(
        {
            skill_entry
            for skill_list in skill_rows
            if skill_list
            for skill_entry in skill_list
            if isinstance(skill_entry, str) and skill_entry
        }
    )
    skill_options = sorted(set(all_skills).union(selected_skills))
    skill_filter_options = "".join(
        f'<option value="{html.escape(skill_option)}" {"selected" if skill_option in selected_skills else ""}>{html.escape(skill_option)}</option>'
        for skill_option in skill_options
    )

    top_rated_stmt = (
        select(Worker)
        .where(*base_worker_filters, Worker.rating_avg.is_not(None))
        .order_by(sa.desc(Worker.rating_avg).nullslast(), sa.desc(Worker.rating_count))
        .limit(5)
    )
    top_rated = (await session.execute(top_rated_stmt)).scalars().all()

    busiest_stmt = (
        select(
            Worker.worker_id,
            Worker.name,
            func.coalesce(func.sum(Booking.duration_minutes), 0).label("minutes"),
            func.count(sa.distinct(Booking.booking_id)).label("booking_count"),
        )
        .select_from(assignment_subquery)
        .join(Booking, Booking.booking_id == assignment_subquery.c.booking_id)
        .join(Worker, Worker.worker_id == assignment_subquery.c.worker_id)
        .where(
            Booking.org_id == org_id,
            Booking.starts_at >= range_start,
            Booking.starts_at <= now,
            Booking.status.in_({"CONFIRMED", "DONE"}),
            Worker.archived_at.is_(None),
            *worker_skill_filters,
        )
        .group_by(Worker.worker_id)
        .order_by(sa.desc("minutes"))
        .limit(5)
    )
    busiest_rows = (await session.execute(busiest_stmt)).all()

    completed_count_expr = func.coalesce(
        func.sum(sa.case((Booking.status == "DONE", 1), else_=0)),
        0,
    )
    newbie_cutoff = now - timedelta(days=_DASHBOARD_NEWBIE_DAYS)
    newbie_stmt = (
        select(
            Worker.worker_id,
            Worker.name,
            Worker.created_at,
            completed_count_expr.label("completed_count"),
        )
        .select_from(Worker)
        .outerjoin(assignment_subquery, assignment_subquery.c.worker_id == Worker.worker_id)
        .outerjoin(
            Booking,
            sa.and_(
                Booking.booking_id == assignment_subquery.c.booking_id,
                Booking.org_id == org_id,
            ),
        )
        .where(*base_worker_filters, Worker.created_at >= newbie_cutoff)
        .group_by(Worker.worker_id)
        .having(completed_count_expr <= _DASHBOARD_NEWBIE_COMPLETED_MAX)
        .order_by(Worker.created_at.desc())
        .limit(5)
    )
    newbie_rows = (await session.execute(newbie_stmt)).all()

    total_count_expr = func.coalesce(
        func.sum(
            sa.case((Booking.status.in_({"DONE", "CANCELLED", "CONFIRMED"}), 1), else_=0)
        ),
        0,
    )
    cancellation_count_expr = func.coalesce(
        func.sum(sa.case((Booking.status == "CANCELLED", 1), else_=0)),
        0,
    )
    cancellation_rate_expr = sa.cast(cancellation_count_expr, sa.Float) / func.nullif(total_count_expr, 0)
    problematic_stmt = (
        select(
            Worker.worker_id,
            Worker.name,
            cancellation_count_expr.label("cancellations"),
            total_count_expr.label("total"),
            cancellation_rate_expr.label("rate"),
        )
        .select_from(Worker)
        .outerjoin(assignment_subquery, assignment_subquery.c.worker_id == Worker.worker_id)
        .outerjoin(
            Booking,
            sa.and_(
                Booking.booking_id == assignment_subquery.c.booking_id,
                Booking.org_id == org_id,
                Booking.starts_at >= range_start,
                Booking.starts_at <= now,
            ),
        )
        .where(*base_worker_filters)
        .group_by(Worker.worker_id)
        .having(
            or_(
                cancellation_count_expr >= _DASHBOARD_CANCELLATION_COUNT_THRESHOLD,
                sa.and_(
                    total_count_expr >= _DASHBOARD_CANCELLATION_MIN_TOTAL,
                    cancellation_rate_expr >= _DASHBOARD_CANCELLATION_RATE_THRESHOLD,
                ),
            )
        )
        .order_by(sa.desc(cancellation_count_expr), sa.desc(cancellation_rate_expr))
        .limit(5)
    )
    problematic_rows = (await session.execute(problematic_stmt)).all()

    revenue_stmt = (
        select(
            Worker.worker_id,
            Worker.name,
            func.coalesce(func.sum(Booking.base_charge_cents), 0).label("revenue_cents"),
            func.count(sa.distinct(Booking.booking_id)).label("booking_count"),
        )
        .select_from(assignment_subquery)
        .join(Booking, Booking.booking_id == assignment_subquery.c.booking_id)
        .join(Worker, Worker.worker_id == assignment_subquery.c.worker_id)
        .where(
            Booking.org_id == org_id,
            Booking.starts_at >= range_start,
            Booking.starts_at <= now,
            Booking.status == "DONE",
            Worker.archived_at.is_(None),
            *worker_skill_filters,
        )
        .group_by(Worker.worker_id)
        .order_by(sa.desc("revenue_cents"))
        .limit(5)
    )
    revenue_rows = (await session.execute(revenue_stmt)).all()

    incident_stmt = (
        select(WorkerNote.worker_id, Worker.skills)
        .join(Worker, Worker.worker_id == WorkerNote.worker_id)
        .where(
            WorkerNote.org_id == org_id,
            WorkerNote.note_type == "incident",
            WorkerNote.created_at >= range_start,
            WorkerNote.created_at <= now,
            Worker.archived_at.is_(None),
            *worker_skill_filters,
        )
    )
    incident_rows = (await session.execute(incident_stmt)).all()
    incident_skill_counts: dict[str, int] = {}
    for _worker_id, skills in incident_rows:
        for skill_entry in skills or []:
            if not isinstance(skill_entry, str) or not skill_entry:
                continue
            incident_skill_counts[skill_entry] = incident_skill_counts.get(skill_entry, 0) + 1
    incident_skill_table_rows = [
        """
        <tr>
          <td>{skill}</td>
          <td>{count}</td>
        </tr>
        """.format(
            skill=html.escape(skill),
            count=html.escape(str(count)),
        )
        for skill, count in sorted(
            incident_skill_counts.items(), key=lambda item: (-item[1], item[0])
        )[:5]
    ]

    top_rated_table_rows = [
        """
        <tr>
          <td><a href="/v1/admin/ui/workers/{worker_id}">{name}</a></td>
          <td>{rating}</td>
          <td>{skills}</td>
        </tr>
        """.format(
            worker_id=worker.worker_id,
            name=html.escape(worker.name),
            rating=html.escape(f"{worker.rating_avg:.1f} ({worker.rating_count})"),
            skills=html.escape(", ".join(worker.skills or []) or "-"),
        )
        for worker in top_rated
    ]

    busiest_table_rows = [
        """
        <tr>
          <td><a href="/v1/admin/ui/workers/{worker_id}">{name}</a></td>
          <td>{minutes}</td>
          <td>{count}</td>
        </tr>
        """.format(
            worker_id=row.worker_id,
            name=html.escape(row.name),
            minutes=html.escape(str(row.minutes)),
            count=html.escape(str(row.booking_count)),
        )
        for row in busiest_rows
    ]

    newbie_table_rows = [
        """
        <tr>
          <td><a href="/v1/admin/ui/workers/{worker_id}">{name}</a></td>
          <td>{created_at}</td>
          <td>{completed}</td>
        </tr>
        """.format(
            worker_id=row.worker_id,
            name=html.escape(row.name),
            created_at=html.escape(_format_dt(row.created_at)),
            completed=html.escape(str(row.completed_count)),
        )
        for row in newbie_rows
    ]

    problematic_table_rows = [
        """
        <tr>
          <td><a href="/v1/admin/ui/workers/{worker_id}">{name}</a></td>
          <td>{cancellations}</td>
          <td>{total}</td>
          <td>{rate}</td>
        </tr>
        """.format(
            worker_id=row.worker_id,
            name=html.escape(row.name),
            cancellations=html.escape(str(row.cancellations)),
            total=html.escape(str(row.total)),
            rate=html.escape("-" if row.rate is None else f"{row.rate:.0%}"),
        )
        for row in problematic_rows
    ]

    revenue_table_rows = [
        """
        <tr>
          <td><a href="/v1/admin/ui/workers/{worker_id}">{name}</a></td>
          <td class="align-right">{revenue}</td>
          <td>{count}</td>
        </tr>
        """.format(
            worker_id=row.worker_id,
            name=html.escape(row.name),
            revenue=html.escape(_format_money(row.revenue_cents, settings.deposit_currency.upper())),
            count=html.escape(str(row.booking_count)),
        )
        for row in revenue_rows
    ]

    content = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div>",
            "<div class=\"title with-icon\">",
            _icon("users"),
            "Workers dashboard</div>",
            "<div class=\"muted\">Operational segments for staffing, quality, and revenue.</div>",
            "</div>",
            "<div class=\"actions\">",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers\">All workers</a>",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/alerts\">Alerts</a>",
            "</div>",
            "</div>",
            "<form class=\"filters\" method=\"get\">",
            "<div class=\"form-group\"><label>Skills</label>",
            f"<select class=\"input\" name=\"skill\" multiple size=\"3\">{skill_filter_options}</select></div>",
            "<div class=\"form-group\"><label>Date range</label>",
            "<select class=\"input\" name=\"date_range\">"
            f"<option value=\"last7\" {'selected' if range_value == 'last7' else ''}>Last 7 days</option>"
            f"<option value=\"last30\" {'selected' if range_value == 'last30' else ''}>Last 30 days</option>"
            "</select></div>",
            "<div class=\"form-group\"><label>&nbsp;</label><div class=\"actions\">",
            "<button class=\"btn\" type=\"submit\">Apply</button>",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/dashboard\">Reset</a>",
            "</div></div>",
            "</form>",
            "</div>",
            "<div class=\"section\">",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div class=\"title\">Top rated</div>",
            "<div class=\"actions\">",
            f"<a class=\"btn secondary small\" href=\"{html.escape(_workers_list_url(worker_ids=[worker.worker_id for worker in top_rated], skills=selected_skills))}\">View list</a>",
            "</div>",
            "</div>",
            _render_worker_table(
                headers=["Worker", "Rating", "Skills"],
                rows=top_rated_table_rows,
                empty_label="No rated workers found.",
            ),
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div class=\"title\">Busiest ({'Last 7 days' if range_value == 'last7' else 'Last 30 days'})</div>",
            "<div class=\"actions\">",
            f"<a class=\"btn secondary small\" href=\"{html.escape(_workers_list_url(worker_ids=[row.worker_id for row in busiest_rows], skills=selected_skills))}\">View list</a>",
            "</div>",
            "</div>",
            _render_worker_table(
                headers=["Worker", "Minutes booked", "Bookings"],
                rows=busiest_table_rows,
                empty_label="No bookings in range.",
            ),
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div class=\"title\">New workers needing attention (last {_DASHBOARD_NEWBIE_DAYS} days)</div>",
            "<div class=\"actions\">",
            f"<a class=\"btn secondary small\" href=\"{html.escape(_workers_list_url(worker_ids=[row.worker_id for row in newbie_rows], skills=selected_skills))}\">View list</a>",
            "</div>",
            "</div>",
            _render_worker_table(
                headers=["Worker", "Created", "Completed jobs"],
                rows=newbie_table_rows,
                empty_label="No new workers need attention.",
            ),
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div class=\"title\">Problematic (last {range_delta.days} days)</div>",
            "<div class=\"actions\">",
            f"<a class=\"btn secondary small\" href=\"{html.escape(_workers_list_url(worker_ids=[row.worker_id for row in problematic_rows], skills=selected_skills))}\">View list</a>",
            "</div>",
            "</div>",
            _render_worker_table(
                headers=["Worker", "Cancellations", "Total", "Rate"],
                rows=problematic_table_rows,
                empty_label="No problematic workers in range.",
            ),
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div class=\"title\">Top revenue (last {range_delta.days} days)</div>",
            "<div class=\"actions\">",
            f"<a class=\"btn secondary small\" href=\"{html.escape(_workers_list_url(worker_ids=[row.worker_id for row in revenue_rows], skills=selected_skills))}\">View list</a>",
            "</div>",
            "</div>",
            _render_worker_table(
                headers=["Worker", "Revenue", "Bookings"],
                rows=revenue_table_rows,
                empty_label="No revenue in range.",
            ),
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div class=\"title\">Incidents by skill (last {range_delta.days} days)</div>",
            "</div>",
            _render_worker_table(
                headers=["Skill", "Incidents"],
                rows=incident_skill_table_rows,
                empty_label="No incidents recorded.",
            ),
            "</div>",
            "</div>",
        ]
    )
    return HTMLResponse(
        _wrap_page(
            request,
            content,
            title="Workers dashboard",
            active="workers",
        )
    )


@router.get("/v1/admin/ui/workers/alerts", response_class=HTMLResponse)
async def admin_workers_alerts(
    request: Request,
    skill: list[str] | None = Query(default=None),
    severity: list[str] | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = _resolve_admin_org(request, identity)
    selected_skills = _normalize_skill_filters(skill)
    selected_severities = _normalize_alert_severities(severity)
    worker_skill_filters = _worker_skill_filters(selected_skills)

    workers_stmt = (
        select(Worker)
        .where(
            Worker.org_id == org_id,
            Worker.archived_at.is_(None),
            Worker.is_active.is_(True),
            *worker_skill_filters,
        )
        .order_by(Worker.name)
    )
    workers = (await session.execute(workers_stmt)).scalars().all()
    worker_ids = [worker.worker_id for worker in workers]

    skill_rows = (
        await session.execute(select(Worker.skills).where(Worker.org_id == org_id))
    ).scalars().all()
    all_skills = sorted(
        {
            skill_entry
            for skill_list in skill_rows
            if skill_list
            for skill_entry in skill_list
            if isinstance(skill_entry, str) and skill_entry
        }
    )
    skill_options = sorted(set(all_skills).union(selected_skills))
    skill_filter_options = "".join(
        f'<option value="{html.escape(skill_option)}" {"selected" if skill_option in selected_skills else ""}>{html.escape(skill_option)}</option>'
        for skill_option in skill_options
    )
    severity_filter_options = "".join(
        f'<option value="{html.escape(option)}" {"selected" if option in selected_severities else ""}>{html.escape(option.title())}</option>'
        for option in sorted(_ALERT_SEVERITIES)
    )

    now = datetime.now(timezone.utc)
    last_booking_end_by_worker: dict[int, datetime] = {}
    if worker_ids:
        assignment_subquery = _booking_worker_assignments_subquery()
        bookings_stmt = (
            select(
                assignment_subquery.c.worker_id,
                Booking.starts_at,
                Booking.duration_minutes,
            )
            .join(Booking, Booking.booking_id == assignment_subquery.c.booking_id)
            .where(
                Booking.org_id == org_id,
                assignment_subquery.c.worker_id.in_(worker_ids),
                Booking.status.in_({"CONFIRMED", "DONE"}),
            )
        )
        booking_rows = (await session.execute(bookings_stmt)).all()
        for worker_id, starts_at, duration_minutes in booking_rows:
            if starts_at is None or duration_minutes is None:
                continue
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            ends_at = starts_at + timedelta(minutes=duration_minutes)
            current = last_booking_end_by_worker.get(worker_id)
            if current is None or ends_at > current:
                last_booking_end_by_worker[worker_id] = ends_at

    reviews_by_worker: dict[int, list[tuple[int, datetime]]] = {}
    if worker_ids:
        reviews_stmt = (
            select(WorkerReview.worker_id, WorkerReview.rating, WorkerReview.created_at)
            .where(
                WorkerReview.org_id == org_id,
                WorkerReview.worker_id.in_(worker_ids),
            )
            .order_by(WorkerReview.worker_id, WorkerReview.created_at.desc())
        )
        review_rows = (await session.execute(reviews_stmt)).all()
        for worker_id, rating, created_at in review_rows:
            if rating is None or created_at is None:
                continue
            reviews_by_worker.setdefault(worker_id, []).append((rating, created_at))

    overrides = settings.worker_alert_skill_thresholds
    alerts: list[dict[str, object]] = []
    inactive_count = 0
    rating_drop_count = 0
    unread_messages_count = 0

    def include_severity(value: str) -> bool:
        return not selected_severities or value in selected_severities

    for worker in workers:
        config = _resolve_worker_alert_config(worker, overrides)
        inactive_days = int(config["inactive_days"])
        rating_drop_threshold = float(config["rating_drop_threshold"])
        rating_drop_window = int(config["rating_drop_window"])

        last_booking_end = last_booking_end_by_worker.get(worker.worker_id)
        last_activity = last_booking_end or worker.created_at
        if last_activity and last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)
        if last_activity:
            days_inactive = (now - last_activity).days
            if days_inactive >= inactive_days:
                severity_level = "high" if days_inactive >= inactive_days * 2 else "medium"
                if include_severity(severity_level):
                    alerts.append(
                        {
                            "worker": worker,
                            "type": "Inactive worker",
                            "severity": severity_level,
                            "details": (
                                "No bookings yet"
                                if last_booking_end is None
                                else f"Last booking ended {_format_dt(last_booking_end)}"
                            ),
                            "timestamp": last_activity,
                        }
                    )
                    inactive_count += 1

        reviews = reviews_by_worker.get(worker.worker_id, [])
        if rating_drop_window > 0 and len(reviews) >= rating_drop_window * 2:
            recent = reviews[:rating_drop_window]
            previous = reviews[rating_drop_window : rating_drop_window * 2]
            recent_avg = sum(score for score, _ in recent) / rating_drop_window
            prev_avg = sum(score for score, _ in previous) / rating_drop_window
            drop = prev_avg - recent_avg
            if drop >= rating_drop_threshold:
                severity_level = "high" if drop >= rating_drop_threshold * 2 else "medium"
                if include_severity(severity_level):
                    alerts.append(
                        {
                            "worker": worker,
                            "type": "Rating drop",
                            "severity": severity_level,
                            "details": (
                                f"Last {rating_drop_window} avg {recent_avg:.2f} vs "
                                f"prev {prev_avg:.2f} (drop {drop:.2f})"
                            ),
                            "timestamp": recent[0][1],
                        }
                    )
                    rating_drop_count += 1

    alert_rows: list[str] = []
    for alert in alerts:
        worker = alert["worker"]
        skills_display = ", ".join(worker.skills or []) or "-"
        alert_rows.append(
            """
            <tr>
              <td>
                <div class="title"><a href="/v1/admin/ui/workers/{worker_id}">{name}</a></div>
                <div class="muted small">{skills}</div>
              </td>
              <td>{alert_type}</td>
              <td>{severity}</td>
              <td>{details}</td>
              <td class="muted">{timestamp}</td>
            </tr>
            """.format(
                worker_id=worker.worker_id,
                name=html.escape(worker.name),
                skills=html.escape(skills_display),
                alert_type=html.escape(str(alert["type"])),
                severity=_alert_severity_badge(str(alert["severity"])),
                details=html.escape(str(alert["details"])),
                timestamp=html.escape(_format_dt(alert.get("timestamp"))),
            )
        )

    alerts_table = (
        "<table class=\"table\">"
        "<thead><tr>"
        "<th>Worker</th><th>Alert</th><th>Severity</th><th>Details</th><th>Last activity</th>"
        "</tr></thead>"
        f"<tbody>{''.join(alert_rows)}</tbody>"
        "</table>"
        if alert_rows
        else _render_empty("No alerts match the current filters.")
    )

    content = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div>",
            f"<div class=\"title with-icon\">{_icon('warning')}Worker alerts</div>",
            "<div class=\"muted\">Operational alerts for inactivity, rating shifts, and messages.</div>",
            "</div>",
            "<div class=\"actions\">",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers\">All workers</a>",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/dashboard\">Dashboard</a>",
            "</div>",
            "</div>",
            "<form class=\"filters\" method=\"get\">",
            "<div class=\"form-group\"><label>Skills</label>",
            f"<select class=\"input\" name=\"skill\" multiple size=\"3\">{skill_filter_options}</select></div>",
            "<div class=\"form-group\"><label>Severity</label>",
            f"<select class=\"input\" name=\"severity\" multiple size=\"3\">{severity_filter_options}</select></div>",
            "<div class=\"form-group\"><label>&nbsp;</label><div class=\"actions\">",
            "<button class=\"btn\" type=\"submit\">Apply</button>",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/alerts\">Reset</a>",
            "</div></div>",
            "</form>",
            "</div>",
            "<div class=\"card\">",
            "<div class=\"metric-grid\">",
            "<div class=\"metric\">",
            "<div class=\"label\">Inactive workers</div>",
            f"<div class=\"value\">{html.escape(str(inactive_count))}</div>",
            "</div>",
            "<div class=\"metric\">",
            "<div class=\"label\">Rating drop</div>",
            f"<div class=\"value\">{html.escape(str(rating_drop_count))}</div>",
            "</div>",
            "<div class=\"metric\">",
            "<div class=\"label\">Unread messages</div>",
            f"<div class=\"value\">{html.escape(str(unread_messages_count))}</div>",
            "</div>",
            "</div>",
            "<div class=\"muted small\">Unread messages are a placeholder until chat launches.</div>",
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div class=\"title\">Alerts</div>",
            "</div>",
            alerts_table,
            "</div>",
        ]
    )
    return HTMLResponse(
        _wrap_page(
            request,
            content,
            title="Worker alerts",
            active="workers",
            page_lang=lang,
        )
    )


@router.get("/v1/admin/ui/workers", response_class=HTMLResponse)
async def admin_workers_list(
    request: Request,
    q: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    active_state: str | None = Query(default=None),
    team_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    show: str | None = Query(default=None),
    rating_min: float | None = Query(default=None),
    rating_max: float | None = Query(default=None),
    availability: str | None = Query(default=None),
    skill: list[str] | None = Query(default=None),
    worker_id: list[int] | None = Query(default=None),
    has_expiring_certs: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = _resolve_admin_org(request, identity)
    status_value, availability_value, selected_skills = _resolve_worker_filters(
        status=status,
        show=show,
        availability=availability,
        skill=skill,
    )
    if status is None and active_state in {"inactive", "all"}:
        status_value = "all"
    active_state_value = _resolve_worker_active_state(active_state, active_only, status_value)
    workers = await _list_workers(
        session,
        org_id=org_id,
        q=q,
        active_only=active_only,
        active_state=active_state_value,
        team_id=team_id,
        status=status_value,
        rating_min=rating_min,
        rating_max=rating_max,
        skills=selected_skills,
        has_expiring_certs=has_expiring_certs,
        worker_ids=worker_id,
    )
    busy_until_map = await _worker_busy_until_map(
        session,
        org_id=org_id,
        worker_ids=[worker.worker_id for worker in workers],
    )
    if availability_value == "busy":
        workers = [worker for worker in workers if worker.worker_id in busy_until_map]
    elif availability_value == "free":
        workers = [worker for worker in workers if worker.worker_id not in busy_until_map]
    teams = (
        await session.execute(
            select(Team)
            .where(Team.org_id == org_id, Team.archived_at.is_(None))
            .order_by(Team.name)
        )
    ).scalars().all()
    skill_rows = (
        await session.execute(select(Worker.skills).where(Worker.org_id == org_id))
    ).scalars().all()
    all_skills = sorted(
        {
            skill_entry
            for skill_list in skill_rows
            if skill_list
            for skill_entry in skill_list
            if isinstance(skill_entry, str) and skill_entry
        }
    )
    team_filter_options = "".join(
        f'<option value="{team.team_id}" {"selected" if team_id == team.team_id else ""}>{html.escape(team.name)}</option>'
        for team in teams
    )
    skill_options = sorted(set(all_skills).union(selected_skills))
    skill_filter_options = "".join(
        f'<option value="{html.escape(skill_option)}" {"selected" if skill_option in selected_skills else ""}>{html.escape(skill_option)}</option>'
        for skill_option in skill_options
    )
    templates = await message_template_service.list_templates(session, org_id=org_id)
    template_options = "".join(
        f'<option value="{template.template_id}">{html.escape(template.name)}</option>'
        for template in templates
    )
    csrf_token = get_csrf_token(request)
    csrf_input = render_csrf_input(csrf_token)
    export_query = _build_workers_export_query(
        q=q,
        active_only=active_only,
        active_state=active_state_value,
        team_id=team_id,
        status=status_value,
        rating_min=rating_min,
        rating_max=rating_max,
        availability=availability_value,
        skills=selected_skills,
        has_expiring_certs=has_expiring_certs,
    )
    export_filtered_url = "/v1/admin/ui/workers/export?format=csv"
    if export_query:
        export_filtered_url = f"{export_filtered_url}&{export_query}"
    return_to = f"{request.url.path}?{request.url.query}" if request.url.query else request.url.path
    bulk_action = request.query_params.get("bulk_action")
    bulk_updated = request.query_params.get("updated")
    bulk_skipped = request.query_params.get("skipped")
    bulk_note = ""
    if bulk_action:
        action_label = "Archive" if bulk_action == "archive" else "Unarchive"
        updated_label = bulk_updated or "0"
        skipped_label = bulk_skipped or "0"
        bulk_note = (
            "<div class=\"card\">"
            "<div class=\"card-row\">"
            f"<div class=\"note\">{html.escape(action_label)} complete: "
            f"{html.escape(updated_label)} updated, {html.escape(skipped_label)} skipped.</div>"
            "</div>"
            "</div>"
        )
    broadcast_sent = request.query_params.get("broadcast_sent")
    broadcast_skipped = request.query_params.get("broadcast_skipped")
    broadcast_note = ""
    if broadcast_sent is not None:
        sent_label = broadcast_sent or "0"
        skipped_label = broadcast_skipped or "0"
        broadcast_note = (
            "<div class=\"card\">"
            "<div class=\"card-row\">"
            f"<div class=\"note\">Announcement sent: "
            f"{html.escape(sent_label)} delivered, {html.escape(skipped_label)} skipped.</div>"
            "</div>"
            "</div>"
        )
    rows: list[str] = []
    for worker in workers:
        busy_until = busy_until_map.get(worker.worker_id)
        skills_html = (
            " ".join(
                f'<span class="chip">{html.escape(skill_item)}</span>'
                for skill_item in (worker.skills or [])
            )
            or "-"
        )
        if worker.rating_avg is None:
            rating_display = "-"
        else:
            rating_display = f"{worker.rating_avg:.1f} ({worker.rating_count})"
        archive_action = (
            f"/v1/admin/ui/workers/{worker.worker_id}/unarchive"
            if worker.archived_at
            else f"/v1/admin/ui/workers/{worker.worker_id}/archive"
        )
        archive_label = tr(lang, "admin.workers.unarchive" if worker.archived_at else "admin.workers.archive")
        rows.append(
            """
            <tr>
              <td><input type="checkbox" name="worker_ids" value="{worker_id}" data-worker-select /></td>
              <td>
                <div class="title">{name}</div>
                <div class="muted small">{team}</div>
              </td>
              <td>
                <div>{phone}</div>
                <div class="muted small">{email}</div>
              </td>
              <td>{status}</td>
              <td>{skills}</td>
              <td>{rating}</td>
              <td>{busy_until}</td>
              <td>
                <div class="actions">
                  <a class="btn secondary small" href="/v1/admin/ui/workers/{worker_id}">{edit_icon}{edit_label}</a>
                  <form method="post" action="{archive_action}">
                    {csrf_input}
                    <button class="btn secondary small" type="submit">{archive_label}</button>
                  </form>
                  <a class="btn danger small" href="/v1/admin/ui/workers/{worker_id}/delete">{delete_label}</a>
                </div>
              </td>
            </tr>
            """.format(
                name=html.escape(worker.name),
                team=html.escape(getattr(worker.team, "name", tr(lang, "admin.workers.team"))),
                phone=html.escape(worker.phone),
                email=html.escape(worker.email or "-"),
                status=_worker_availability_indicator(worker, busy_until, lang),
                skills=skills_html,
                rating=html.escape(rating_display),
                busy_until=html.escape(_format_dt(busy_until) if busy_until else "-"),
                worker_id=worker.worker_id,
                edit_icon=_icon("edit"),
                edit_label=html.escape(tr(lang, "admin.workers.details")),
                delete_label=html.escape(tr(lang, "admin.workers.delete_permanent")),
                archive_action=archive_action,
                archive_label=html.escape(archive_label),
                csrf_input=csrf_input,
            )
        )
    content = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div><div class=\"title with-icon\">{_icon('users')}{html.escape(tr(lang, 'admin.workers.title'))}</div>",
            f"<div class=\"muted\">{html.escape(tr(lang, 'admin.workers.subtitle'))}</div></div>",
            "<div class=\"actions\">",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/dashboard\">Dashboard</a>",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/availability\">Availability</a>",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/alerts\">Alerts</a>",
            f"<a class=\"btn\" href=\"/v1/admin/ui/workers/new\">{_icon('plus')}{html.escape(tr(lang, 'admin.workers.create'))}</a>",
            "</div></div>",
            "<form class=\"filters\" method=\"get\">",
            f"<div class=\"form-group\"><label>{html.escape(tr(lang, 'admin.workers.search'))}</label><input class=\"input\" type=\"text\" name=\"q\" value=\"{html.escape(q or '')}\" /></div>",
            f"<div class=\"form-group\"><label>{html.escape(tr(lang, 'admin.workers.team'))}</label><select class=\"input\" name=\"team_id\"><option value=\"\"></option>{team_filter_options}</select></div>",
            f"<div class=\"form-group\"><label>{html.escape(tr(lang, 'admin.workers.active_state'))}</label><select class=\"input\" name=\"active_state\">"
            f"<option value=\"active\" {'selected' if active_state_value == 'active' else ''}>{html.escape(tr(lang, 'admin.workers.status_active'))}</option>"
            f"<option value=\"inactive\" {'selected' if active_state_value == 'inactive' else ''}>{html.escape(tr(lang, 'admin.workers.status_inactive'))}</option>"
            f"<option value=\"all\" {'selected' if active_state_value == 'all' else ''}>{html.escape(tr(lang, 'admin.workers.status_all'))}</option>"
            f"</select></div>",
            f"<div class=\"form-group\"><label>{html.escape(tr(lang, 'admin.workers.status_label'))}</label><select class=\"input\" name=\"status\">"
            f"<option value=\"active\" {'selected' if status_value == 'active' else ''}>{html.escape(tr(lang, 'admin.workers.status_active'))}</option>"
            f"<option value=\"archived\" {'selected' if status_value == 'archived' else ''}>{html.escape(tr(lang, 'admin.workers.status_archived'))}</option>"
            f"<option value=\"all\" {'selected' if status_value == 'all' else ''}>{html.escape(tr(lang, 'admin.workers.status_all'))}</option>"
            f"</select></div>",
            f"<div class=\"form-group\"><label>{html.escape(tr(lang, 'admin.workers.availability'))}</label><select class=\"input\" name=\"availability\">"
            f"<option value=\"all\" {'selected' if availability_value == 'all' else ''}>{html.escape(tr(lang, 'admin.workers.availability_all'))}</option>"
            f"<option value=\"free\" {'selected' if availability_value == 'free' else ''}>{html.escape(tr(lang, 'admin.workers.availability_free'))}</option>"
            f"<option value=\"busy\" {'selected' if availability_value == 'busy' else ''}>{html.escape(tr(lang, 'admin.workers.availability_busy'))}</option>"
            f"</select></div>",
            f"<div class=\"form-group\"><label>{html.escape(tr(lang, 'admin.workers.rating_min'))}</label><input class=\"input\" type=\"number\" name=\"rating_min\" min=\"0\" max=\"5\" step=\"0.1\" value=\"{'' if rating_min is None else rating_min}\" /></div>",
            f"<div class=\"form-group\"><label>{html.escape(tr(lang, 'admin.workers.rating_max'))}</label><input class=\"input\" type=\"number\" name=\"rating_max\" min=\"0\" max=\"5\" step=\"0.1\" value=\"{'' if rating_max is None else rating_max}\" /></div>",
            f"<div class=\"form-group\"><label>{html.escape(tr(lang, 'admin.workers.skills'))}</label><select class=\"input\" name=\"skill\" multiple size=\"3\">{skill_filter_options}</select></div>",
            "<div class=\"form-group\">"
            "<label>Expiring certs</label>"
            f"<label class=\"with-icon\"><input type=\"checkbox\" name=\"has_expiring_certs\" value=\"1\" {'checked' if has_expiring_certs else ''} />Within {_CERT_EXPIRY_WARNING_DAYS} days</label>"
            "</div>",
            "<div class=\"form-group\"><label>&nbsp;</label><div class=\"actions\"><button class=\"btn\" type=\"submit\">Apply</button><a class=\"btn secondary\" href=\"/v1/admin/ui/workers\">Reset</a></div></div>",
            "</form>",
            "</div>",
            bulk_note,
            broadcast_note,
            (
                "<form method=\"post\">"
                f"{csrf_input}"
                f"<input type=\"hidden\" name=\"return_to\" value=\"{html.escape(return_to)}\" />"
                "<div class=\"card\">"
                "<div class=\"card-row\">"
                "<div class=\"actions\">"
                "<label class=\"with-icon\"><input type=\"checkbox\" id=\"select-all-workers\" /> Select all on page</label>"
                "<button class=\"btn secondary\" type=\"submit\" formaction=\"/v1/admin/ui/workers/bulk/archive\">Archive selected</button>"
                "<button class=\"btn secondary\" type=\"submit\" formaction=\"/v1/admin/ui/workers/bulk/unarchive\">Unarchive selected</button>"
                "<button class=\"btn secondary\" type=\"submit\" formaction=\"/v1/admin/ui/workers/export_selected\">Export selected CSV</button>"
                f"<a class=\"btn secondary\" href=\"{html.escape(export_filtered_url)}\">Export filtered CSV</a>"
                "<a class=\"btn secondary\" href=\"/v1/admin/ui/message-templates\">Message templates</a>"
                "</div>"
                "</div>"
                "<div class=\"card-row\">"
                "<div class=\"stack\" style=\"flex: 1; min-width: 260px;\">"
                "<div class=\"title\">Team announcement</div>"
                "<div class=\"muted small\">Send a broadcast to selected workers using a template or custom text.</div>"
                "</div>"
                "<div class=\"stack\" style=\"flex: 2; min-width: 260px;\">"
                "<div class=\"form-group\"><label>Template</label>"
                "<select class=\"input\" name=\"template_id\"><option value=\"\">Custom message</option>"
                f"{template_options}</select></div>"
                "<div class=\"form-group\"><label>Message</label>"
                "<textarea class=\"input\" name=\"announcement_body\" rows=\"3\" placeholder=\"Add a short update...\"></textarea></div>"
                "</div>"
                "<div class=\"actions\" style=\"align-self: flex-end;\">"
                "<button class=\"btn\" type=\"submit\" formaction=\"/v1/admin/ui/workers/bulk/announce\">Send announcement</button>"
                "</div>"
                "</div>"
                "</div>"
                "<table class=\"table\">"
                "<thead><tr>"
                "<th>Select</th>"
                f"<th>{html.escape(tr(lang, 'admin.workers.name'))}</th>"
                f"<th>{html.escape(tr(lang, 'admin.workers.phone'))}</th>"
                f"<th>{html.escape(tr(lang, 'admin.workers.status_label'))}</th>"
                f"<th>{html.escape(tr(lang, 'admin.workers.skills'))}</th>"
                f"<th>{html.escape(tr(lang, 'admin.workers.rating'))}</th>"
                f"<th>{html.escape(tr(lang, 'admin.workers.busy_until'))}</th>"
                f"<th>{html.escape(tr(lang, 'admin.workers.actions'))}</th>"
                "</tr></thead><tbody>"
                f"{''.join(rows)}"
                "</tbody></table>"
                "</form>"
                "<script>"
                "const selectAll = document.getElementById('select-all-workers');"
                "if (selectAll) {"
                "selectAll.addEventListener('change', () => {"
                "document.querySelectorAll('input[data-worker-select]').forEach((checkbox) => {"
                "checkbox.checked = selectAll.checked;"
                "});"
                "});"
                "}"
                "</script>"
                if rows
                else _render_empty(tr(lang, "admin.workers.none"))
            ),
        ]
    )
    response = HTMLResponse(_wrap_page(request, content, title="Admin — Workers", active="workers", page_lang=lang))
    issue_csrf_token(request, response, csrf_token)
    return response


@router.get("/v1/admin/ui/message-templates", response_class=HTMLResponse)
async def admin_message_templates_list(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = _resolve_admin_org(request, identity)
    templates = await message_template_service.list_templates(session, org_id=org_id)
    csrf_token = get_csrf_token(request)
    csrf_input = render_csrf_input(csrf_token)

    rows: list[str] = []
    for template in templates:
        preview = template.body if len(template.body) <= 140 else f"{template.body[:137]}..."
        rows.append(
            "".join(
                [
                    "<div class=\"card\">",
                    "<div class=\"card-row\">",
                    f"<div><div class=\"title\">{html.escape(template.name)}</div>",
                    f"<div class=\"muted small\">{html.escape(preview)}</div></div>",
                    "<div class=\"actions\">",
                    f"<a class=\"btn secondary\" href=\"/v1/admin/ui/message-templates/{template.template_id}/edit\">Edit</a>",
                    "<form method=\"post\" action=\"/v1/admin/ui/message-templates/"
                    f"{template.template_id}/delete\">",
                    csrf_input,
                    "<button class=\"btn danger\" type=\"submit\">Delete</button>",
                    "</form>",
                    "</div>",
                    "</div>",
                    "</div>",
                ]
            )
        )

    create_form = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div>",
            "<div class=\"title\">New template</div>",
            "<div class=\"muted small\">Reusable messages for team announcements.</div>",
            "</div>",
            "</div>",
            "<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/message-templates\">",
            csrf_input,
            "<div class=\"form-group\"><label>Name</label>"
            "<input class=\"input\" type=\"text\" name=\"name\" required /></div>",
            "<div class=\"form-group\"><label>Message</label>"
            "<textarea class=\"input\" name=\"body\" rows=\"4\" required></textarea></div>",
            "<div class=\"actions\"><button class=\"btn\" type=\"submit\">Create template</button></div>",
            "</form>",
            "</div>",
        ]
    )

    content = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div>",
            "<div class=\"title with-icon\">",
            _icon("message-circle"),
            "Message templates</div>",
            "<div class=\"muted\">Manage reusable announcements for workers.</div>",
            "</div>",
            "<div class=\"actions\">",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers\">Back to workers</a>",
            "</div>",
            "</div>",
            "</div>",
            create_form,
            "".join(rows) if rows else _render_empty("No templates yet."),
        ]
    )
    response = HTMLResponse(
        _wrap_page(
            request,
            content,
            title="Message templates",
            active="workers",
            page_lang=lang,
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/message-templates", response_class=HTMLResponse)
async def admin_message_templates_create(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    form = await request.form()
    name = str(form.get("name") or "").strip()
    body = str(form.get("body") or "").strip()
    if not name or not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name and body required")
    await message_template_service.create_template(session, org_id=org_id, name=name, body=body)
    await session.commit()
    return RedirectResponse(
        "/v1/admin/ui/message-templates",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/v1/admin/ui/message-templates/{template_id}/edit", response_class=HTMLResponse)
async def admin_message_templates_edit_form(
    request: Request,
    template_id: int,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = _resolve_admin_org(request, identity)
    template = await message_template_service.get_template(
        session, org_id=org_id, template_id=template_id
    )
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    csrf_token = get_csrf_token(request)
    csrf_input = render_csrf_input(csrf_token)

    content = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div>",
            "<div class=\"title\">Edit template</div>",
            f"<div class=\"muted\">{html.escape(template.name)}</div>",
            "</div>",
            "<div class=\"actions\">",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/message-templates\">Back</a>",
            "</div>",
            "</div>",
            "<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/message-templates/"
            f"{template.template_id}\">",
            csrf_input,
            "<div class=\"form-group\"><label>Name</label>"
            f"<input class=\"input\" type=\"text\" name=\"name\" value=\"{html.escape(template.name)}\" required /></div>",
            "<div class=\"form-group\"><label>Message</label>"
            f"<textarea class=\"input\" name=\"body\" rows=\"4\" required>{html.escape(template.body)}</textarea></div>",
            "<div class=\"actions\"><button class=\"btn\" type=\"submit\">Save changes</button></div>",
            "</form>",
            "</div>",
        ]
    )
    response = HTMLResponse(
        _wrap_page(
            request,
            content,
            title="Edit template",
            active="workers",
            page_lang=lang,
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/message-templates/{template_id}", response_class=HTMLResponse)
async def admin_message_templates_update(
    request: Request,
    template_id: int,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    form = await request.form()
    name = str(form.get("name") or "").strip()
    body = str(form.get("body") or "").strip()
    if not name or not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name and body required")
    template = await message_template_service.update_template(
        session, org_id=org_id, template_id=template_id, name=name, body=body
    )
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    await session.commit()
    return RedirectResponse(
        "/v1/admin/ui/message-templates",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/v1/admin/ui/message-templates/{template_id}/delete", response_class=HTMLResponse)
async def admin_message_templates_delete(
    request: Request,
    template_id: int,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    deleted = await message_template_service.delete_template(
        session, org_id=org_id, template_id=template_id
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    await session.commit()
    return RedirectResponse(
        "/v1/admin/ui/message-templates",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/v1/admin/ui/workers/availability", response_class=HTMLResponse)
async def admin_workers_availability(
    request: Request,
    week: str | None = Query(default=None),
    start: str | None = Query(default=None),
    skill: list[str] | None = Query(default=None),
    team_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = _resolve_admin_org(request, identity)
    start_date = _parse_availability_start_date(week, start)
    end_date = start_date + timedelta(days=7)
    days = [start_date + timedelta(days=offset) for offset in range(7)]
    status_value = status if status in {"active", "archived", "all"} else "active"
    selected_skills = _normalize_skill_filters(skill)
    workers = await _list_workers(
        session,
        org_id=org_id,
        q=None,
        active_only=False,
        active_state="all",
        team_id=team_id,
        status=status_value,
        rating_min=None,
        rating_max=None,
        skills=selected_skills,
    )
    workers = sorted(workers, key=lambda worker: worker.name.lower())
    worker_ids = [worker.worker_id for worker in workers]
    availability_map: dict[int, dict[date, int]] = {
        worker_id: {day: 0 for day in days} for worker_id in worker_ids
    }
    if worker_ids:
        assignment_subquery = _booking_worker_assignments_subquery()
        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, time.min, tzinfo=timezone.utc)
        range_start = start_dt - timedelta(days=7)
        bookings_stmt = (
            select(
                assignment_subquery.c.worker_id,
                Booking.booking_id,
                Booking.starts_at,
                Booking.duration_minutes,
            )
            .join(Booking, Booking.booking_id == assignment_subquery.c.booking_id)
            .where(
                Booking.org_id == org_id,
                Booking.status.in_(booking_service.BLOCKING_STATUSES),
                assignment_subquery.c.worker_id.in_(worker_ids),
                Booking.starts_at < end_dt,
                Booking.starts_at >= range_start,
            )
        )
        booking_rows = (await session.execute(bookings_stmt)).all()
        for worker_id, _booking_id, starts_at, duration_minutes in booking_rows:
            if starts_at is None or duration_minutes is None:
                continue
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
            ends_at = starts_at + timedelta(minutes=duration_minutes)
            for day in days:
                day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
                day_end = day_start + timedelta(days=1)
                overlap_start = max(starts_at, day_start)
                overlap_end = min(ends_at, day_end)
                if overlap_end <= overlap_start:
                    continue
                minutes = int((overlap_end - overlap_start).total_seconds() / 60)
                availability_map[worker_id][day] += minutes

    teams = (
        await session.execute(
            select(Team)
            .where(Team.org_id == org_id, Team.archived_at.is_(None))
            .order_by(Team.name)
        )
    ).scalars().all()
    skill_rows = (
        await session.execute(select(Worker.skills).where(Worker.org_id == org_id))
    ).scalars().all()
    all_skills = sorted(
        {
            skill_entry
            for skill_list in skill_rows
            if skill_list
            for skill_entry in skill_list
            if isinstance(skill_entry, str) and skill_entry
        }
    )
    team_filter_options = "".join(
        f'<option value="{team.team_id}" {"selected" if team_id == team.team_id else ""}>{html.escape(team.name)}</option>'
        for team in teams
    )
    skill_options = sorted(set(all_skills).union(selected_skills))
    skill_filter_options = "".join(
        f'<option value="{html.escape(skill_option)}" {"selected" if skill_option in selected_skills else ""}>{html.escape(skill_option)}</option>'
        for skill_option in skill_options
    )
    rows: list[str] = []
    for worker in workers:
        day_cells = []
        for day in days:
            minutes = availability_map.get(worker.worker_id, {}).get(day, 0)
            level = _availability_level(minutes)
            label = "Free" if level == "free" else "Light" if level == "light" else "Heavy"
            dispatch_url = (
                f"/v1/admin/ui/dispatch?date={day.isoformat()}&worker_id={worker.worker_id}"
            )
            day_cells.append(
                """
                <td class="availability-cell {level}">
                  <a href="{dispatch_url}">
                    <div class="minutes">{minutes}m</div>
                    <div class="status">{label}</div>
                  </a>
                </td>
                """.format(
                    level=level,
                    dispatch_url=html.escape(dispatch_url),
                    minutes=html.escape(str(minutes)),
                    label=html.escape(label),
                )
            )
        rows.append(
            """
            <tr>
              <td>
                <div class="title">{name}</div>
                <div class="muted small">{team}</div>
              </td>
              {cells}
            </tr>
            """.format(
                name=html.escape(worker.name),
                team=html.escape(getattr(worker.team, "name", tr(lang, "admin.workers.team"))),
                cells="".join(day_cells),
            )
        )
    header_cells = "".join(
        f"<th>{html.escape(day.strftime('%a %b %d'))}</th>" for day in days
    )
    if rows:
        tbody_html = "".join(rows)
    else:
        tbody_html = (
            f"<tr><td colspan=\"{len(days) + 1}\" class=\"muted\">No workers found.</td></tr>"
        )
    table_html = (
        "<table class=\"table availability-table\">"
        "<thead><tr><th>Worker</th>"
        f"{header_cells}</tr></thead>"
        f"<tbody>{tbody_html}</tbody>"
        "</table>"
    )
    week_value = _availability_week_value(start_date)
    content = "".join(
        [
            "<style>",
            ".availability-table .availability-cell { text-align: center; padding: 0; }",
            ".availability-table .availability-cell a { display: block; padding: 8px; color: inherit; text-decoration: none; }",
            ".availability-table .availability-cell .minutes { font-weight: 600; }",
            ".availability-table .availability-cell .status { font-size: 12px; opacity: 0.8; }",
            ".availability-table .availability-cell.free { background: #ecfdf3; }",
            ".availability-table .availability-cell.light { background: #fff7ed; }",
            ".availability-table .availability-cell.heavy { background: #fef2f2; }",
            ".availability-legend { display: flex; gap: 12px; flex-wrap: wrap; }",
            ".availability-legend .swatch { display: inline-flex; align-items: center; gap: 6px; }",
            ".availability-legend .box { width: 14px; height: 14px; border-radius: 4px; display: inline-block; }",
            "</style>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div><div class=\"title with-icon\">{_icon('calendar')}Availability</div>",
            f"<div class=\"muted\">Week of {html.escape(start_date.isoformat())}</div></div>",
            "<div class=\"actions\">",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers\">All workers</a>",
            "</div></div>",
            "<form class=\"filters\" method=\"get\">",
            "<div class=\"form-group\"><label>Week</label>",
            f"<input class=\"input\" type=\"week\" name=\"week\" value=\"{html.escape(week_value)}\" /></div>",
            "<div class=\"form-group\"><label>Start date</label>",
            f"<input class=\"input\" type=\"date\" name=\"start\" value=\"{html.escape(start_date.isoformat())}\" /></div>",
            "<div class=\"form-group\"><label>Team</label>",
            f"<select class=\"input\" name=\"team_id\"><option value=\"\"></option>{team_filter_options}</select></div>",
            "<div class=\"form-group\"><label>Status</label><select class=\"input\" name=\"status\">",
            f"<option value=\"active\" {'selected' if status_value == 'active' else ''}>Active</option>",
            f"<option value=\"archived\" {'selected' if status_value == 'archived' else ''}>Archived</option>",
            f"<option value=\"all\" {'selected' if status_value == 'all' else ''}>All</option>",
            "</select></div>",
            "<div class=\"form-group\"><label>Skills</label>",
            f"<select class=\"input\" name=\"skill\" multiple size=\"3\">{skill_filter_options}</select></div>",
            "<div class=\"form-group\"><label>&nbsp;</label><div class=\"actions\">",
            "<button class=\"btn\" type=\"submit\">Apply</button>",
            "<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/availability\">Reset</a>",
            "</div></div>",
            "</form>",
            "<div class=\"availability-legend muted\">",
            "<span class=\"swatch\"><span class=\"box\" style=\"background:#ecfdf3\"></span>Free (0m)</span>",
            f"<span class=\"swatch\"><span class=\"box\" style=\"background:#fff7ed\"></span>Light (1–{AVAILABILITY_HEAVY_THRESHOLD_MINUTES}m)</span>",
            f"<span class=\"swatch\"><span class=\"box\" style=\"background:#fef2f2\"></span>Heavy ({AVAILABILITY_HEAVY_THRESHOLD_MINUTES + 1}m+)</span>",
            "</div>",
            "</div>",
            "<div class=\"card\">",
            table_html,
            "</div>",
        ]
    )
    return HTMLResponse(
        _wrap_page(
            request,
            content,
            title="Availability",
            active="workers",
            page_lang=lang,
        )
    )


@router.post("/v1/admin/ui/workers/bulk/archive", response_class=HTMLResponse)
async def admin_workers_bulk_archive(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    form = await request.form()
    worker_ids = _parse_worker_ids(form)
    if not worker_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workers selected")
    workers = (
        await session.execute(
            select(Worker)
            .where(Worker.org_id == org_id, Worker.worker_id.in_(worker_ids))
        )
    ).scalars().all()
    worker_ids_set = {worker.worker_id for worker in workers}
    now = datetime.now(timezone.utc)
    updated = 0
    for worker in workers:
        before = {
            "archived_at": worker.archived_at.isoformat() if worker.archived_at else None,
            "is_active": worker.is_active,
        }
        changed = False
        if worker.archived_at is None:
            worker.archived_at = now
            changed = True
        if worker.is_active:
            worker.is_active = False
            changed = True
            if entitlements.has_tenant_identity(request):
                await billing_service.record_usage_event(
                    session,
                    entitlements.resolve_org_id(request),
                    metric="worker_created",
                    quantity=-1,
                    resource_id=str(worker.worker_id),
                )
        if changed:
            updated += 1
            await audit_service.record_action(
                session,
                identity=identity,
                action="ARCHIVE_WORKER",
                resource_type="worker",
                resource_id=str(worker.worker_id),
                before=before,
                after={"archived_at": worker.archived_at.isoformat(), "is_active": worker.is_active},
            )
    if worker_ids_set:
        await session.execute(
            sa.update(Booking)
            .where(
                Booking.org_id == org_id,
                Booking.assigned_worker_id.in_(worker_ids_set),
            )
            .values(assigned_worker_id=None)
        )
        await session.execute(
            sa.delete(BookingWorker).where(BookingWorker.worker_id.in_(worker_ids_set))
        )
    await session.commit()
    skipped = len(set(worker_ids)) - updated
    return_to = form.get("return_to") or "/v1/admin/ui/workers"
    parsed = urlparse(str(return_to))
    redirect_target = parsed.path if parsed.path else "/v1/admin/ui/workers"
    query_parts = parse_qs(parsed.query)
    query_parts.update(
        {"bulk_action": ["archive"], "updated": [str(updated)], "skipped": [str(skipped)]}
    )
    redirect_url = redirect_target
    if query_parts:
        redirect_url = f"{redirect_target}?{urlencode(query_parts, doseq=True)}"
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/workers/bulk/unarchive", response_class=HTMLResponse)
async def admin_workers_bulk_unarchive(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    form = await request.form()
    worker_ids = _parse_worker_ids(form)
    if not worker_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workers selected")
    workers = (
        await session.execute(
            select(Worker)
            .where(Worker.org_id == org_id, Worker.worker_id.in_(worker_ids))
        )
    ).scalars().all()
    updated = 0
    for worker in workers:
        before = {
            "archived_at": worker.archived_at.isoformat() if worker.archived_at else None,
            "is_active": worker.is_active,
        }
        changed = False
        if worker.archived_at is not None:
            worker.archived_at = None
            changed = True
        if not worker.is_active:
            worker.is_active = True
            changed = True
            if entitlements.has_tenant_identity(request):
                await billing_service.record_usage_event(
                    session,
                    entitlements.resolve_org_id(request),
                    metric="worker_created",
                    quantity=1,
                    resource_id=str(worker.worker_id),
                )
        if changed:
            updated += 1
            await audit_service.record_action(
                session,
                identity=identity,
                action="UNARCHIVE_WORKER",
                resource_type="worker",
                resource_id=str(worker.worker_id),
                before=before,
                after={"archived_at": None, "is_active": worker.is_active},
            )
    await session.commit()
    skipped = len(set(worker_ids)) - updated
    return_to = form.get("return_to") or "/v1/admin/ui/workers"
    parsed = urlparse(str(return_to))
    redirect_target = parsed.path if parsed.path else "/v1/admin/ui/workers"
    query_parts = parse_qs(parsed.query)
    query_parts.update(
        {"bulk_action": ["unarchive"], "updated": [str(updated)], "skipped": [str(skipped)]}
    )
    redirect_url = redirect_target
    if query_parts:
        redirect_url = f"{redirect_target}?{urlencode(query_parts, doseq=True)}"
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/workers/bulk/announce", response_class=HTMLResponse)
async def admin_workers_bulk_announce(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    admin_membership_id = await _resolve_admin_membership_id(request, session, org_id, identity)
    form = await request.form()
    worker_ids = _parse_worker_ids(form)
    if not worker_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workers selected")

    template_id = form.get("template_id")
    announcement_body = str(form.get("announcement_body") or "").strip()
    if template_id:
        try:
            template_id_value = int(template_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid template") from exc
        template = await message_template_service.get_template(
            session, org_id=org_id, template_id=template_id_value
        )
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        announcement_body = template.body
    if not announcement_body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message is required")

    workers = (
        await session.execute(
            select(Worker)
            .where(Worker.org_id == org_id, Worker.worker_id.in_(worker_ids))
            .order_by(Worker.created_at.desc())
        )
    ).scalars().all()
    if not workers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching workers found")

    selected_ids = [worker.worker_id for worker in workers]
    thread = await chat_service.create_group_thread(
        session,
        org_id=org_id,
        worker_ids=selected_ids,
        admin_membership_id=admin_membership_id,
    )
    await chat_service.send_message(
        session,
        org_id=org_id,
        thread=thread,
        sender_type=PARTICIPANT_ADMIN,
        body=announcement_body,
        admin_membership_id=admin_membership_id,
    )
    await session.commit()

    skipped = len(set(worker_ids)) - len(selected_ids)
    return_to = form.get("return_to") or "/v1/admin/ui/workers"
    parsed = urlparse(str(return_to))
    redirect_target = parsed.path if parsed.path else "/v1/admin/ui/workers"
    query_parts = parse_qs(parsed.query)
    query_parts.update(
        {
            "broadcast_sent": [str(len(selected_ids))],
            "broadcast_skipped": [str(skipped)],
        }
    )
    redirect_url = redirect_target
    if query_parts:
        redirect_url = f"{redirect_target}?{urlencode(query_parts, doseq=True)}"
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/v1/admin/ui/workers/export")
async def admin_workers_export_filtered(
    request: Request,
    format: str = Query(default="csv"),
    q: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    active_state: str | None = Query(default=None),
    team_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    show: str | None = Query(default=None),
    rating_min: float | None = Query(default=None),
    rating_max: float | None = Query(default=None),
    availability: str | None = Query(default=None),
    skill: list[str] | None = Query(default=None),
    has_expiring_certs: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    if format != "csv":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid export format")
    org_id = _resolve_admin_org(request, identity)
    status_value, availability_value, selected_skills = _resolve_worker_filters(
        status=status,
        show=show,
        availability=availability,
        skill=skill,
    )
    if status is None and active_state in {"inactive", "all"}:
        status_value = "all"
    active_state_value = _resolve_worker_active_state(active_state, active_only, status_value)
    workers = await _list_workers(
        session,
        org_id=org_id,
        q=q,
        active_only=active_only,
        active_state=active_state_value,
        team_id=team_id,
        status=status_value,
        rating_min=rating_min,
        rating_max=rating_max,
        skills=selected_skills,
        has_expiring_certs=has_expiring_certs,
    )
    if availability_value != "all":
        busy_until_map = await _worker_busy_until_map(
            session,
            org_id=org_id,
            worker_ids=[worker.worker_id for worker in workers],
        )
        if availability_value == "busy":
            workers = [worker for worker in workers if worker.worker_id in busy_until_map]
        elif availability_value == "free":
            workers = [worker for worker in workers if worker.worker_id not in busy_until_map]
    return _workers_csv_response(workers, filename="workers.csv")


@router.post("/v1/admin/ui/workers/export_selected")
async def admin_workers_export_selected(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    form = await request.form()
    worker_ids = _parse_worker_ids(form)
    if not worker_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workers selected")
    workers = (
        await session.execute(
            select(Worker)
            .options(selectinload(Worker.team))
            .where(Worker.org_id == org_id, Worker.worker_id.in_(worker_ids))
            .order_by(Worker.created_at.desc())
        )
    ).scalars().all()
    if not workers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching workers found")
    return _workers_csv_response(workers, filename="workers-selected.csv")


@router.get("/v1/admin/ui/workers/new", response_class=HTMLResponse)
async def admin_workers_new_form(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    teams = (
        await session.execute(
            select(Team)
            .where(Team.org_id == org_id, Team.archived_at.is_(None))
            .order_by(Team.name)
        )
    ).scalars().all()
    csrf_token = get_csrf_token(request)
    response = HTMLResponse(
        _wrap_page(
            request,
            _render_worker_form(None, teams, lang, render_csrf_input(csrf_token)),
            title="Admin — Workers",
            active="workers",
            page_lang=lang,
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/workers/new", response_class=HTMLResponse)
async def admin_workers_create(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await entitlements.require_worker_entitlement(request, session=session)
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    name = (form.get("name") or "").strip()
    phone = (form.get("phone") or "").strip()
    email = (form.get("email") or "").strip() or None
    role = (form.get("role") or "").strip() or None
    password = (form.get("password") or "").strip()
    team_id_raw = form.get("team_id")
    hourly_rate_raw = form.get("hourly_rate_cents")
    skills = _normalize_worker_skills(form.get("skills"))
    rating_raw = (form.get("rating_avg") or "").strip()
    is_active = (
        form.get("is_active") == "on"
        or form.get("is_active") == "1"
        or "is_active" not in form
    )

    if not name or not phone or not team_id_raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required fields")

    # Validate password if provided
    if password and len(password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters")
    team_id = int(team_id_raw)
    team = (
        await session.execute(
            select(Team).where(
                Team.team_id == team_id, Team.org_id == org_id, Team.archived_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    hourly_rate_cents = int(hourly_rate_raw) if hourly_rate_raw else None
    rating_avg = None
    if rating_raw:
        try:
            rating_avg = float(rating_raw)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid rating") from exc
        if rating_avg < 0 or rating_avg > 5:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rating must be between 0 and 5")

    # Hash password if provided
    password_hash_value = hash_password(password, settings=settings) if password else None

    worker = Worker(
        name=name,
        phone=phone,
        password_hash=password_hash_value,
        email=email,
        role=role,
        team_id=team_id,
        org_id=org_id,
        hourly_rate_cents=hourly_rate_cents,
        skills=skills,
        rating_avg=rating_avg,
        is_active=is_active,
    )
    session.add(worker)
    await session.flush()
    if entitlements.has_tenant_identity(request) and worker.is_active:
        await billing_service.record_usage_event(
            session,
            entitlements.resolve_org_id(request),
            metric="worker_created",
            quantity=1,
            resource_id=str(worker.worker_id),
        )
    await audit_service.record_action(
        session,
        identity=identity,
        action="CREATE_WORKER",
        resource_type="worker",
        resource_id=None,
        before=None,
        after={
            "name": name,
            "phone": phone,
            "email": email,
            "role": role,
            "team_id": team_id,
            "hourly_rate_cents": hourly_rate_cents,
            "skills": skills,
            "rating_avg": rating_avg,
            "is_active": is_active,
        },
    )
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/workers/{worker.worker_id}", status_code=status.HTTP_303_SEE_OTHER
    )


async def _worker_booking_stats(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_id: int,
) -> tuple[int, int, int | None]:
    worker_join = and_(
        BookingWorker.booking_id == Booking.booking_id, BookingWorker.worker_id == worker_id
    )
    stmt = (
        select(
            func.count(func.distinct(Booking.booking_id))
            .filter(Booking.status == "DONE")
            .label("completed"),
            func.count(func.distinct(Booking.booking_id))
            .filter(Booking.status == "CANCELLED")
            .label("cancelled"),
            func.avg(Booking.base_charge_cents).filter(Booking.status == "DONE").label("avg_ticket"),
        )
        .select_from(Booking)
        .outerjoin(BookingWorker, worker_join)
        .where(
            Booking.org_id == org_id,
            or_(Booking.assigned_worker_id == worker_id, BookingWorker.worker_id.is_not(None)),
        )
    )
    row = (await session.execute(stmt)).one()
    completed = int(row.completed or 0)
    cancelled = int(row.cancelled or 0)
    avg_ticket = int(round(float(row.avg_ticket))) if row.avg_ticket is not None else None
    return completed, cancelled, avg_ticket


async def _worker_upcoming_bookings(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_id: int,
    start_dt: datetime,
    end_dt: datetime,
) -> list[Booking]:
    worker_join = and_(
        BookingWorker.booking_id == Booking.booking_id, BookingWorker.worker_id == worker_id
    )
    stmt = (
        select(Booking)
        .outerjoin(BookingWorker, worker_join)
        .options(selectinload(Booking.client), selectinload(Booking.lead))
        .where(
            Booking.org_id == org_id,
            Booking.starts_at >= start_dt,
            Booking.starts_at < end_dt,
            or_(Booking.assigned_worker_id == worker_id, BookingWorker.worker_id.is_not(None)),
        )
        .order_by(Booking.starts_at.asc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def _worker_recent_reviews(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_id: int,
    limit: int = 5,
) -> list[WorkerReview]:
    stmt = (
        select(WorkerReview)
        .options(selectinload(WorkerReview.booking))
        .where(WorkerReview.org_id == org_id, WorkerReview.worker_id == worker_id)
        .order_by(WorkerReview.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def _worker_recent_notes(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_id: int,
    limit: int = 5,
) -> list[WorkerNote]:
    stmt = (
        select(WorkerNote)
        .options(selectinload(WorkerNote.booking))
        .where(WorkerNote.org_id == org_id, WorkerNote.worker_id == worker_id)
        .order_by(WorkerNote.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def _resolve_worker_booking(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    worker_id: int,
    booking_id: str,
) -> Booking:
    stmt = (
        select(Booking)
        .outerjoin(BookingWorker, BookingWorker.booking_id == Booking.booking_id)
        .where(
            Booking.booking_id == booking_id,
            Booking.org_id == org_id,
            or_(Booking.assigned_worker_id == worker_id, BookingWorker.worker_id == worker_id),
        )
    )
    booking = (await session.execute(stmt)).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking


_INCIDENT_SEVERITY_OPTIONS = ("low", "medium", "high")
_CERT_STATUS_OPTIONS = ("active", "pending", "expired", "revoked")
_CERT_EXPIRY_WARNING_DAYS = 30
_CERT_EXPIRY_CRITICAL_DAYS = 7


def _parse_date_input(value: str | None, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name} date",
        ) from exc


def _certificate_expiry_badge(expires_at: date | None, today: date) -> tuple[str, str] | None:
    if not expires_at:
        return None
    days_remaining = (expires_at - today).days
    if days_remaining < 0:
        return ("Expired", "badge-high")
    if days_remaining <= _CERT_EXPIRY_CRITICAL_DAYS:
        return (f"Expires in {days_remaining} days", "badge-high")
    if days_remaining <= _CERT_EXPIRY_WARNING_DAYS:
        return (f"Expires in {days_remaining} days", "badge-medium")
    return (f"Expires in {days_remaining} days", "badge-low")


@router.get("/v1/admin/ui/workers/{worker_id}", response_class=HTMLResponse)
async def admin_worker_detail(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    worker = (
        await session.execute(
            select(Worker)
            .options(selectinload(Worker.team))
            .where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")

    completed_count, cancelled_count, avg_ticket_cents = await _worker_booking_stats(
        session,
        org_id=org_id,
        worker_id=worker.worker_id,
    )
    now = datetime.now(timezone.utc)
    start_dt = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=7)
    schedule_bookings = await _worker_upcoming_bookings(
        session,
        org_id=org_id,
        worker_id=worker.worker_id,
        start_dt=start_dt,
        end_dt=end_dt,
    )
    busy_until_map = await _worker_busy_until_map(
        session,
        org_id=org_id,
        worker_ids=[worker.worker_id],
    )
    status_label = _worker_availability_indicator(worker, busy_until_map.get(worker.worker_id), lang)
    skills_html = (
        " ".join(f'<span class="chip">{html.escape(skill)}</span>' for skill in (worker.skills or []))
        or "-"
    )
    rating_display = "-" if worker.rating_avg is None else f"{worker.rating_avg:.1f} ({worker.rating_count})"
    avg_ticket_display = (
        _format_money(avg_ticket_cents, settings.deposit_currency.upper())
        if avg_ticket_cents is not None
        else "-"
    )
    recent_reviews = await _worker_recent_reviews(
        session,
        org_id=org_id,
        worker_id=worker.worker_id,
    )
    recent_notes = await _worker_recent_notes(
        session,
        org_id=org_id,
        worker_id=worker.worker_id,
    )
    onboarding = (
        await session.execute(
            select(WorkerOnboarding).where(
                WorkerOnboarding.worker_id == worker.worker_id,
                WorkerOnboarding.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    certificates = (
        await session.execute(
            select(WorkerCertificate)
            .where(
                WorkerCertificate.worker_id == worker.worker_id,
                WorkerCertificate.org_id == org_id,
                WorkerCertificate.archived_at.is_(None),
            )
            .order_by(WorkerCertificate.expires_at.asc().nulls_last(), WorkerCertificate.name.asc())
        )
    ).scalars().all()

    schedule_rows = []
    for booking in schedule_bookings:
        starts_at = booking.starts_at
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        starts_at = starts_at.astimezone(timezone.utc)
        client = booking.client or booking.lead
        client_name = getattr(client, "name", None) or getattr(client, "full_name", None) or "-"
        schedule_rows.append(
            """
            <tr>
              <td>{date}</td>
              <td>{time}</td>
              <td>{duration}</td>
              <td>{client}</td>
              <td>{status}</td>
            </tr>
            """.format(
                date=html.escape(starts_at.strftime("%Y-%m-%d")),
                time=html.escape(starts_at.strftime("%H:%M UTC")),
                duration=html.escape(str(booking.duration_minutes)),
                client=html.escape(client_name),
                status=html.escape(booking.status),
            )
        )

    archive_action = (
        f"/v1/admin/ui/workers/{worker.worker_id}/unarchive"
        if worker.archived_at
        else f"/v1/admin/ui/workers/{worker.worker_id}/archive"
    )
    archive_label = tr(lang, "admin.workers.unarchive" if worker.archived_at else "admin.workers.archive")
    today_str = now.date().isoformat()
    csrf_token = get_csrf_token(request)
    csrf_input = render_csrf_input(csrf_token)
    schedule_table = (
        "<table class=\"table\"><thead><tr>"
        f"<th>{html.escape(tr(lang, 'admin.workers.schedule_date'))}</th>"
        f"<th>{html.escape(tr(lang, 'admin.workers.schedule_time'))}</th>"
        f"<th>{html.escape(tr(lang, 'admin.workers.schedule_duration'))}</th>"
        f"<th>{html.escape(tr(lang, 'admin.workers.schedule_client'))}</th>"
        f"<th>{html.escape(tr(lang, 'admin.workers.schedule_status'))}</th>"
        "</tr></thead><tbody>"
        f"{''.join(schedule_rows)}"
        "</tbody></table>"
        if schedule_rows
        else _render_empty(tr(lang, "admin.workers.schedule_empty"))
    )
    review_rows = []
    for review in recent_reviews:
        review_rows.append(
            """
            <tr>
              <td>{rating}</td>
              <td>{comment}</td>
              <td>{booking_id}</td>
              <td>{created_at}</td>
            </tr>
            """.format(
                rating=html.escape(f"{review.rating}/5"),
                comment=html.escape(review.comment or "-"),
                booking_id=html.escape(review.booking_id),
                created_at=html.escape(_format_dt(review.created_at)),
            )
        )
    reviews_table = (
        "<table class=\"table\"><thead><tr>"
        "<th>Rating</th><th>Comment</th><th>Booking</th><th>Created</th>"
        "</tr></thead><tbody>"
        f"{''.join(review_rows)}"
        "</tbody></table>"
        if review_rows
        else _render_empty("No reviews yet.")
    )
    note_rows = []
    for note in recent_notes:
        note_rows.append(
            """
            <tr>
              <td>{note_type}</td>
              <td>{severity}</td>
              <td>{text}</td>
              <td>{booking_id}</td>
              <td>{created_by}</td>
              <td>{created_at}</td>
            </tr>
            """.format(
                note_type=html.escape(note.note_type.replace("_", " ").title()),
                severity=html.escape(note.severity or "-"),
                text=html.escape(note.text),
                booking_id=html.escape(note.booking_id or "-"),
                created_by=html.escape(note.created_by or "-"),
                created_at=html.escape(_format_dt(note.created_at)),
            )
        )
    notes_table = (
        "<table class=\"table\"><thead><tr>"
        "<th>Type</th><th>Severity</th><th>Note</th><th>Booking</th><th>Created by</th><th>Created</th>"
        "</tr></thead><tbody>"
        f"{''.join(note_rows)}"
        "</tbody></table>"
        if note_rows
        else _render_empty("No internal notes or incidents yet.")
    )
    incident_severity_options = "".join(
        f"<option value=\"{html.escape(option)}\">{html.escape(option.title())}</option>"
        for option in _INCIDENT_SEVERITY_OPTIONS
    )
    notes_form = "".join(
        [
            f"<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/workers/{worker.worker_id}/notes/create\">",
            csrf_input,
            "<div class=\"form-group\">",
            "<label>Internal note</label>",
            "<textarea class=\"input\" name=\"text\" rows=\"3\" required></textarea>",
            "</div>",
            "<div class=\"form-group\">",
            "<label>Booking ID (optional)</label>",
            "<input class=\"input\" type=\"text\" name=\"booking_id\" />",
            "</div>",
            "<button class=\"btn secondary\" type=\"submit\">Add internal note</button>",
            "</form>",
        ]
    )
    incident_form = "".join(
        [
            f"<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/workers/{worker.worker_id}/incidents/create\">",
            csrf_input,
            "<div class=\"form-group\">",
            "<label>Incident details</label>",
            "<textarea class=\"input\" name=\"text\" rows=\"3\" required></textarea>",
            "</div>",
            "<div class=\"form-group\">",
            "<label>Severity</label>",
            f"<select class=\"input\" name=\"severity\" required>{incident_severity_options}</select>",
            "</div>",
            "<div class=\"form-group\">",
            "<label>Booking ID (optional)</label>",
            "<input class=\"input\" type=\"text\" name=\"booking_id\" />",
            "</div>",
            "<button class=\"btn danger\" type=\"submit\">Report incident</button>",
            "</form>",
        ]
    )
    onboarding_completed, onboarding_total = onboarding_progress(onboarding)
    onboarding_percent = int(round((onboarding_completed / onboarding_total) * 100)) if onboarding_total else 0
    onboarding_checkboxes = "".join(
        [
            "<label class=\"with-icon\">"
            f"<input type=\"checkbox\" name=\"{html.escape(field_name)}\" "
            f"{'checked' if onboarding and getattr(onboarding, field_name, False) else ''} />"
            f"{html.escape(label)}</label>"
            for field_name, label in ONBOARDING_CHECKLIST_FIELDS
        ]
    )
    today = now.date()
    certificate_snapshots = [
        CertificateSnapshot(name=cert.name, status=cert.status, expires_at=cert.expires_at)
        for cert in certificates
    ]
    missing_required = missing_required_certificates(
        worker.skills or [],
        certificate_snapshots,
        requirements=get_skill_cert_requirements(),
        reference_date=today,
    )
    missing_required_html = (
        "<div class=\"note\"><div class=\"danger\"><strong>Missing required certificates:</strong> "
        f"{', '.join(html.escape(name) for name in missing_required)}</div></div>"
        if missing_required
        else "<div class=\"note\"><div class=\"success\">All required certificates are on file.</div></div>"
    )
    cert_status_options = list(_CERT_STATUS_OPTIONS)
    certificate_cards: list[str] = []
    for cert in certificates:
        expiry_badge = _certificate_expiry_badge(cert.expires_at, today)
        expiry_html = ""
        if expiry_badge:
            label, badge_class = expiry_badge
            expiry_html = f"<span class=\"badge {badge_class}\">{html.escape(label)}</span>"
        status_value = (cert.status or "").strip().lower()
        status_choices = list(cert_status_options)
        if status_value and status_value not in status_choices:
            status_choices.append(status_value)
        status_options_html = "".join(
            f"<option value=\"{html.escape(option)}\" {'selected' if option == status_value else ''}>"
            f"{html.escape(option.title() or option)}</option>"
            for option in status_choices
        )
        certificate_cards.append(
            "".join(
                [
                    "<div class=\"card\">",
                    f"<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/workers/{worker.worker_id}/certificates\">",
                    csrf_input,
                    f"<input type=\"hidden\" name=\"cert_id\" value=\"{cert.cert_id}\" />",
                    "<div class=\"card-row\">",
                    f"<div><div class=\"title\">{html.escape(cert.name)}</div>",
                    f"<div class=\"muted\">{expiry_html or 'No expiry date'}</div></div>",
                    "</div>",
                    "<div class=\"form-group\">",
                    "<label>Certificate name</label>",
                    f"<input class=\"input\" type=\"text\" name=\"name\" value=\"{html.escape(cert.name)}\" required />",
                    "</div>",
                    "<div class=\"form-group\">",
                    "<label>Status</label>",
                    f"<select class=\"input\" name=\"status\">{status_options_html}</select>",
                    "</div>",
                    "<div class=\"form-group\">",
                    "<label>Issued at</label>",
                    f"<input class=\"input\" type=\"date\" name=\"issued_at\" value=\"{html.escape(cert.issued_at.isoformat() if cert.issued_at else '')}\" />",
                    "</div>",
                    "<div class=\"form-group\">",
                    "<label>Expires at</label>",
                    f"<input class=\"input\" type=\"date\" name=\"expires_at\" value=\"{html.escape(cert.expires_at.isoformat() if cert.expires_at else '')}\" />",
                    "</div>",
                    "<div class=\"actions\">",
                    "<button class=\"btn secondary\" type=\"submit\">Update certificate</button>",
                    "</div>",
                    "</form>",
                    f"<form method=\"post\" action=\"/v1/admin/ui/workers/{worker.worker_id}/certificates/{cert.cert_id}/archive\">",
                    csrf_input,
                    "<button class=\"btn danger small\" type=\"submit\">Archive</button>",
                    "</form>",
                    "</div>",
                ]
            )
        )
    certificates_section = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div><div class=\"title\">Training & certificates</div>",
            "<div class=\"muted\">Track required certifications tied to skills.</div></div>",
            "</div>",
            missing_required_html,
            "<div class=\"section\">",
            "".join(certificate_cards) if certificate_cards else _render_empty("No certificates on file."),
            "</div>",
            "<div class=\"card-row\">",
            "<div><div class=\"title\">Add certificate</div></div>",
            "</div>",
            f"<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/workers/{worker.worker_id}/certificates\">",
            csrf_input,
            "<div class=\"form-group\">",
            "<label>Certificate name</label>",
            "<input class=\"input\" type=\"text\" name=\"name\" required />",
            "</div>",
            "<div class=\"form-group\">",
            "<label>Status</label>",
            "<select class=\"input\" name=\"status\">"
            + "".join(
                f"<option value=\"{html.escape(option)}\">{html.escape(option.title() or option)}</option>"
                for option in cert_status_options
            )
            + "</select>",
            "</div>",
            "<div class=\"form-group\">",
            "<label>Issued at</label>",
            "<input class=\"input\" type=\"date\" name=\"issued_at\" />",
            "</div>",
            "<div class=\"form-group\">",
            "<label>Expires at</label>",
            "<input class=\"input\" type=\"date\" name=\"expires_at\" />",
            "</div>",
            "<button class=\"btn\" type=\"submit\">Add certificate</button>",
            "</form>",
            "</div>",
        ]
    )
    onboarding_section = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div><div class=\"title\">Onboarding checklist</div>",
            "<div class=\"muted\">Docs, background checks, and training status.</div></div>",
            "</div>",
            f"<div class=\"progress\" role=\"progressbar\" aria-valuenow=\"{onboarding_percent}\" aria-valuemin=\"0\" aria-valuemax=\"100\">",
            f"<div class=\"progress-fill\" style=\"width: {onboarding_percent}%;\"></div>",
            "</div>",
            f"<div class=\"progress-meta\"><span>{onboarding_completed} of {onboarding_total} complete</span><span>{onboarding_percent}%</span></div>",
            f"<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/workers/{worker.worker_id}/onboarding\">",
            csrf_input,
            "<div class=\"stack\">",
            onboarding_checkboxes,
            "</div>",
            "<button class=\"btn\" type=\"submit\">Save checklist</button>",
            "</form>",
            "</div>",
        ]
    )
    content = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div><div class=\"title with-icon\">{_icon('users')}{html.escape(worker.name)}</div>",
            f"<div class=\"muted\">{html.escape(worker.phone)} · {html.escape(worker.email or '-')}</div>",
            f"<div class=\"muted\">{html.escape(getattr(worker.team, 'name', ''))}</div></div>",
            "<div class=\"actions\">",
            f"<span>{status_label}</span>",
            f"<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/{worker.worker_id}/edit\">{_icon('edit')}{html.escape(tr(lang, 'admin.workers.edit'))}</a>",
            f"<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/{worker.worker_id}/chat\">Chat</a>",
            "</div></div>",
            "<div class=\"card-row\">",
            f"<div><strong>{html.escape(tr(lang, 'admin.workers.rating'))}:</strong> {html.escape(rating_display)}</div>",
            f"<div><strong>{html.escape(tr(lang, 'admin.workers.skills'))}:</strong> {skills_html}</div>",
            "</div></div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div class=\"metrics\">",
            f"<div class=\"metric\"><div class=\"label\">{html.escape(tr(lang, 'admin.workers.completed_bookings'))}</div><div class=\"value\">{completed_count}</div></div>",
            f"<div class=\"metric\"><div class=\"label\">{html.escape(tr(lang, 'admin.workers.cancelled_bookings'))}</div><div class=\"value\">{cancelled_count}</div></div>",
            f"<div class=\"metric\"><div class=\"label\">{html.escape(tr(lang, 'admin.workers.avg_ticket'))}</div><div class=\"value\">{html.escape(avg_ticket_display)}</div></div>",
            f"<div class=\"metric\"><div class=\"label\">{html.escape(tr(lang, 'admin.workers.working_since'))}</div><div class=\"value\">{html.escape(_format_date(worker.created_at.date()))}</div></div>",
            "</div>",
            "</div>",
            "</div>",
            onboarding_section,
            certificates_section,
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div><div class=\"title\">Recent reviews</div>",
            "<div class=\"muted\">Last 5 client ratings</div></div>",
            "</div>",
            reviews_table,
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div><div class=\"title\">Internal notes & incidents</div>",
            "<div class=\"muted\">Last 5 entries</div></div>",
            "</div>",
            notes_table,
            "<div class=\"card-row\">",
            "<div class=\"stack\">",
            notes_form,
            incident_form,
            "</div>",
            "</div>",
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div><div class=\"title\">{html.escape(tr(lang, 'admin.workers.quick_actions'))}</div></div>",
            "<div class=\"actions\">",
            f"<a class=\"btn secondary\" href=\"/v1/admin/ui/dispatch?date={today_str}&worker_id={worker.worker_id}\">{_icon('calendar')}{html.escape(tr(lang, 'admin.workers.assign'))}</a>",
            f"<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/{worker.worker_id}/export?format=csv\">{html.escape(tr(lang, 'admin.workers.export_csv'))}</a>",
            f"<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/{worker.worker_id}/export?format=json\">{html.escape(tr(lang, 'admin.workers.export_json'))}</a>",
            "</div>",
            "</div>",
            "<div class=\"card-row\">",
            f"<form method=\"post\" action=\"{archive_action}\">{csrf_input}<button class=\"btn secondary\" type=\"submit\">{html.escape(archive_label)}</button></form>",
            "</div>",
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div><div class=\"title\">{html.escape(tr(lang, 'admin.workers.edit_skills_rating'))}</div></div>",
            "</div>",
            f"<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/workers/{worker.worker_id}\">",
            "<div class=\"form-group\">",
            f"<label>{html.escape(tr(lang, 'admin.workers.skills'))}</label>",
            f"<input class=\"input\" type=\"text\" name=\"skills\" value=\"{html.escape(', '.join(worker.skills or []))}\" />",
            f"<div class=\"muted\">{html.escape(tr(lang, 'admin.workers.skills_hint'))}</div>",
            "</div>",
            "<div class=\"form-group\">",
            f"<label>{html.escape(tr(lang, 'admin.workers.rating'))}</label>",
            f"<input class=\"input\" type=\"number\" name=\"rating_avg\" min=\"0\" max=\"5\" step=\"0.1\" value=\"{'' if worker.rating_avg is None else f'{worker.rating_avg:.1f}'}\" />",
            "</div>",
            csrf_input,
            f"<button class=\"btn\" type=\"submit\">{html.escape(tr(lang, 'admin.workers.save'))}</button>",
            "</form>",
            "</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div><div class=\"title\">{html.escape(tr(lang, 'admin.workers.weekly_schedule'))}</div>",
            f"<div class=\"muted\">{html.escape(tr(lang, 'admin.workers.next_7_days'))}</div></div>",
            "</div>",
            schedule_table,
            "</div>",
        ]
    )
    response = HTMLResponse(
        _wrap_page(request, content, title=f"Admin — {worker.name}", active="workers", page_lang=lang)
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.get("/v1/admin/ui/workers/{worker_id}/chat", response_class=HTMLResponse)
async def admin_worker_chat(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = _resolve_admin_org(request, identity)
    admin_membership_id = await _resolve_admin_membership_id(request, session, org_id, identity)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")

    thread = await chat_service.get_or_create_direct_thread(
        session,
        org_id=org_id,
        worker_id=worker.worker_id,
        admin_membership_id=admin_membership_id,
    )
    messages = await chat_service.list_messages(
        session,
        org_id=org_id,
        thread_id=thread.thread_id,
    )
    message_rows = []
    for message in messages:
        sender = "Admin" if message.sender_type == PARTICIPANT_ADMIN else worker.name
        message_rows.append(
            "".join(
                [
                    "<div class=\"card\">",
                    "<div class=\"card-row\">",
                    f"<div><div class=\"title\">{html.escape(sender)}</div>",
                    f"<div class=\"muted\">{html.escape(_format_dt(message.created_at))}</div></div>",
                    "</div>",
                    f"<div>{html.escape(message.body)}</div>",
                    "</div>",
                ]
            )
        )
    messages_section = (
        "".join(message_rows)
        if message_rows
        else "<div class=\"card\"><div class=\"muted\">No messages yet.</div></div>"
    )
    last_message = messages[-1] if messages else None
    last_message_ts = last_message.created_at.isoformat() if last_message else ""
    last_message_id = last_message.message_id if last_message else 0
    messages_container = (
        "".join(
            [
                "<div id=\"chat-messages\"",
                f" data-thread-id=\"{html.escape(str(thread.thread_id))}\"",
                f" data-last-ts=\"{html.escape(last_message_ts)}\"",
                f" data-last-id=\"{last_message_id}\"",
                f" data-worker-name=\"{html.escape(worker.name)}\">",
                messages_section,
                "</div>",
            ]
        )
        if thread
        else messages_section
    )

    csrf_token = get_csrf_token(request)
    csrf_input = render_csrf_input(csrf_token)
    content = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div><div class=\"title\">Chat with {html.escape(worker.name)}</div>",
            f"<div class=\"muted\">Thread {html.escape(str(thread.thread_id))}</div></div>",
            "<div class=\"actions\">",
            f"<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/{worker.worker_id}\">Back to worker</a>",
            f"<a class=\"btn secondary\" href=\"/v1/admin/ui/workers/{worker.worker_id}/chat\">Refresh</a>",
            "</div>",
            "</div>",
            "</div>",
            "<div class=\"actions\">",
            f"<form method=\"post\" action=\"/v1/admin/ui/workers/{worker.worker_id}/chat/read\">",
            csrf_input,
            f"<input type=\"hidden\" name=\"thread_id\" value=\"{thread.thread_id}\" />",
            "<button class=\"btn secondary\" type=\"submit\">Mark read</button>",
            "</form>",
            "</div>",
            messages_container,
            "<div class=\"card\">",
            "<div class=\"card-row\"><div class=\"title\">Send a message</div></div>",
            f"<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/workers/{worker.worker_id}/chat/messages\">",
            csrf_input,
            f"<input type=\"hidden\" name=\"thread_id\" value=\"{thread.thread_id}\" />",
            "<textarea class=\"input\" name=\"body\" rows=\"3\" required></textarea>",
            "<button class=\"btn\" type=\"submit\">Send</button>",
            "</form>",
            "</div>",
            "<script>",
            "(function() {",
            "  const container = document.getElementById('chat-messages');",
            "  if (!container || !window.EventSource) return;",
            "  const threadId = container.dataset.threadId;",
            "  const workerName = container.dataset.workerName || 'Worker';",
            "  let lastTs = container.dataset.lastTs || '';",
            "  let lastId = parseInt(container.dataset.lastId || '0', 10);",
            "  const params = new URLSearchParams();",
            "  if (lastTs) params.set('since', lastTs);",
            "  const url = `/v1/admin/chat/threads/${threadId}/stream${params.toString() ? `?${params}` : ''}`;",
            "  const source = new EventSource(url);",
            "  const formatTimestamp = (value) => {",
            "    const dt = new Date(value);",
            "    if (Number.isNaN(dt.getTime())) return value;",
            "    return dt.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';",
            "  };",
            "  source.addEventListener('message', (event) => {",
            "    if (!event.data) return;",
            "    const payload = JSON.parse(event.data);",
            "    if (!payload || !payload.message_id) return;",
            "    if (payload.created_at === lastTs && payload.message_id <= lastId) return;",
            "    lastTs = payload.created_at;",
            "    lastId = payload.message_id;",
            "    container.dataset.lastTs = lastTs;",
            "    container.dataset.lastId = String(lastId);",
            "    const sender = payload.sender_type === 'admin' ? 'Admin' : workerName;",
            "    const card = document.createElement('div');",
            "    card.className = 'card';",
            "    const row = document.createElement('div');",
            "    row.className = 'card-row';",
            "    const rowInner = document.createElement('div');",
            "    const title = document.createElement('div');",
            "    title.className = 'title';",
            "    title.textContent = sender;",
            "    const timestamp = document.createElement('div');",
            "    timestamp.className = 'muted';",
            "    timestamp.textContent = formatTimestamp(payload.created_at);",
            "    rowInner.appendChild(title);",
            "    rowInner.appendChild(timestamp);",
            "    row.appendChild(rowInner);",
            "    const body = document.createElement('div');",
            "    body.textContent = payload.body;",
            "    card.appendChild(row);",
            "    card.appendChild(body);",
            "    container.appendChild(card);",
            "  });",
            "})();",
            "</script>",
        ]
    )
    response = HTMLResponse(
        _wrap_page(request, content, title=f"Admin — Chat with {worker.name}", active="workers", page_lang=lang)
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/workers/{worker_id}/chat/messages", response_class=HTMLResponse)
async def admin_worker_chat_send(
    worker_id: int,
    request: Request,
    thread_id: uuid.UUID = Form(...),
    body: str = Form(...),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    admin_membership_id = await _resolve_admin_membership_id(request, session, org_id, identity)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    try:
        thread = await chat_service.ensure_participant(
            session,
            org_id=org_id,
            thread_id=thread_id,
            participant_type=PARTICIPANT_ADMIN,
            admin_membership_id=admin_membership_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    message_body = body.strip()
    if not message_body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")
    await chat_service.send_message(
        session,
        org_id=org_id,
        thread=thread,
        sender_type=PARTICIPANT_ADMIN,
        admin_membership_id=admin_membership_id,
        body=message_body,
    )
    await session.commit()
    return HTMLResponse(
        "",
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": f"/v1/admin/ui/workers/{worker_id}/chat"},
    )


@router.post("/v1/admin/ui/workers/{worker_id}/chat/read", response_class=HTMLResponse)
async def admin_worker_chat_mark_read(
    worker_id: int,
    request: Request,
    thread_id: uuid.UUID = Form(...),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    admin_membership_id = await _resolve_admin_membership_id(request, session, org_id, identity)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    try:
        await chat_service.ensure_participant(
            session,
            org_id=org_id,
            thread_id=thread_id,
            participant_type=PARTICIPANT_ADMIN,
            admin_membership_id=admin_membership_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    await chat_service.mark_thread_read(
        session,
        org_id=org_id,
        thread_id=thread_id,
        participant_type=PARTICIPANT_ADMIN,
        admin_membership_id=admin_membership_id,
    )
    await session.commit()
    return HTMLResponse(
        "",
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": f"/v1/admin/ui/workers/{worker_id}/chat"},
    )


@router.post("/v1/admin/ui/workers/{worker_id}/onboarding", response_class=HTMLResponse)
async def admin_worker_onboarding_update(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    form = await request.form()
    checklist_values = {
        field_name: form.get(field_name) == "on"
        for field_name, _label in ONBOARDING_CHECKLIST_FIELDS
    }
    onboarding = (
        await session.execute(
            select(WorkerOnboarding).where(
                WorkerOnboarding.worker_id == worker.worker_id,
                WorkerOnboarding.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if onboarding is None:
        onboarding = WorkerOnboarding(
            worker_id=worker.worker_id,
            org_id=org_id,
            **checklist_values,
        )
        session.add(onboarding)
    else:
        for field_name, value in checklist_values.items():
            setattr(onboarding, field_name, value)
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/workers/{worker.worker_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/v1/admin/ui/workers/{worker_id}/certificates", response_class=HTMLResponse)
async def admin_worker_certificate_upsert(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    form = await request.form()
    cert_id = form.get("cert_id")
    name = (form.get("name") or "").strip()
    status_value = (form.get("status") or "").strip().lower()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Certificate name is required")
    if status_value not in _CERT_STATUS_OPTIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid certificate status")
    issued_at = _parse_date_input(form.get("issued_at"), "issued_at")
    expires_at = _parse_date_input(form.get("expires_at"), "expires_at")
    cert_id_value = None
    if cert_id:
        try:
            cert_id_value = int(cert_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid certificate id"
            ) from exc
    if cert_id_value is not None:
        certificate = (
            await session.execute(
                select(WorkerCertificate).where(
                    WorkerCertificate.cert_id == cert_id_value,
                    WorkerCertificate.worker_id == worker.worker_id,
                    WorkerCertificate.org_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if certificate is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")
        certificate.name = name
        certificate.status = status_value
        certificate.issued_at = issued_at
        certificate.expires_at = expires_at
    else:
        certificate = WorkerCertificate(
            org_id=org_id,
            worker_id=worker.worker_id,
            name=name,
            status=status_value,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        session.add(certificate)
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/workers/{worker.worker_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post(
    "/v1/admin/ui/workers/{worker_id}/certificates/{cert_id}/archive",
    response_class=HTMLResponse,
)
async def admin_worker_certificate_archive(
    worker_id: int,
    cert_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    certificate = (
        await session.execute(
            select(WorkerCertificate).where(
                WorkerCertificate.cert_id == cert_id,
                WorkerCertificate.worker_id == worker_id,
                WorkerCertificate.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if certificate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")
    certificate.archived_at = datetime.now(timezone.utc)
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/workers/{worker_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/v1/admin/ui/workers/{worker_id}/notes/create", response_class=HTMLResponse)
async def admin_worker_note_create(
    worker_id: int,
    request: Request,
    text: str = Form(...),
    booking_id: str | None = Form(None),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")

    note_text = (text or "").strip()
    if not note_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Note text is required")

    booking_value = (booking_id or "").strip() or None
    if booking_value:
        await _resolve_worker_booking(
            session,
            org_id=org_id,
            worker_id=worker.worker_id,
            booking_id=booking_value,
        )

    note = WorkerNote(
        org_id=org_id,
        worker_id=worker.worker_id,
        booking_id=booking_value,
        note_type="note",
        text=note_text,
        created_by=identity.username,
    )
    session.add(note)
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/workers/{worker.worker_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/v1/admin/ui/workers/{worker_id}/incidents/create", response_class=HTMLResponse)
async def admin_worker_incident_create(
    worker_id: int,
    request: Request,
    text: str = Form(...),
    severity: str = Form(...),
    booking_id: str | None = Form(None),
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = _resolve_admin_org(request, identity)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")

    note_text = (text or "").strip()
    if not note_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Incident details are required"
        )
    severity_value = (severity or "").strip().lower()
    if severity_value not in _INCIDENT_SEVERITY_OPTIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid severity")

    booking_value = (booking_id or "").strip() or None
    if booking_value:
        await _resolve_worker_booking(
            session,
            org_id=org_id,
            worker_id=worker.worker_id,
            booking_id=booking_value,
        )

    note = WorkerNote(
        org_id=org_id,
        worker_id=worker.worker_id,
        booking_id=booking_value,
        note_type="incident",
        severity=severity_value,
        text=note_text,
        created_by=identity.username,
    )
    session.add(note)
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/workers/{worker.worker_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/v1/admin/ui/workers/{worker_id}/edit", response_class=HTMLResponse)
async def admin_workers_edit_form(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    teams = (
        await session.execute(
            select(Team)
            .where(
                Team.org_id == org_id,
                or_(Team.archived_at.is_(None), Team.team_id == worker.team_id),
            )
            .order_by(Team.name)
        )
    ).scalars().all()
    csrf_token = get_csrf_token(request)
    response = HTMLResponse(
        _wrap_page(
            request,
            _render_worker_form(worker, teams, lang, render_csrf_input(csrf_token)),
            title="Admin — Workers",
            active="workers",
            page_lang=lang,
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.get("/v1/admin/ui/workers/{worker_id}/export")
async def admin_worker_export(
    worker_id: int,
    request: Request,
    format: str = Query(default="csv"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    if format not in {"csv", "json"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid export format")
    worker = (
        await session.execute(
            select(Worker)
            .options(selectinload(Worker.team))
            .where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")

    worker_join = and_(
        BookingWorker.booking_id == Booking.booking_id, BookingWorker.worker_id == worker_id
    )
    booking_stmt = (
        select(Booking)
        .outerjoin(BookingWorker, worker_join)
        .options(selectinload(Booking.client), selectinload(Booking.lead))
        .where(
            Booking.org_id == org_id,
            or_(Booking.assigned_worker_id == worker_id, BookingWorker.worker_id.is_not(None)),
        )
        .order_by(Booking.starts_at.desc())
        .limit(25)
    )
    booking_rows = (await session.execute(booking_stmt)).scalars().all()

    def _client_name(booking: Booking) -> str:
        client = booking.client or booking.lead
        return getattr(client, "name", None) or getattr(client, "full_name", None) or ""

    if format == "json":
        payload = {
            "worker": {
                "worker_id": worker.worker_id,
                "name": worker.name,
                "phone": worker.phone,
                "email": worker.email,
                "role": worker.role,
                "team_id": worker.team_id,
                "team_name": getattr(worker.team, "name", None),
                "is_active": worker.is_active,
                "archived_at": worker.archived_at.isoformat() if worker.archived_at else None,
                "rating_avg": worker.rating_avg,
                "rating_count": worker.rating_count,
                "skills": worker.skills or [],
                "created_at": worker.created_at.isoformat() if worker.created_at else None,
            },
            "bookings": [
                {
                    "booking_id": booking.booking_id,
                    "starts_at": booking.starts_at.isoformat() if booking.starts_at else None,
                    "duration_minutes": booking.duration_minutes,
                    "status": booking.status,
                    "base_charge_cents": booking.base_charge_cents,
                    "client": _client_name(booking),
                }
                for booking in booking_rows
            ],
        }
        return Response(
            content=json.dumps(payload),
            media_type="application/json",
        )

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    headers = [
        "worker_id",
        "worker_name",
        "worker_phone",
        "worker_email",
        "worker_role",
        "worker_team",
        "worker_is_active",
        "worker_archived_at",
        "worker_rating_avg",
        "worker_rating_count",
        "worker_skills",
        "worker_created_at",
        "booking_id",
        "booking_starts_at",
        "booking_duration_minutes",
        "booking_status",
        "booking_base_charge_cents",
        "booking_client",
    ]
    writer.writerow(headers)
    rows = booking_rows or [None]
    for booking in rows:
        booking_client = _client_name(booking) if booking else ""
        row_values = [
            worker.worker_id,
            worker.name,
            worker.phone,
            worker.email or "",
            worker.role or "",
            getattr(worker.team, "name", "") if worker.team else "",
            worker.is_active,
            worker.archived_at.isoformat() if worker.archived_at else "",
            worker.rating_avg if worker.rating_avg is not None else "",
            worker.rating_count,
            ", ".join(worker.skills or []),
            worker.created_at.isoformat() if worker.created_at else "",
            booking.booking_id if booking else "",
            booking.starts_at.isoformat() if booking else "",
            booking.duration_minutes if booking else "",
            booking.status if booking else "",
            booking.base_charge_cents if booking else "",
            booking_client,
        ]
        writer.writerow([_safe_csv_value(value) for value in row_values])
    csv_content = csv_buffer.getvalue()
    return Response(content=csv_content, media_type="text/csv")


@router.post("/v1/admin/ui/workers/{worker_id}", response_class=HTMLResponse)
async def admin_workers_update(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")

    before = {
        "name": worker.name,
        "phone": worker.phone,
        "email": worker.email,
        "role": worker.role,
        "team_id": worker.team_id,
        "hourly_rate_cents": worker.hourly_rate_cents,
        "skills": worker.skills,
        "rating_avg": worker.rating_avg,
        "is_active": worker.is_active,
    }

    form = await request.form()
    worker.name = (form.get("name") or worker.name).strip()
    worker.phone = (form.get("phone") or worker.phone).strip()
    worker.email = (form.get("email") or "").strip() or None
    worker.role = (form.get("role") or "").strip() or None
    if "skills" in form:
        worker.skills = _normalize_worker_skills(form.get("skills"))
    if "rating_avg" in form:
        rating_raw = (form.get("rating_avg") or "").strip()
        if rating_raw:
            try:
                rating_avg = float(rating_raw)
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid rating") from exc
            if rating_avg < 0 or rating_avg > 5:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rating must be between 0 and 5")
            worker.rating_avg = rating_avg
        else:
            worker.rating_avg = None

    # Update password if provided
    password = (form.get("password") or "").strip()
    if password:
        if len(password) < 8:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters")
        worker.password_hash = hash_password(password, settings=settings)

    team_id_raw = form.get("team_id")
    if team_id_raw:
        team = (
            await session.execute(
                select(Team).where(
                    Team.team_id == int(team_id_raw),
                    Team.org_id == org_id,
                    Team.archived_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if team is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
        worker.team_id = team.team_id
    hourly_rate_raw = form.get("hourly_rate_cents")
    worker.hourly_rate_cents = int(hourly_rate_raw) if hourly_rate_raw else None
    if "is_active" in form:
        worker.is_active = form.get("is_active") == "on" or form.get("is_active") == "1"

    if entitlements.has_tenant_identity(request) and before["is_active"] != worker.is_active:
        await billing_service.record_usage_event(
            session,
            entitlements.resolve_org_id(request),
            metric="worker_created",
            quantity=1 if worker.is_active else -1,
            resource_id=str(worker.worker_id),
        )

    await audit_service.record_action(
        session,
        identity=identity,
        action="UPDATE_WORKER",
        resource_type="worker",
        resource_id=str(worker.worker_id),
        before=before,
        after={
            "name": worker.name,
            "phone": worker.phone,
            "email": worker.email,
            "role": worker.role,
            "team_id": worker.team_id,
            "hourly_rate_cents": worker.hourly_rate_cents,
            "skills": worker.skills,
            "rating_avg": worker.rating_avg,
            "is_active": worker.is_active,
        },
    )
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/workers/{worker.worker_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/v1/admin/ui/workers/{worker_id}/archive", response_class=HTMLResponse)
async def admin_workers_archive(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    before = {
        "archived_at": worker.archived_at.isoformat() if worker.archived_at else None,
        "is_active": worker.is_active,
    }
    worker.archived_at = datetime.now(timezone.utc)
    if worker.is_active:
        worker.is_active = False
        if entitlements.has_tenant_identity(request):
            await billing_service.record_usage_event(
                session,
                entitlements.resolve_org_id(request),
                metric="worker_created",
                quantity=-1,
                resource_id=str(worker.worker_id),
            )
    await session.execute(
        sa.update(Booking)
        .where(Booking.assigned_worker_id == worker.worker_id, Booking.org_id == org_id)
        .values(assigned_worker_id=None)
    )
    await session.execute(
        sa.delete(BookingWorker).where(BookingWorker.worker_id == worker.worker_id)
    )
    await audit_service.record_action(
        session,
        identity=identity,
        action="ARCHIVE_WORKER",
        resource_type="worker",
        resource_id=str(worker.worker_id),
        before=before,
        after={"archived_at": worker.archived_at.isoformat(), "is_active": worker.is_active},
    )
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/workers/{worker.worker_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/v1/admin/ui/workers/{worker_id}/unarchive", response_class=HTMLResponse)
async def admin_workers_unarchive(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    before = {
        "archived_at": worker.archived_at.isoformat() if worker.archived_at else None,
        "is_active": worker.is_active,
    }
    worker.archived_at = None
    if not worker.is_active:
        worker.is_active = True
        if entitlements.has_tenant_identity(request):
            await billing_service.record_usage_event(
                session,
                entitlements.resolve_org_id(request),
                metric="worker_created",
                quantity=1,
                resource_id=str(worker.worker_id),
            )
    await audit_service.record_action(
        session,
        identity=identity,
        action="UNARCHIVE_WORKER",
        resource_type="worker",
        resource_id=str(worker.worker_id),
        before=before,
        after={"archived_at": None, "is_active": worker.is_active},
    )
    await session.commit()
    return RedirectResponse("/v1/admin/ui/workers", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/v1/admin/ui/workers/{worker_id}/delete", response_class=HTMLResponse)
async def admin_workers_delete_confirm(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
    crew_assignments_count = await session.scalar(
        select(func.count()).select_from(BookingWorker).where(BookingWorker.worker_id == worker.worker_id)
    )
    bookings_primary_count = await session.scalar(
        select(func.count())
        .select_from(Booking)
        .where(Booking.assigned_worker_id == worker.worker_id, Booking.org_id == org_id)
    )
    csrf_token = get_csrf_token(request)
    content = _render_worker_delete_confirm_page(
        worker,
        crew_assignments_count=crew_assignments_count or 0,
        bookings_primary_count=bookings_primary_count or 0,
        lang=lang,
        csrf_input=render_csrf_input(csrf_token),
    )
    response = HTMLResponse(
        _wrap_page(request, content, title="Admin — Workers", active="workers", page_lang=lang)
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/workers/{worker_id}/delete", response_class=HTMLResponse)
async def admin_workers_delete(
    worker_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    strategy = (form.get("strategy") or "").strip()
    confirmation = (form.get("confirm") or "").strip().upper()
    if confirmation != "DELETE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deletion confirmation required")
    worker = (
        await session.execute(
            select(Worker).where(Worker.worker_id == worker_id, Worker.org_id == org_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")

    before = {"name": worker.name, "team_id": worker.team_id}
    if strategy == "detach":
        await session.execute(
            sa.delete(BookingWorker).where(BookingWorker.worker_id == worker.worker_id)
        )
        await session.execute(
            sa.update(Booking)
            .where(Booking.assigned_worker_id == worker.worker_id, Booking.org_id == org_id)
            .values(assigned_worker_id=None)
        )
        await audit_service.record_action(
            session,
            identity=identity,
            action="DELETE_WORKER_DETACH",
            resource_type="worker",
            resource_id=str(worker.worker_id),
            before=before,
            after={"deleted": True},
        )
    elif strategy == "cascade":
        booking_ids = set(
            (
                await session.execute(
                    select(Booking.booking_id).where(
                        Booking.assigned_worker_id == worker.worker_id, Booking.org_id == org_id
                    )
                )
            ).scalars().all()
        )
        crew_booking_ids = (
            await session.execute(
                select(BookingWorker.booking_id)
                .join(Booking, Booking.booking_id == BookingWorker.booking_id)
                .where(BookingWorker.worker_id == worker.worker_id, Booking.org_id == org_id)
            )
        ).scalars().all()
        booking_ids.update(crew_booking_ids)
        for booking_id in booking_ids:
            await hard_delete_booking(session, booking_id)
        await audit_service.record_action(
            session,
            identity=identity,
            action="DELETE_WORKER_CASCADE",
            resource_type="worker",
            resource_id=str(worker.worker_id),
            before=before,
            after={"deleted": True},
        )
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deletion strategy required")

    await session.delete(worker)
    await session.commit()
    return RedirectResponse("/v1/admin/ui/workers", status_code=status.HTTP_303_SEE_OTHER)


# ============================================================
# Client Management Routes
# ============================================================


def _format_client_tags(tags: list[str], lang: str | None) -> str:
    if not tags:
        return f'<div class="muted">{html.escape(tr(lang, "admin.clients.tags_none"))}</div>'
    chips = "".join(f'<span class="badge">{html.escape(tag)}</span>' for tag in tags)
    return f'<div class="stack" style="flex-direction: row; flex-wrap: wrap; gap: var(--space-xs);">{chips}</div>'


def _format_booking_workers(booking: Booking) -> str:
    names: list[str] = []
    seen: set[str] = set()
    if booking.assigned_worker and booking.assigned_worker.name:
        name = booking.assigned_worker.name
        seen.add(name)
        names.append(name)
    for assignment in booking.worker_assignments:
        worker = assignment.worker
        if worker and worker.name and worker.name not in seen:
            seen.add(worker.name)
            names.append(worker.name)
    return ", ".join(names) if names else "—"


async def _client_booking_stats(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Booking.status, func.count())
            .where(Booking.client_id == client_id, Booking.org_id == org_id)
            .group_by(Booking.status)
        )
    ).all()
    counts = {status: int(count) for status, count in rows}
    total = sum(counts.values())
    return {
        "total": total,
        "completed": counts.get("COMPLETED", 0) + counts.get("DONE", 0),
        "cancelled": counts.get("CANCELLED", 0),
    }


def _bucket_key_expr(column: sa.ColumnElement, period: str, bind) -> sa.ColumnElement:
    if bind and bind.dialect.name == "sqlite":
        if period == "week":
            return func.strftime("%Y-%W", column)
        return func.strftime("%Y-%m", column)
    return func.date_trunc(period, column)


def _week_start(value: datetime) -> datetime:
    floored = value - timedelta(days=value.weekday())
    return floored.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(value: datetime, months: int) -> datetime:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    return value.replace(year=year, month=month, day=1)


async def _client_booking_time_series(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
    period: str,
    periods: int = 12,
) -> list[dict[str, int | str]]:
    now = datetime.now(tz=timezone.utc)
    if period == "week":
        current_start = _week_start(now)
        bucket_starts = [
            current_start - timedelta(weeks=offset) for offset in range(periods - 1, -1, -1)
        ]
        label_format = "%b %d"
        key_format = "%Y-%W"
    else:
        current_start = _month_start(now)
        bucket_starts = [_add_months(current_start, -offset) for offset in range(periods - 1, -1, -1)]
        label_format = "%b %Y"
        key_format = "%Y-%m"

    cutoff = bucket_starts[0]
    bucket_expr = _bucket_key_expr(Booking.starts_at, period, session.bind)
    rows = (
        await session.execute(
            select(bucket_expr.label("bucket"), func.count())
            .where(Booking.client_id == client_id, Booking.org_id == org_id, Booking.starts_at >= cutoff)
            .group_by(bucket_expr)
            .order_by(bucket_expr)
        )
    ).all()
    counts: dict[str, int] = {}
    for bucket, count in rows:
        if bucket is None:
            continue
        if isinstance(bucket, str):
            key = bucket
        else:
            key = bucket.strftime(key_format)
        counts[key] = int(count)

    series: list[dict[str, int | str]] = []
    for bucket_start in bucket_starts:
        key = bucket_start.strftime(key_format)
        series.append(
            {
                "label": bucket_start.strftime(label_format),
                "count": counts.get(key, 0),
            }
        )
    return series


async def _client_booking_frequency_stats(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
) -> dict[str, int | float | datetime | None]:
    now = datetime.now(tz=timezone.utc)
    cutoff_30 = now - timedelta(days=30)
    cutoff_90 = now - timedelta(days=90)
    base_filters = (Booking.client_id == client_id, Booking.org_id == org_id)
    total_count = (
        await session.execute(select(func.count()).select_from(Booking).where(*base_filters))
    ).scalar_one()
    last_30_count = (
        await session.execute(
            select(func.count()).select_from(Booking).where(*base_filters, Booking.starts_at >= cutoff_30)
        )
    ).scalar_one()
    last_90_count = (
        await session.execute(
            select(func.count()).select_from(Booking).where(*base_filters, Booking.starts_at >= cutoff_90)
        )
    ).scalar_one()
    last_booking_at = (
        await session.execute(select(func.max(Booking.starts_at)).where(*base_filters))
    ).scalar_one()
    last_completed_at = (
        await session.execute(
            select(func.max(Booking.starts_at)).where(
                *base_filters, Booking.status.in_(_COMPLETED_BOOKING_STATUSES)
            )
        )
    ).scalar_one()

    completed_rows = (
        await session.execute(
            select(Booking.starts_at)
            .where(*base_filters, Booking.status.in_(_COMPLETED_BOOKING_STATUSES))
            .order_by(Booking.starts_at.asc())
        )
    ).scalars().all()
    avg_gap_days = None
    if len(completed_rows) >= 2:
        gaps = [
            (current - previous).total_seconds() / 86400
            for previous, current in zip(completed_rows, completed_rows[1:])
        ]
        avg_gap_days = sum(gaps) / len(gaps) if gaps else None

    return {
        "total": int(total_count or 0),
        "last_30": int(last_30_count or 0),
        "last_90": int(last_90_count or 0),
        "avg_gap_days": float(avg_gap_days) if avg_gap_days is not None else None,
        "last_booking_at": last_booking_at,
        "last_completed_at": last_completed_at,
    }


def _resolve_service_type(
    booking_snapshot: dict | None,
    lead_snapshot: dict | None,
) -> str | None:
    structured = booking_snapshot or {}
    service_type = structured.get("service_type") or structured.get("cleaning_type")
    if not service_type and lead_snapshot:
        service_type = lead_snapshot.get("service_type") or lead_snapshot.get("cleaning_type")
    return service_type if isinstance(service_type, str) and service_type else None


async def _client_service_preferences(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
    limit: int = 3,
) -> dict[str, list[dict[str, int | str]]]:
    service_counts: dict[str, int] = {}
    service_rows = (
        await session.execute(
            select(Booking.policy_snapshot, Lead.structured_inputs)
            .outerjoin(Lead, and_(Lead.lead_id == Booking.lead_id, Lead.org_id == org_id))
            .where(Booking.client_id == client_id, Booking.org_id == org_id)
        )
    ).all()
    for policy_snapshot, lead_snapshot in service_rows:
        service_type = _resolve_service_type(policy_snapshot, lead_snapshot)
        if service_type:
            service_counts[service_type] = service_counts.get(service_type, 0) + 1

    service_types = [
        {"label": label, "count": count}
        for label, count in sorted(service_counts.items(), key=lambda item: (-item[1], item[0]))
    ][:limit]

    addon_rows = (
        await session.execute(
            select(
                AddonDefinition.name,
                func.coalesce(func.sum(OrderAddon.qty), 0).label("total_qty"),
            )
            .join(OrderAddon, OrderAddon.addon_id == AddonDefinition.addon_id)
            .join(Booking, Booking.booking_id == OrderAddon.order_id)
            .where(Booking.client_id == client_id, Booking.org_id == org_id)
            .group_by(AddonDefinition.addon_id, AddonDefinition.name)
            .order_by(sa.desc("total_qty"), AddonDefinition.name.asc())
        )
    ).all()
    addons = [
        {"label": str(name), "count": int(total_qty or 0)}
        for name, total_qty in addon_rows
        if name
    ][:limit]

    return {"service_types": service_types, "addons": addons}


async def _client_churn_inputs_for_clients(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_ids: list[str],
) -> dict[str, dict[str, float | int | datetime | None]]:
    if not client_ids:
        return {}
    now = datetime.now(tz=timezone.utc)
    complaints_cutoff = now - timedelta(days=settings.client_risk_complaints_window_days)
    feedback_cutoff = now - timedelta(days=settings.client_risk_feedback_window_days)

    complaints_rows = (
        await session.execute(
            select(
                ClientNote.client_id,
                func.count(ClientNote.note_id).label("complaint_count"),
            )
            .where(
                ClientNote.org_id == org_id,
                ClientNote.client_id.in_(client_ids),
                ClientNote.note_type == ClientNote.NOTE_TYPE_COMPLAINT,
                ClientNote.created_at >= complaints_cutoff,
            )
            .group_by(ClientNote.client_id)
        )
    ).all()
    feedback_rows = (
        await session.execute(
            select(
                ClientFeedback.client_id,
                func.avg(ClientFeedback.rating).label("avg_rating"),
                func.coalesce(
                    func.sum(
                        sa.case(
                            (ClientFeedback.rating <= settings.client_risk_low_rating_threshold, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("low_rating_count"),
            )
            .where(
                ClientFeedback.org_id == org_id,
                ClientFeedback.client_id.in_(client_ids),
                ClientFeedback.created_at >= feedback_cutoff,
            )
            .group_by(ClientFeedback.client_id)
        )
    ).all()
    last_completed_rows = (
        await session.execute(
            select(
                Booking.client_id,
                func.max(Booking.starts_at).label("last_completed_at"),
            )
            .where(
                Booking.org_id == org_id,
                Booking.client_id.in_(client_ids),
                Booking.status.in_(_COMPLETED_BOOKING_STATUSES),
            )
            .group_by(Booking.client_id)
        )
    ).all()
    completed_rows = (
        await session.execute(
            select(Booking.client_id, Booking.starts_at)
            .where(
                Booking.org_id == org_id,
                Booking.client_id.in_(client_ids),
                Booking.status.in_(_COMPLETED_BOOKING_STATUSES),
            )
            .order_by(Booking.client_id.asc(), Booking.starts_at.asc())
        )
    ).all()

    complaint_map = {row.client_id: int(row.complaint_count or 0) for row in complaints_rows}
    feedback_map = {
        row.client_id: {
            "avg_rating": float(row.avg_rating) if row.avg_rating is not None else None,
            "low_rating_count": int(row.low_rating_count or 0),
        }
        for row in feedback_rows
    }
    last_completed_map = {
        row.client_id: row.last_completed_at for row in last_completed_rows
    }

    avg_gap_map: dict[str, float | None] = {}
    grouped: dict[str, list[datetime]] = {}
    for client_id, starts_at in completed_rows:
        grouped.setdefault(client_id, []).append(starts_at)
    for client_id, dates in grouped.items():
        if len(dates) < 2:
            avg_gap_map[client_id] = None
            continue
        gaps = [
            (current - previous).total_seconds() / 86400
            for previous, current in zip(dates, dates[1:])
        ]
        avg_gap_map[client_id] = sum(gaps) / len(gaps) if gaps else None

    churn_inputs: dict[str, dict[str, float | int | datetime | None]] = {}
    for client_id in client_ids:
        churn_inputs[client_id] = {
            "last_completed_at": last_completed_map.get(client_id),
            "avg_gap_days": avg_gap_map.get(client_id),
            "complaint_count": complaint_map.get(client_id, 0),
            "avg_rating": feedback_map.get(client_id, {}).get("avg_rating"),
            "low_rating_count": feedback_map.get(client_id, {}).get("low_rating_count", 0),
        }
    return churn_inputs


async def _client_favorite_workers(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
    limit: int = 3,
) -> list[dict[str, int | str]]:
    assigned = (
        select(
            Booking.booking_id.label("booking_id"),
            Booking.assigned_worker_id.label("worker_id"),
            Booking.duration_minutes.label("duration_minutes"),
            Booking.base_charge_cents.label("base_charge_cents"),
        )
        .where(
            Booking.client_id == client_id,
            Booking.org_id == org_id,
            Booking.assigned_worker_id.is_not(None),
            Booking.status.in_(_COMPLETED_BOOKING_STATUSES),
        )
    )
    crew = (
        select(
            BookingWorker.booking_id.label("booking_id"),
            BookingWorker.worker_id.label("worker_id"),
            Booking.duration_minutes.label("duration_minutes"),
            Booking.base_charge_cents.label("base_charge_cents"),
        )
        .join(Booking, Booking.booking_id == BookingWorker.booking_id)
        .where(
            Booking.client_id == client_id,
            Booking.org_id == org_id,
            Booking.status.in_(_COMPLETED_BOOKING_STATUSES),
        )
    )
    combined = sa.union(assigned, crew).subquery()
    rows = (
        await session.execute(
            select(
                Worker.worker_id,
                Worker.name,
                func.count(combined.c.booking_id).label("completed_count"),
                func.coalesce(func.sum(combined.c.duration_minutes), 0).label("total_minutes"),
                func.coalesce(func.sum(combined.c.base_charge_cents), 0).label("total_revenue_cents"),
            )
            .join(Worker, Worker.worker_id == combined.c.worker_id)
            .where(Worker.org_id == org_id)
            .group_by(Worker.worker_id, Worker.name)
            .order_by(
                sa.desc("completed_count"),
                sa.desc("total_revenue_cents"),
                sa.desc("total_minutes"),
                Worker.name.asc(),
            )
            .limit(limit)
        )
    ).all()
    return [
        {
            "worker_id": int(worker_id),
            "name": name,
            "completed_count": int(completed_count or 0),
            "total_minutes": int(total_minutes or 0),
            "total_revenue_cents": int(total_revenue_cents or 0),
        }
        for worker_id, name, completed_count, total_minutes, total_revenue_cents in rows
    ]


async def _client_feedback_summary(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
) -> dict[str, float | int | None]:
    row = (
        await session.execute(
            select(
                func.count(ClientFeedback.feedback_id).label("rating_count"),
                func.avg(ClientFeedback.rating).label("avg_rating"),
                func.coalesce(
                    func.sum(sa.case((ClientFeedback.rating <= 2, 1), else_=0)), 0
                ).label("low_rating_count"),
            ).where(ClientFeedback.org_id == org_id, ClientFeedback.client_id == client_id)
        )
    ).one()
    rating_count = int(row.rating_count or 0)
    avg_rating = float(row.avg_rating) if row.avg_rating is not None else None
    low_rating_count = int(row.low_rating_count or 0)
    return {
        "rating_count": rating_count,
        "avg_rating": avg_rating,
        "low_rating_count": low_rating_count,
    }


async def _client_risk_summary(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
) -> dict[str, float | int | None]:
    complaints_cutoff = datetime.now(tz=timezone.utc) - timedelta(
        days=settings.client_risk_complaints_window_days
    )
    feedback_cutoff = datetime.now(tz=timezone.utc) - timedelta(
        days=settings.client_risk_feedback_window_days
    )
    complaint_count = (
        await session.execute(
            select(func.count(ClientNote.note_id)).where(
                ClientNote.org_id == org_id,
                ClientNote.client_id == client_id,
                ClientNote.note_type == ClientNote.NOTE_TYPE_COMPLAINT,
                ClientNote.created_at >= complaints_cutoff,
            )
        )
    ).scalar_one()
    feedback_row = (
        await session.execute(
            select(
                func.avg(ClientFeedback.rating).label("avg_rating"),
                func.coalesce(
                    func.sum(
                        sa.case(
                            (ClientFeedback.rating <= settings.client_risk_low_rating_threshold, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("low_rating_count"),
                func.count(ClientFeedback.feedback_id).label("rating_count"),
            ).where(
                ClientFeedback.org_id == org_id,
                ClientFeedback.client_id == client_id,
                ClientFeedback.created_at >= feedback_cutoff,
            )
        )
    ).one()
    avg_rating = float(feedback_row.avg_rating) if feedback_row.avg_rating is not None else None
    return {
        "complaint_count": int(complaint_count or 0),
        "avg_rating": avg_rating,
        "low_rating_count": int(feedback_row.low_rating_count or 0),
        "rating_count": int(feedback_row.rating_count or 0),
    }


async def _client_recent_feedback(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
    limit: int = 5,
) -> list[tuple[ClientFeedback, Booking]]:
    stmt = (
        select(ClientFeedback, Booking)
        .join(Booking, Booking.booking_id == ClientFeedback.booking_id)
        .where(ClientFeedback.org_id == org_id, ClientFeedback.client_id == client_id)
        .order_by(ClientFeedback.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(feedback, booking) for feedback, booking in rows]


async def _resolve_client_booking(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
    booking_id: str,
) -> Booking:
    booking = (
        await session.execute(
            select(Booking).where(
                Booking.booking_id == booking_id,
                Booking.org_id == org_id,
                Booking.client_id == client_id,
            )
        )
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid booking for client")
    return booking


_COMPLETED_BOOKING_STATUSES = {"COMPLETED", "DONE"}


async def _client_finance_aggregates(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
) -> dict[str, int | str]:
    booking_totals = (
        await session.execute(
            select(
                func.count(Booking.booking_id).label("total_bookings"),
                func.coalesce(
                    func.sum(
                        sa.case(
                            (Booking.status.in_(_COMPLETED_BOOKING_STATUSES), 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("completed_bookings"),
                func.coalesce(
                    func.sum(
                        sa.case(
                            (Booking.status.in_(_COMPLETED_BOOKING_STATUSES), Booking.base_charge_cents),
                            else_=0,
                        )
                    ),
                    0,
                ).label("completed_total_cents"),
            ).where(Booking.client_id == client_id, Booking.org_id == org_id)
        )
    ).one()
    total_bookings = int(booking_totals.total_bookings or 0)
    completed_bookings = int(booking_totals.completed_bookings or 0)
    completed_total_cents = int(booking_totals.completed_total_cents or 0)

    paid_invoice_totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(Invoice.total_cents), 0).label("paid_total_cents"),
                func.count(Invoice.invoice_id).label("paid_invoice_count"),
            )
            .select_from(Invoice)
            .join(Booking, Invoice.order_id == Booking.booking_id)
            .where(
                Booking.client_id == client_id,
                Booking.org_id == org_id,
                Invoice.org_id == org_id,
                Invoice.status == invoice_statuses.INVOICE_STATUS_PAID,
            )
        )
    ).one()
    paid_invoice_total_cents = int(paid_invoice_totals.paid_total_cents or 0)
    paid_invoice_count = int(paid_invoice_totals.paid_invoice_count or 0)

    booking_ids_subq = select(Booking.booking_id).where(
        Booking.client_id == client_id, Booking.org_id == org_id
    )
    invoice_ids_subq = (
        select(Invoice.invoice_id)
        .join(Booking, Invoice.order_id == Booking.booking_id)
        .where(Booking.client_id == client_id, Booking.org_id == org_id, Invoice.org_id == org_id)
    )

    payment_totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(Payment.amount_cents), 0).label("paid_cents"),
                func.count(Payment.payment_id).label("payment_count"),
            ).where(
                Payment.org_id == org_id,
                Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                or_(
                    Payment.booking_id.in_(booking_ids_subq),
                    Payment.invoice_id.in_(invoice_ids_subq),
                ),
            )
        )
    ).one()
    paid_payments_cents = int(payment_totals.paid_cents or 0)
    payment_count = int(payment_totals.payment_count or 0)
    payment_currency_rows = (
        await session.execute(
            select(func.distinct(Payment.currency)).where(
                Payment.org_id == org_id,
                Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                or_(
                    Payment.booking_id.in_(booking_ids_subq),
                    Payment.invoice_id.in_(invoice_ids_subq),
                ),
            )
        )
    ).all()
    payment_currencies = {row[0].upper() for row in payment_currency_rows if row[0]}

    invoice_currency_rows = (
        await session.execute(
            select(func.distinct(Invoice.currency))
            .select_from(Invoice)
            .join(Booking, Invoice.order_id == Booking.booking_id)
            .where(
                Booking.client_id == client_id,
                Booking.org_id == org_id,
                Invoice.org_id == org_id,
                Invoice.status == invoice_statuses.INVOICE_STATUS_PAID,
            )
        )
    ).all()
    invoice_currencies = {row[0].upper() for row in invoice_currency_rows if row[0]}

    payments_by_invoice = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(Payment.amount_cents), 0).label("paid_cents"),
        )
        .where(
            Payment.org_id == org_id,
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
        )
        .group_by(Payment.invoice_id)
        .subquery()
    )
    balance_rows = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(
                        sa.case(
                            (
                                (Invoice.total_cents - func.coalesce(payments_by_invoice.c.paid_cents, 0)) > 0,
                                Invoice.total_cents - func.coalesce(payments_by_invoice.c.paid_cents, 0),
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("outstanding_cents"),
                func.coalesce(
                    func.sum(
                        sa.case(
                            (
                                (func.coalesce(payments_by_invoice.c.paid_cents, 0) - Invoice.total_cents) > 0,
                                func.coalesce(payments_by_invoice.c.paid_cents, 0) - Invoice.total_cents,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("overpaid_cents"),
                func.count(Invoice.invoice_id).label("invoice_count"),
                func.coalesce(
                    func.sum(
                        sa.case(
                            (
                                Invoice.total_cents
                                > func.coalesce(payments_by_invoice.c.paid_cents, 0),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("unpaid_invoice_count"),
            )
            .select_from(Invoice)
            .join(Booking, Invoice.order_id == Booking.booking_id)
            .outerjoin(payments_by_invoice, payments_by_invoice.c.invoice_id == Invoice.invoice_id)
            .where(
                Booking.client_id == client_id,
                Booking.org_id == org_id,
                Invoice.org_id == org_id,
                Invoice.status.in_(
                    {
                        invoice_statuses.INVOICE_STATUS_SENT,
                        invoice_statuses.INVOICE_STATUS_OVERDUE,
                        invoice_statuses.INVOICE_STATUS_PARTIAL,
                        invoice_statuses.INVOICE_STATUS_PAID,
                    }
                ),
            )
        )
    ).one()

    ltv_source = "completed_bookings"
    if payment_count > 0 or paid_payments_cents > 0:
        ltv_cents = paid_payments_cents
        ltv_source = "payments"
    elif paid_invoice_total_cents > 0:
        ltv_cents = paid_invoice_total_cents
        ltv_source = "paid_invoices"
    else:
        ltv_cents = completed_total_cents

    if ltv_source == "payments":
        avg_basis = paid_invoice_count or completed_bookings
    elif ltv_source == "paid_invoices":
        avg_basis = paid_invoice_count
    else:
        avg_basis = completed_bookings
    avg_check_cents = int(round(ltv_cents / avg_basis)) if avg_basis else 0

    currency_source = ltv_source
    currency_mixed = False
    if ltv_source == "payments":
        currencies = payment_currencies
    elif ltv_source == "paid_invoices":
        currencies = invoice_currencies
    else:
        currencies = {settings.deposit_currency.upper()}
    currency_code = None
    if len(currencies) > 1:
        currency_mixed = True
    elif len(currencies) == 1:
        currency_code = next(iter(currencies))
    else:
        currency_code = settings.deposit_currency.upper()

    return {
        "total_bookings": total_bookings,
        "completed_bookings": completed_bookings,
        "ltv_cents": int(ltv_cents),
        "avg_check_cents": avg_check_cents,
        "avg_basis": int(avg_basis),
        "ltv_source": ltv_source,
        "currency_source": currency_source,
        "currency_code": currency_code,
        "currency_mixed": currency_mixed,
        "outstanding_cents": int(balance_rows.outstanding_cents or 0),
        "overpaid_cents": int(balance_rows.overpaid_cents or 0),
        "invoice_count": int(balance_rows.invoice_count or 0),
        "unpaid_invoice_count": int(balance_rows.unpaid_invoice_count or 0),
    }


async def _client_invoice_history(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
) -> list[Invoice]:
    return (
        (
            await session.execute(
                select(Invoice)
                .join(Booking, Invoice.order_id == Booking.booking_id)
                .where(
                    Booking.client_id == client_id,
                    Booking.org_id == org_id,
                    Invoice.org_id == org_id,
                )
                .order_by(Invoice.issue_date.desc(), Invoice.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )


async def _client_payment_history(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
) -> list[tuple[Payment, str | None]]:
    booking_ids_subq = select(Booking.booking_id).where(
        Booking.client_id == client_id, Booking.org_id == org_id
    )
    invoice_ids_subq = (
        select(Invoice.invoice_id)
        .join(Booking, Invoice.order_id == Booking.booking_id)
        .where(Booking.client_id == client_id, Booking.org_id == org_id, Invoice.org_id == org_id)
    )
    return (
        await session.execute(
            select(Payment, Invoice.invoice_number)
            .outerjoin(Invoice, Payment.invoice_id == Invoice.invoice_id)
            .where(
                Payment.org_id == org_id,
                or_(
                    Payment.booking_id.in_(booking_ids_subq),
                    Payment.invoice_id.in_(invoice_ids_subq),
                ),
            )
            .order_by(sa.desc(func.coalesce(Payment.received_at, Payment.created_at)))
            .limit(20)
        )
    ).all()


def _render_client_form(client: ClientUser | None, lang: str | None, csrf_input: str) -> str:
    return f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title with-icon">{_icon('users')}{html.escape(tr(lang, 'admin.clients.title'))}</div>
          <div class="muted">{html.escape(tr(lang, 'admin.clients.subtitle'))}</div>
        </div>
      </div>
      <form class="stack" method="post">
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.clients.name'))}</label>
          <input class="input" type="text" name="name" value="{html.escape(getattr(client, 'name', '') or '')}" />
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.clients.phone'))}</label>
          <input class="input" type="text" name="phone" value="{html.escape(getattr(client, 'phone', '') or '')}" />
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.clients.email'))}</label>
          <input class="input" type="email" name="email" required value="{html.escape(getattr(client, 'email', '') or '')}" />
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.clients.address'))}</label>
          <input class="input" type="text" name="address" value="{html.escape(getattr(client, 'address', '') or '')}" />
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.clients.notes'))}</label>
          <textarea class="input" name="notes" rows="3">{html.escape(getattr(client, 'notes', '') or '')}</textarea>
        </div>
        {csrf_input}
        <button class="btn" type="submit">{html.escape(tr(lang, 'admin.clients.save'))}</button>
      </form>
    </div>
    """


def _render_client_danger_zone(client: ClientUser, lang: str | None, csrf_input: str) -> str:
    if client.is_active:
        archive_action = "archive"
        archive_label = html.escape(tr(lang, "admin.clients.archive_client"))
        confirm_text = html.escape(tr(lang, "admin.clients.archive_confirm"))
        help_text = html.escape(tr(lang, "admin.clients.archive_help"))
    else:
        archive_action = "unarchive"
        archive_label = html.escape(tr(lang, "admin.clients.unarchive_client"))
        confirm_text = html.escape(tr(lang, "admin.clients.unarchive_confirm"))
        help_text = html.escape(tr(lang, "admin.clients.unarchive_help"))

    delete_label = html.escape(tr(lang, "admin.clients.delete_client"))
    return f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.danger_zone"))}</div>
          <div class="muted">{help_text}</div>
        </div>
      </div>
      <form class="stack" method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/{archive_action}" onsubmit="return confirm('{confirm_text}')">
        {csrf_input}
        <button class="btn danger" type="submit">{archive_label}</button>
      </form>
    </div>
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{delete_label}</div>
          <div class="muted">Delete permanently with a dependency strategy.</div>
        </div>
        <div class="actions">
          <a class="btn danger" href="/v1/admin/ui/clients/{html.escape(client.client_id)}/delete">Delete permanently</a>
        </div>
      </div>
    </div>
    """


async def _list_clients(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    q: str | None,
    show: str | None,
    risk: str | None,
) -> list[ClientUser]:
    risk_value = (risk or "all").strip().lower()
    allowed_risks = {"all", "frequent_complaints", "low_rater", "any"}
    if risk_value not in allowed_risks:
        risk_value = "all"
    filters = [ClientUser.org_id == org_id]
    if show == "archived":
        filters.append(ClientUser.is_active.is_(False))
    else:
        filters.append(ClientUser.is_active.is_(True))
    if q:
        pattern = f"%{q.lower()}%"
        filters.append(
            or_(
                func.lower(ClientUser.name).like(pattern),
                func.lower(ClientUser.phone).like(pattern),
                func.lower(ClientUser.email).like(pattern),
            )
        )
    complaints_cutoff = datetime.now(tz=timezone.utc) - timedelta(
        days=settings.client_risk_complaints_window_days
    )
    feedback_cutoff = datetime.now(tz=timezone.utc) - timedelta(
        days=settings.client_risk_feedback_window_days
    )
    complaints_subq = (
        select(
            ClientNote.client_id.label("client_id"),
            func.count(ClientNote.note_id).label("complaint_count"),
        )
        .where(
            ClientNote.org_id == org_id,
            ClientNote.note_type == ClientNote.NOTE_TYPE_COMPLAINT,
            ClientNote.created_at >= complaints_cutoff,
        )
        .group_by(ClientNote.client_id)
        .subquery()
    )
    feedback_subq = (
        select(
            ClientFeedback.client_id.label("client_id"),
            func.avg(ClientFeedback.rating).label("avg_rating"),
            func.coalesce(
                func.sum(
                    sa.case(
                        (ClientFeedback.rating <= settings.client_risk_low_rating_threshold, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("low_rating_count"),
        )
        .where(ClientFeedback.org_id == org_id, ClientFeedback.created_at >= feedback_cutoff)
        .group_by(ClientFeedback.client_id)
        .subquery()
    )
    complaint_count = func.coalesce(complaints_subq.c.complaint_count, 0)
    low_rating_count = func.coalesce(feedback_subq.c.low_rating_count, 0)
    low_rating_by_avg = and_(
        feedback_subq.c.avg_rating.is_not(None),
        feedback_subq.c.avg_rating <= settings.client_risk_avg_rating_threshold,
    )
    low_rating_by_count = low_rating_count >= settings.client_risk_low_rating_count_threshold
    frequent_complaints_filter = complaint_count >= settings.client_risk_complaints_threshold
    low_rater_filter = or_(low_rating_by_avg, low_rating_by_count)
    if risk_value == "frequent_complaints":
        filters.append(frequent_complaints_filter)
    elif risk_value == "low_rater":
        filters.append(low_rater_filter)
    elif risk_value == "any":
        filters.append(or_(frequent_complaints_filter, low_rater_filter))
    stmt = (
        select(ClientUser)
        .outerjoin(complaints_subq, complaints_subq.c.client_id == ClientUser.client_id)
        .outerjoin(feedback_subq, feedback_subq.c.client_id == ClientUser.client_id)
        .where(*filters)
        .order_by(ClientUser.created_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def _client_delete_counts(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    client_id: str,
) -> dict[str, int]:
    bookings_count = (
        await session.execute(
            select(func.count())
            .select_from(Booking)
            .where(Booking.client_id == client_id, Booking.org_id == org_id)
        )
    ).scalar_one()
    invoices_count = (
        await session.execute(
            select(func.count())
            .select_from(Invoice)
            .join(Booking, Invoice.order_id == Booking.booking_id)
            .where(Booking.client_id == client_id, Booking.org_id == org_id)
        )
    ).scalar_one()
    subscriptions_count = (
        await session.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.client_id == client_id, Subscription.org_id == org_id)
        )
    ).scalar_one()
    return {
        "bookings": int(bookings_count or 0),
        "invoices": int(invoices_count or 0),
        "subscriptions": int(subscriptions_count or 0),
    }


@router.get("/v1/admin/ui/clients", response_class=HTMLResponse)
async def admin_clients_list(
    request: Request,
    q: str | None = Query(default=None),
    show: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    churn: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_admin),
) -> HTMLResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    lang = resolve_lang(request)
    clients = await _list_clients(session, org_id=org_id, q=q, show=show, risk=risk)

    search_value = html.escape(q or "")
    show_value = show or ""
    risk_value = (risk or "all").strip().lower()
    if risk_value not in {"all", "frequent_complaints", "low_rater", "any"}:
        risk_value = "all"
    churn_value = (churn or "any").strip().lower()
    if churn_value not in {"any", "low", "medium", "high"}:
        churn_value = "any"
    churn_assessments: dict[str, client_service.ChurnAssessment] = {}
    if clients:
        churn_inputs = await _client_churn_inputs_for_clients(
            session,
            org_id=org_id,
            client_ids=[client.client_id for client in clients],
        )
        now = datetime.now(tz=timezone.utc)
        for client in clients:
            inputs = churn_inputs.get(client.client_id, {})
            last_completed_at = inputs.get("last_completed_at")
            if isinstance(last_completed_at, datetime):
                last_completed_at = _ensure_timezone(last_completed_at)
            days_since_last = (
                int((now - last_completed_at).total_seconds() / 86400)
                if isinstance(last_completed_at, datetime)
                else None
            )
            churn_assessments[client.client_id] = client_service.evaluate_churn(
                days_since_last_completed=days_since_last,
                avg_gap_days=inputs.get("avg_gap_days"),
                complaint_count=int(inputs.get("complaint_count") or 0),
                avg_rating=inputs.get("avg_rating"),
                low_rating_count=int(inputs.get("low_rating_count") or 0),
            )
        if churn_value != "any":
            clients = [
                client
                for client in clients
                if churn_assessments.get(client.client_id)
                and churn_assessments[client.client_id].risk_band.lower() == churn_value
            ]
    csrf_token = get_csrf_token(request)
    csrf_input = render_csrf_input(csrf_token)
    search_form = f"""
    <form class="stack" method="get" style="margin-bottom: var(--space-lg);">
      <div class="form-group">
        <label>{html.escape(tr(lang, 'admin.clients.search'))}</label>
        <input class="input" type="text" name="q" value="{search_value}" />
      </div>
      <div class="form-group">
        <label>{html.escape(tr(lang, 'admin.clients.status_label'))}</label>
        <select class="input" name="show">
          <option value="" {"selected" if show_value == "" else ""}>{html.escape(tr(lang, 'admin.clients.status_active'))}</option>
          <option value="archived" {"selected" if show_value == "archived" else ""}>{html.escape(tr(lang, 'admin.clients.status_archived'))}</option>
        </select>
      </div>
      <div class="form-group">
        <label>{html.escape(tr(lang, "admin.clients.risk_flags_label"))}</label>
        <select class="input" name="risk">
          <option value="all" {"selected" if risk_value == "all" else ""}>{html.escape(tr(lang, "admin.clients.risk_filter_all"))}</option>
          <option value="frequent_complaints" {"selected" if risk_value == "frequent_complaints" else ""}>{html.escape(tr(lang, "admin.clients.risk_filter_frequent_complaints"))}</option>
          <option value="low_rater" {"selected" if risk_value == "low_rater" else ""}>{html.escape(tr(lang, "admin.clients.risk_filter_low_ratings"))}</option>
          <option value="any" {"selected" if risk_value == "any" else ""}>{html.escape(tr(lang, "admin.clients.risk_filter_any"))}</option>
        </select>
      </div>
      <div class="form-group">
        <label>{html.escape(tr(lang, "admin.clients.churn_label"))}</label>
        <select class="input" name="churn">
          <option value="any" {"selected" if churn_value == "any" else ""}>{html.escape(tr(lang, "admin.clients.churn_filter_any"))}</option>
          <option value="low" {"selected" if churn_value == "low" else ""}>{html.escape(tr(lang, "admin.clients.churn_filter_low"))}</option>
          <option value="medium" {"selected" if churn_value == "medium" else ""}>{html.escape(tr(lang, "admin.clients.churn_filter_medium"))}</option>
          <option value="high" {"selected" if churn_value == "high" else ""}>{html.escape(tr(lang, "admin.clients.churn_filter_high"))}</option>
        </select>
      </div>
      <button class="btn" type="submit">{html.escape(tr(lang, "admin.clients.search_button"))}</button>
    </form>
    """

    rows = []
    for client in clients:
        status_label = (
            html.escape(tr(lang, "admin.clients.status_archived"))
            if not client.is_active
            else html.escape(tr(lang, "admin.clients.status_active"))
        )
        if client.is_active:
            action_html = f"""
            <form method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/archive" onsubmit="return confirm('{html.escape(tr(lang, 'admin.clients.archive_confirm'))}')">
              {csrf_input}
              <button class="btn danger small" type="submit">{html.escape(tr(lang, 'admin.clients.archive'))}</button>
            </form>
            """
        elif show_value == "archived":
            action_html = f"""
            <div class="stack" style="gap: var(--space-xs);">
              <form method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/unarchive" onsubmit="return confirm('{html.escape(tr(lang, 'admin.clients.unarchive_confirm'))}')">
                {csrf_input}
                <button class="btn secondary small" type="submit">{html.escape(tr(lang, 'admin.clients.unarchive'))}</button>
              </form>
              <a class="btn danger small" href="/v1/admin/ui/clients/{html.escape(client.client_id)}/delete">Delete permanently</a>
            </div>
            """
        else:
            action_html = f"<span class=\"badge\">{html.escape(tr(lang, 'admin.clients.status_archived'))}</span>"
        churn_assessment = churn_assessments.get(client.client_id)
        churn_badge = _churn_badge(churn_assessment.risk_band if churn_assessment else "LOW", lang)
        rows.append(f"""
        <tr>
          <td><a href="/v1/admin/ui/clients/{html.escape(client.client_id)}">{html.escape(client.name or '—')}</a></td>
          <td>{html.escape(client.email or '—')}</td>
          <td>{html.escape(client.phone or '—')}</td>
          <td>{html.escape(client.address or '—')}</td>
          <td>{churn_badge}</td>
          <td>{status_label}</td>
          <td>{action_html}</td>
        </tr>
        """)

    table = f"""
    <table class="table">
      <thead>
        <tr>
          <th>{html.escape(tr(lang, 'admin.clients.name'))}</th>
          <th>{html.escape(tr(lang, 'admin.clients.email'))}</th>
          <th>{html.escape(tr(lang, 'admin.clients.phone'))}</th>
          <th>{html.escape(tr(lang, 'admin.clients.address'))}</th>
          <th>{html.escape(tr(lang, "admin.clients.churn_column"))}</th>
          <th>{html.escape(tr(lang, 'admin.clients.status_label'))}</th>
          <th>{html.escape(tr(lang, 'admin.clients.actions'))}</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows) if rows else f'<tr><td colspan="7">{html.escape(tr(lang, "admin.clients.none"))}</td></tr>'}
      </tbody>
    </table>
    """ if clients else f'<p class="muted">{html.escape(tr(lang, "admin.clients.none"))}</p>'

    content = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title with-icon">{_icon('users')}{html.escape(tr(lang, 'admin.clients.title'))}</div>
          <div class="muted">{html.escape(tr(lang, 'admin.clients.subtitle'))}</div>
        </div>
        <a class="btn" href="/v1/admin/ui/clients/new">{html.escape(tr(lang, 'admin.clients.create'))}</a>
      </div>
    </div>
    {search_form}
    {table}
    """

    response = HTMLResponse(_wrap_page(request, content, title="Admin — Clients", active="clients", page_lang=lang))
    issue_csrf_token(request, response, csrf_token)
    return response


@router.get("/v1/admin/ui/clients/new", response_class=HTMLResponse)
async def admin_clients_new_form(
    request: Request,
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    csrf_token = get_csrf_token(request)
    content = _render_client_form(None, lang, render_csrf_input(csrf_token))
    response = HTMLResponse(_wrap_page(request, content, title="Admin — New Client", active="clients", page_lang=lang))
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/clients/new", response_class=HTMLResponse)
async def admin_clients_create(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    name = (form.get("name") or "").strip() or None
    phone = (form.get("phone") or "").strip() or None
    email = (form.get("email") or "").strip()
    address = (form.get("address") or "").strip() or None
    notes = (form.get("notes") or "").strip() or None

    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required")

    client = ClientUser(
        name=name,
        phone=phone,
        email=email,
        address=address,
        notes=notes,
        org_id=org_id,
    )
    session.add(client)
    await session.flush()

    await audit_service.record_action(
        session,
        identity=identity,
        action="CREATE_CLIENT",
        resource_type="client",
        resource_id=None,
        before=None,
        after={
            "name": name,
            "phone": phone,
            "email": email,
            "address": address,
            "notes": notes,
        },
    )
    await session.commit()
    return RedirectResponse("/v1/admin/ui/clients", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/v1/admin/ui/clients/{client_id}", response_class=HTMLResponse)
async def admin_clients_edit_form(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_admin),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    tags = parse_tags_json(client.tags_json)
    note_filter_raw = (request.query_params.get("note_type") or "all").strip().lower()
    note_filter_options = {
        "all": None,
        "note": ClientNote.NOTE_TYPE_NOTE,
        "complaint": ClientNote.NOTE_TYPE_COMPLAINT,
        "praise": ClientNote.NOTE_TYPE_PRAISE,
    }
    note_filter = note_filter_raw if note_filter_raw in note_filter_options else "all"
    note_type_default = note_filter_options[note_filter] or ClientNote.NOTE_TYPE_NOTE
    bookings = (
        await session.execute(
            select(Booking)
            .where(Booking.client_id == client_id, Booking.org_id == org_id)
            .options(
                selectinload(Booking.team),
                selectinload(Booking.assigned_worker),
                selectinload(Booking.worker_assignments).selectinload(BookingWorker.worker),
            )
            .order_by(Booking.starts_at.desc())
            .limit(50)
        )
    ).scalars().all()
    booking_stats = await _client_booking_stats(session, org_id=org_id, client_id=client_id)
    weekly_series = await _client_booking_time_series(
        session, org_id=org_id, client_id=client_id, period="week"
    )
    monthly_series = await _client_booking_time_series(
        session, org_id=org_id, client_id=client_id, period="month"
    )
    frequency_stats = await _client_booking_frequency_stats(
        session, org_id=org_id, client_id=client_id
    )
    favorite_workers = await _client_favorite_workers(session, org_id=org_id, client_id=client_id)
    feedback_summary = await _client_feedback_summary(session, org_id=org_id, client_id=client_id)
    risk_summary = await _client_risk_summary(session, org_id=org_id, client_id=client_id)
    recent_feedback = await _client_recent_feedback(session, org_id=org_id, client_id=client_id)
    service_preferences = await _client_service_preferences(session, org_id=org_id, client_id=client_id)
    finance_summary = await _client_finance_aggregates(session, org_id=org_id, client_id=client_id)
    invoice_history = await _client_invoice_history(session, org_id=org_id, client_id=client_id)
    payment_history = await _client_payment_history(session, org_id=org_id, client_id=client_id)
    last_booking = bookings[0].starts_at if bookings else None
    notes_query = select(ClientNote).where(ClientNote.client_id == client_id, ClientNote.org_id == org_id)
    note_filter_value = note_filter_options[note_filter]
    if note_filter_value:
        notes_query = notes_query.where(ClientNote.note_type == note_filter_value)
    notes = (
        await session.execute(notes_query.order_by(ClientNote.created_at.desc()).limit(10))
    ).scalars().all()
    addresses = (
        await session.execute(
            select(ClientAddress)
            .where(ClientAddress.client_id == client_id, ClientAddress.org_id == org_id)
            .order_by(ClientAddress.created_at.desc())
        )
    ).scalars().all()
    address_ids = [address.address_id for address in addresses]
    usage_counts = {address_id: 0 for address_id in address_ids}
    if address_ids:
        usage_rows = (
            await session.execute(
                select(Booking.address_id, func.count())
                .where(Booking.org_id == org_id, Booking.address_id.in_(address_ids))
                .group_by(Booking.address_id)
            )
        ).all()
        usage_counts.update(
            {address_id: int(count or 0) for address_id, count in usage_rows if address_id}
        )

    csrf_token = get_csrf_token(request)
    csrf_input = render_csrf_input(csrf_token)
    address_cards = []
    for address in addresses:
        usage_count = usage_counts.get(address.address_id)
        usage_label = tr(lang, "admin.clients.addresses_usage", count=usage_count or 0)
        notes_html = (
            f'<div class="muted">{html.escape(address.notes)}</div>' if address.notes else ""
        )
        archive_badge = (
            ""
            if address.is_active
            else f'<span class="badge">{html.escape(tr(lang, "admin.clients.addresses_archived_badge"))}</span>'
        )
        use_link = (
            ""
            if not address.is_active
            else (
                f'<a class="btn small" href="/v1/admin/ui/bookings/new?client_id={html.escape(client.client_id)}'
                f'&address_id={address.address_id}">{html.escape(tr(lang, "admin.clients.addresses_use"))}</a>'
            )
        )
        archive_action = "archive" if address.is_active else "unarchive"
        archive_label = (
            tr(lang, "admin.clients.addresses_archive")
            if address.is_active
            else tr(lang, "admin.clients.addresses_unarchive")
        )
        address_cards.append(
            f"""
            <div class="card" style="padding: var(--space-md);">
              <div class="card-row">
                <div>
                  <div class="title">{html.escape(address.label)}</div>
                  <div class="muted">{html.escape(address.address_text)}</div>
                  {notes_html}
                  <div class="muted">{html.escape(usage_label)}</div>
                  {archive_badge}
                </div>
                <div class="actions">
                  {use_link}
                  <form method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/addresses/{address.address_id}/{archive_action}">
                    {csrf_input}
                    <button class="btn secondary small" type="submit">{html.escape(archive_label)}</button>
                  </form>
                </div>
              </div>
              <form class="stack" method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/addresses/{address.address_id}/update">
                <div class="form-group">
                  <label>{html.escape(tr(lang, "admin.clients.addresses_label_label"))}</label>
                  <input class="input" type="text" name="label" list="client-address-labels" value="{html.escape(address.label)}" required />
                </div>
                <div class="form-group">
                  <label>{html.escape(tr(lang, "admin.clients.addresses_label_address"))}</label>
                  <input class="input" type="text" name="address_text" value="{html.escape(address.address_text)}" required />
                </div>
                <div class="form-group">
                  <label>{html.escape(tr(lang, "admin.clients.addresses_label_notes"))}</label>
                  <textarea class="input" name="notes" rows="2">{html.escape(address.notes or "")}</textarea>
                </div>
                {csrf_input}
                <button class="btn secondary" type="submit">{html.escape(tr(lang, "admin.clients.addresses_update"))}</button>
              </form>
            </div>
            """
        )
    address_cards_html = "".join(address_cards) or f'<div class="muted">{html.escape(tr(lang, "admin.clients.addresses_empty"))}</div>'
    status_label = (
        html.escape(tr(lang, "admin.clients.status_active"))
        if client.is_active
        else html.escape(tr(lang, "admin.clients.status_archived"))
    )
    blocked_label = (
        html.escape(tr(lang, "admin.clients.status_blocked"))
        if client.is_blocked
        else html.escape(tr(lang, "admin.clients.status_unblocked"))
    )
    block_action = "unblock" if client.is_blocked else "block"
    block_label = (
        html.escape(tr(lang, "admin.clients.unblock"))
        if client.is_blocked
        else html.escape(tr(lang, "admin.clients.block"))
    )
    tags_input_value = html.escape(", ".join(tags))
    booking_currency = settings.deposit_currency.upper()
    finance_currency_code = finance_summary.get("currency_code") or booking_currency
    finance_currency_mixed = bool(finance_summary.get("currency_mixed"))
    finance_currency_source = finance_summary.get("currency_source") or "completed_bookings"
    finance_currency_display = (
        tr(lang, "admin.clients.finance_currency_mixed")
        if finance_currency_mixed
        else finance_currency_code
    )
    finance_currency_proxy = (
        tr(lang, "admin.clients.finance_currency_proxy_suffix")
        if finance_currency_source == "completed_bookings"
        else ""
    )
    finance_currency_label = (
        f"{tr(lang, 'admin.clients.finance_currency_label')}: "
        f"{finance_currency_display}{(' ' + finance_currency_proxy) if finance_currency_proxy else ''}"
    )
    finance_currency_warning = (
        f"<div class=\"muted\">⚠️ {html.escape(tr(lang, 'admin.clients.finance_currency_warning'))}</div>"
        if finance_currency_mixed
        else ""
    )
    bookings_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(_format_dt(booking.starts_at))}</td>
          <td>{html.escape(booking.status)}</td>
          <td>{html.escape(str(booking.duration_minutes))}</td>
          <td>{html.escape(_format_money(booking.base_charge_cents, booking_currency)) if booking.base_charge_cents else "—"}</td>
          <td>{html.escape(booking.team.name if booking.team else "—")}</td>
          <td>{html.escape(_format_booking_workers(booking))}</td>
          <td><a class="btn small" href="/v1/admin/ui/bookings/{html.escape(booking.booking_id)}/edit">{html.escape(tr(lang, "admin.clients.bookings_view"))}</a></td>
        </tr>
        """
        for booking in bookings
    )
    def _format_finance_amount(cents: int) -> str:
        if finance_currency_mixed:
            return f"{cents / 100:,.2f}"
        return _format_money(cents, finance_currency_code)

    ltv_display = _format_finance_amount(finance_summary["ltv_cents"]) if finance_summary["ltv_cents"] > 0 else "—"
    avg_display = (
        _format_finance_amount(finance_summary["avg_check_cents"]) if finance_summary["avg_basis"] > 0 else "—"
    )
    complaint_count = risk_summary["complaint_count"]
    avg_recent_rating = risk_summary["avg_rating"]
    low_rating_count_recent = risk_summary["low_rating_count"]
    last_completed_at = frequency_stats["last_completed_at"]
    if isinstance(last_completed_at, datetime):
        last_completed_at = _ensure_timezone(last_completed_at)
    days_since_last_completed = (
        int((datetime.now(tz=timezone.utc) - last_completed_at).total_seconds() / 86400)
        if isinstance(last_completed_at, datetime)
        else None
    )
    churn_assessment = client_service.evaluate_churn(
        days_since_last_completed=days_since_last_completed,
        avg_gap_days=frequency_stats["avg_gap_days"],
        complaint_count=int(complaint_count or 0),
        avg_rating=avg_recent_rating,
        low_rating_count=int(low_rating_count_recent or 0),
    )
    churn_badge = _churn_badge(churn_assessment.risk_band, lang)
    churn_reasons_html = (
        "<ul>" + "".join(f"<li>{html.escape(reason)}</li>" for reason in churn_assessment.reasons) + "</ul>"
        if churn_assessment.reasons
        else f'<div class="muted">{html.escape(tr(lang, "admin.clients.churn_no_signals"))}</div>'
    )
    frequent_complaints = complaint_count >= settings.client_risk_complaints_threshold
    low_rater = (
        (avg_recent_rating is not None and avg_recent_rating <= settings.client_risk_avg_rating_threshold)
        or low_rating_count_recent >= settings.client_risk_low_rating_count_threshold
    )
    risk_badges: list[str] = []
    risk_details: list[str] = []
    if frequent_complaints:
        risk_badges.append(
            f'<span class="badge">{html.escape(tr(lang, "admin.clients.risk_badge_frequent_complaints"))}</span>'
        )
        risk_details.append(
            tr(
                lang,
                "admin.clients.risk_detail_complaints",
                days=settings.client_risk_complaints_window_days,
                count=complaint_count,
                threshold=settings.client_risk_complaints_threshold,
            )
        )
    if low_rater:
        risk_badges.append(
            f'<span class="badge">{html.escape(tr(lang, "admin.clients.risk_badge_low_ratings"))}</span>'
        )
        avg_recent_display = "—" if avg_recent_rating is None else f"{avg_recent_rating:.1f}/5"
        risk_details.append(
            tr(
                lang,
                "admin.clients.risk_detail_avg_rating",
                days=settings.client_risk_feedback_window_days,
                avg=avg_recent_display,
                threshold=f"{settings.client_risk_avg_rating_threshold:.1f}/5",
            )
        )
        risk_details.append(
            tr(
                lang,
                "admin.clients.risk_detail_low_ratings",
                low_threshold=settings.client_risk_low_rating_threshold,
                days=settings.client_risk_feedback_window_days,
                count=low_rating_count_recent,
                threshold=settings.client_risk_low_rating_count_threshold,
            )
        )
    if not risk_badges:
        risk_badges.append(
            f'<span class="muted">{html.escape(tr(lang, "admin.clients.risk_none_badge"))}</span>'
        )
        risk_details.append(tr(lang, "admin.clients.risk_none_detail"))
    risk_badges_html = "".join(risk_badges)
    risk_details_html = "".join(f'<div class="muted">{html.escape(detail)}</div>' for detail in risk_details)
    balance_details: list[str] = []
    if finance_summary["invoice_count"] > 0:
        if finance_summary["outstanding_cents"] > 0:
            balance_details.append(
                f"{html.escape(tr(lang, 'admin.clients.finance_outstanding'))}: "
                f"{html.escape(_format_finance_amount(finance_summary['outstanding_cents']))}"
            )
        if finance_summary["overpaid_cents"] > 0:
            balance_details.append(
                f"{html.escape(tr(lang, 'admin.clients.finance_overpaid'))}: "
                f"{html.escape(_format_finance_amount(finance_summary['overpaid_cents']))}"
            )
        if not balance_details:
            balance_details.append(
                f"{html.escape(tr(lang, 'admin.clients.finance_balance'))}: "
                f"{html.escape(_format_finance_amount(0))}"
            )
        if finance_summary["unpaid_invoice_count"] > 0:
            balance_details.append(
                f"{html.escape(tr(lang, 'admin.clients.finance_unpaid_invoices'))}: "
                f"{finance_summary['unpaid_invoice_count']}"
            )
        balance_display = " · ".join(balance_details)
    else:
        balance_display = html.escape(tr(lang, "admin.clients.finance_balance_na"))
    invoice_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(_format_date(invoice.issue_date))}</td>
          <td>{_status_badge(invoice.status)}</td>
          <td>{html.escape(_format_money(invoice.total_cents, invoice.currency))}</td>
          <td><a href="/v1/admin/ui/invoices/{html.escape(invoice.invoice_id)}">{html.escape(invoice.invoice_number)}</a></td>
        </tr>
        """
        for invoice in invoice_history
    )
    invoice_table = (
        f"""
        <table class="table">
          <thead>
            <tr>
              <th>{html.escape(tr(lang, "admin.clients.finance_date"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.finance_status"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.finance_amount"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.finance_invoice"))}</th>
            </tr>
          </thead>
          <tbody>
            {invoice_rows}
          </tbody>
        </table>
        """
        if invoice_rows
        else f"<div class=\"muted\">{html.escape(tr(lang, 'admin.clients.finance_invoices_none'))}</div>"
    )
    payment_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(_format_dt(payment.received_at or payment.created_at))}</td>
          <td><span class="badge">{html.escape(payment.status)}</span></td>
          <td>{html.escape(_format_money(payment.amount_cents, payment.currency))}</td>
          <td>
            {f'<a href="/v1/admin/ui/invoices/{html.escape(payment.invoice_id)}">{html.escape(invoice_number)}</a>' if payment.invoice_id and invoice_number else "—"}
          </td>
        </tr>
        """
        for payment, invoice_number in payment_history
    )
    payment_table = (
        f"""
        <table class="table">
          <thead>
            <tr>
              <th>{html.escape(tr(lang, "admin.clients.finance_date"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.finance_status"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.finance_amount"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.finance_invoice"))}</th>
            </tr>
          </thead>
          <tbody>
            {payment_rows}
          </tbody>
        </table>
        """
        if payment_rows
        else f"<div class=\"muted\">{html.escape(tr(lang, 'admin.clients.finance_payments_none'))}</div>"
    )
    finance_card = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.finance_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.finance_hint"))}</div>
          <div class="muted">{html.escape(finance_currency_label)}</div>
          {finance_currency_warning}
        </div>
      </div>
      <div style="display: grid; gap: var(--space-md); grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));">
        <div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.finance_ltv"))}</div>
          <div class="title">{html.escape(ltv_display)}</div>
        </div>
        <div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.finance_avg_check"))}</div>
          <div class="title">{html.escape(avg_display)}</div>
        </div>
        <div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.finance_balance"))}</div>
          <div>{balance_display}</div>
        </div>
      </div>
      <div class="stack" style="margin-top: var(--space-md);">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.finance_invoices_title"))}</div>
          {invoice_table}
        </div>
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.finance_payments_title"))}</div>
          {payment_table}
        </div>
      </div>
    </div>
    """
    bookings_table = (
        f"""
        <table class="table">
          <thead>
            <tr>
              <th>{html.escape(tr(lang, "admin.clients.bookings_date"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.bookings_status"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.bookings_duration"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.bookings_amount"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.bookings_team"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.bookings_workers"))}</th>
              <th>{html.escape(tr(lang, "admin.clients.bookings_actions"))}</th>
            </tr>
          </thead>
          <tbody>
            {bookings_rows}
          </tbody>
        </table>
        """
        if bookings_rows
        else f"<div class=\"muted\">{html.escape(tr(lang, 'admin.clients.bookings_none'))}</div>"
    )
    avg_rating = feedback_summary["avg_rating"]
    avg_rating_display = "—" if avg_rating is None else f"{avg_rating:.1f}/5"
    rating_count = feedback_summary["rating_count"]
    low_rating_count = feedback_summary["low_rating_count"]
    feedback_rows = []
    for feedback, booking in recent_feedback:
        feedback_rows.append(
            """
            <tr>
              <td>{rating}</td>
              <td>{comment}</td>
              <td>{booking_date}</td>
              <td><a class="btn small" href="/v1/admin/ui/bookings/{booking_id}/edit">{view_label}</a></td>
            </tr>
            """.format(
                rating=html.escape(f"{feedback.rating}/5"),
                comment=html.escape(feedback.comment or "—"),
                booking_date=html.escape(_format_dt(booking.starts_at)),
                booking_id=html.escape(feedback.booking_id),
                view_label=html.escape(tr(lang, "admin.clients.feedback_view_booking")),
            )
        )
    feedback_table = (
        "<table class=\"table\"><thead><tr>"
        f"<th>{html.escape(tr(lang, 'admin.clients.feedback_table_rating'))}</th>"
        f"<th>{html.escape(tr(lang, 'admin.clients.feedback_table_comment'))}</th>"
        f"<th>{html.escape(tr(lang, 'admin.clients.feedback_table_booking_date'))}</th>"
        f"<th>{html.escape(tr(lang, 'admin.clients.feedback_table_booking'))}</th>"
        "</tr></thead><tbody>"
        f"{''.join(feedback_rows)}"
        "</tbody></table>"
        if feedback_rows
        else _render_empty(tr(lang, "admin.clients.feedback_none"))
    )
    booking_options = "".join(
        f"<option value=\"{html.escape(booking.booking_id)}\">"
        f"{html.escape(_format_dt(booking.starts_at))} · {html.escape(booking.status)}"
        "</option>"
        for booking in bookings
    )
    feedback_form = (
        f"""
        <form class="stack" method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/feedback/create">
          <div class="form-group">
            <label>{html.escape(tr(lang, "admin.clients.feedback_form_booking_label"))}</label>
            <select class="input" name="booking_id" required>
              {booking_options}
            </select>
          </div>
          <div class="form-group">
            <label>{html.escape(tr(lang, "admin.clients.feedback_form_rating_label"))}</label>
            <select class="input" name="rating" required>
              <option value="5">5</option>
              <option value="4">4</option>
              <option value="3">3</option>
              <option value="2">2</option>
              <option value="1">1</option>
            </select>
          </div>
          <div class="form-group">
            <label>{html.escape(tr(lang, "admin.clients.feedback_form_comment_label"))}</label>
            <textarea class="input" name="comment" rows="2" placeholder="{html.escape(tr(lang, 'admin.clients.feedback_form_comment_placeholder'))}"></textarea>
          </div>
          {csrf_input}
          <button class="btn secondary" type="submit">{html.escape(tr(lang, "admin.clients.feedback_form_submit"))}</button>
        </form>
        """
        if booking_options
        else f"<div class=\"muted\">{html.escape(tr(lang, 'admin.clients.feedback_form_no_bookings'))}</div>"
    )
    feedback_card = f"""
    <div class="card" id="client-feedback">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.feedback_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.feedback_subtitle"))}</div>
        </div>
      </div>
      <div style="display: grid; gap: var(--space-md); grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));">
        <div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.feedback_avg_rating"))}</div>
          <div class="title">{html.escape(avg_rating_display)}</div>
        </div>
        <div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.feedback_total_ratings"))}</div>
          <div class="title">{rating_count}</div>
        </div>
        <div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.feedback_low_ratings"))}</div>
          <div class="title">{low_rating_count}</div>
        </div>
      </div>
      <div class="stack" style="margin-top: var(--space-md);">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.feedback_recent_title"))}</div>
          {feedback_table}
        </div>
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.feedback_add_title"))}</div>
          {feedback_form}
        </div>
      </div>
    </div>
    """
    notes_list = "".join(
        f"""
        <div class="card" style="padding: var(--space-md);">
          <div class="muted">{html.escape(_format_dt(note.created_at))}{' · ' + html.escape(note.created_by) if note.created_by else ''}</div>
          <div class="with-icon">
            <span class="badge {_note_type_badge_class(note.note_type)}">{html.escape(_note_type_label(note.note_type, lang))}</span>
            <span>{html.escape(note.note_text)}</span>
          </div>
        </div>
        """
        for note in notes
    )
    notes_block = notes_list or f"<div class=\"muted\">{html.escape(tr(lang, 'admin.clients.notes_none'))}</div>"
    notes_filter = f"""
      <form class="filters" method="get" action="/v1/admin/ui/clients/{html.escape(client.client_id)}">
        <div class="form-group">
          <label>{html.escape(tr(lang, "admin.clients.notes_filter_label"))}</label>
          <select class="input" name="note_type">
            <option value="all" {'selected' if note_filter == 'all' else ''}>{html.escape(tr(lang, "admin.clients.notes_filter_all"))}</option>
            <option value="note" {'selected' if note_filter == 'note' else ''}>{html.escape(tr(lang, "admin.clients.notes_filter_note"))}</option>
            <option value="complaint" {'selected' if note_filter == 'complaint' else ''}>{html.escape(tr(lang, "admin.clients.notes_filter_complaint"))}</option>
            <option value="praise" {'selected' if note_filter == 'praise' else ''}>{html.escape(tr(lang, "admin.clients.notes_filter_praise"))}</option>
          </select>
        </div>
        <button class="btn secondary" type="submit">{html.escape(tr(lang, "admin.clients.notes_filter_apply"))}</button>
      </form>
    """
    if settings.chat_enabled:
        chat_action = (
            f'<a class="btn secondary" href="/v1/admin/ui/clients/{html.escape(client.client_id)}/chat">'
            f"{html.escape(tr(lang, 'admin.clients.quick_actions_chat_button'))}</a>"
        )
        chat_hint = ""
    else:
        chat_action = (
            f'<button class="btn secondary" type="button" disabled>'
            f"{html.escape(tr(lang, 'admin.clients.quick_actions_chat_disabled'))}"
            "</button>"
        )
        chat_hint = f'<div class="muted small">{html.escape(tr(lang, "admin.clients.quick_actions_coming_soon"))}</div>'

    if settings.promos_enabled:
        promo_action = (
            f'<a class="btn secondary" href="/v1/admin/ui/clients/{html.escape(client.client_id)}/promos">'
            f"{html.escape(tr(lang, 'admin.clients.quick_actions_promo_button'))}</a>"
        )
        promo_hint = ""
    else:
        promo_action = (
            f'<button class="btn secondary" type="button" disabled>'
            f"{html.escape(tr(lang, 'admin.clients.quick_actions_promo_disabled'))}"
            "</button>"
        )
        promo_hint = f'<div class="muted small">{html.escape(tr(lang, "admin.clients.quick_actions_coming_soon"))}</div>'

    quick_actions_card = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.quick_actions"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.quick_actions_hint"))}</div>
        </div>
      </div>
      <div style="display: grid; gap: var(--space-md); grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));">
        <div class="stack">
          <div class="title">{html.escape(tr(lang, "admin.clients.quick_actions_chat_title"))}</div>
          {chat_action}
          {chat_hint}
        </div>
        <div class="stack">
          <div class="title">{html.escape(tr(lang, "admin.clients.quick_actions_promo_title"))}</div>
          {promo_action}
          {promo_hint}
        </div>
      </div>
    </div>
    """

    def _render_time_series(title: str, series: list[dict[str, int | str]]) -> str:
        max_count = max((int(item["count"]) for item in series), default=0)
        rows = []
        for item in series:
            count = int(item["count"])
            percent = int(round((count / max_count) * 100)) if max_count else 0
            rows.append(
                """
                <div style="display: flex; align-items: center; gap: var(--space-sm);">
                  <div class="muted" style="min-width: 70px;">{label}</div>
                  <div style="flex: 1; background: var(--color-surface-muted); height: 8px; border-radius: 999px; overflow: hidden;">
                    <div style="width: {percent}%; background: var(--color-primary); height: 100%;"></div>
                  </div>
                  <div class="muted" style="min-width: 24px; text-align: right;">{count}</div>
                </div>
                """.format(
                    label=html.escape(str(item["label"])),
                    percent=percent,
                    count=count,
                )
            )
        rows_html = (
            "".join(rows)
            if rows
            else f'<div class="muted">{html.escape(tr(lang, "admin.clients.analytics_no_bookings"))}</div>'
        )
        return f"""
        <div class="stack">
          <div class="muted">{html.escape(title)}</div>
          <div class="stack">
            {rows_html}
          </div>
        </div>
        """

    preference_sections = []
    if service_preferences["service_types"]:
        preference_sections.append(
            _render_time_series(
                tr(lang, "admin.clients.preferences_top_service_types"),
                service_preferences["service_types"],
            )
        )
    if service_preferences["addons"]:
        preference_sections.append(
            _render_time_series(
                tr(lang, "admin.clients.preferences_top_addons"),
                service_preferences["addons"],
            )
        )
    preferences_html = (
        "".join(preference_sections)
        if preference_sections
        else f'<div class="muted">{html.escape(tr(lang, "admin.clients.preferences_empty"))}</div>'
    )

    avg_gap_days = frequency_stats["avg_gap_days"]
    avg_gap_display = (
        "—"
        if avg_gap_days is None
        else tr(lang, "admin.clients.analytics_avg_gap_value", value=f"{avg_gap_days:.1f}")
    )
    last_booking_display = (
        html.escape(_format_dt(frequency_stats["last_booking_at"]))
        if frequency_stats["last_booking_at"]
        else "—"
    )
    favorite_workers_rows = "".join(
        """
        <div class="card" style="padding: var(--space-md);">
          <div class="title">
            <a href="/v1/admin/ui/workers/{worker_id}">{name}</a>
          </div>
          <div class="muted">
            {summary}
          </div>
        </div>
        """.format(
            worker_id=html.escape(str(worker["worker_id"])),
            name=html.escape(str(worker["name"])),
            summary=html.escape(
                tr(
                    lang,
                    "admin.clients.analytics_completed_summary",
                    count=worker["completed_count"],
                    minutes=worker["total_minutes"],
                    revenue=(
                        _format_money(worker["total_revenue_cents"], booking_currency)
                        if worker["total_revenue_cents"]
                        else "—"
                    ),
                )
            ),
        )
        for worker in favorite_workers
    )
    favorite_workers_html = (
        f"<div class=\"stack\">{favorite_workers_rows}</div>"
        if favorite_workers_rows
        else f"<div class=\"muted\">{html.escape(tr(lang, 'admin.clients.analytics_no_completed_bookings'))}</div>"
    )
    analytics_card = f"""
    <div class="card" id="client-analytics">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.analytics_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.analytics_subtitle"))}</div>
        </div>
      </div>
      <div class="stack" style="gap: var(--space-lg);">
        <div class="stack">
          <div class="title">{html.escape(tr(lang, "admin.clients.analytics_bookings_over_time"))}</div>
          {_render_time_series(tr(lang, "admin.clients.analytics_last_12_weeks"), weekly_series)}
          {_render_time_series(tr(lang, "admin.clients.analytics_last_12_months"), monthly_series)}
        </div>
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.analytics_frequency_stats"))}</div>
          <div style="display: grid; gap: var(--space-md); grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));">
            <div>
              <div class="muted">{html.escape(tr(lang, "admin.clients.analytics_total_bookings"))}</div>
              <div class="title">{frequency_stats["total"]}</div>
            </div>
            <div>
              <div class="muted">{html.escape(tr(lang, "admin.clients.analytics_last_30_days"))}</div>
              <div class="title">{frequency_stats["last_30"]}</div>
            </div>
            <div>
              <div class="muted">{html.escape(tr(lang, "admin.clients.analytics_last_90_days"))}</div>
              <div class="title">{frequency_stats["last_90"]}</div>
            </div>
            <div>
              <div class="muted">{html.escape(tr(lang, "admin.clients.analytics_avg_gap_days"))}</div>
              <div class="title">{html.escape(avg_gap_display)}</div>
            </div>
            <div>
              <div class="muted">{html.escape(tr(lang, "admin.clients.analytics_last_booking_date"))}</div>
              <div class="title">{last_booking_display}</div>
            </div>
          </div>
        </div>
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.analytics_churn_risk_title"))}</div>
          <div class="stack">
            <div>{churn_badge}</div>
            {churn_reasons_html}
          </div>
        </div>
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.analytics_service_preferences"))}</div>
          <div class="stack">
            {preferences_html}
          </div>
        </div>
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.analytics_favorite_workers"))}</div>
          {favorite_workers_html}
        </div>
      </div>
    </div>
    """
    overview_card = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title with-icon">{_icon('users')}{html.escape(tr(lang, "admin.clients.details_title"))}</div>
          <div class="muted">{status_label} · {blocked_label}</div>
        </div>
        <div class="actions">
          <a class="btn" href="/v1/admin/ui/bookings/new?client_id={html.escape(client.client_id)}">{html.escape(tr(lang, "admin.clients.create_booking"))}</a>
          <form method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/{block_action}">
            {csrf_input}
            <button class="btn secondary" type="submit">{block_label}</button>
          </form>
          <a class="btn secondary" href="#client-notes">{html.escape(tr(lang, "admin.clients.notes_add"))}</a>
        </div>
      </div>
      <div class="stack">
        <div><strong>{html.escape(tr(lang, "admin.clients.name"))}:</strong> {html.escape(client.name or "—")}</div>
        <div><strong>{html.escape(tr(lang, "admin.clients.phone"))}:</strong> {html.escape(client.phone or "—")}</div>
        <div><strong>{html.escape(tr(lang, "admin.clients.email"))}:</strong> {html.escape(client.email or "—")}</div>
        <div><strong>{html.escape(tr(lang, "admin.clients.registered_at"))}:</strong> {html.escape(_format_dt(client.created_at))}</div>
        <div><strong>{html.escape(tr(lang, "admin.clients.last_booking"))}:</strong> {html.escape(_format_dt(last_booking))}</div>
        <div class="stack" style="margin-top: var(--space-sm);">
          <div><strong>{html.escape(tr(lang, "admin.clients.risk_flags_label"))}</strong></div>
          <div style="display: flex; gap: var(--space-xs); flex-wrap: wrap;">{risk_badges_html}</div>
          {risk_details_html}
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.tags_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.tags_hint"))}</div>
        </div>
      </div>
      {_format_client_tags(tags, lang)}
      <form class="stack" method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/tags/update">
        <input class="input" type="text" name="tags" value="{tags_input_value}" />
        {csrf_input}
        <button class="btn secondary" type="submit">{html.escape(tr(lang, "admin.clients.tags_save"))}</button>
      </form>
    </div>
    {quick_actions_card}
    {analytics_card}
    <div class="card" id="client-addresses">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.addresses_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.addresses_hint"))}</div>
        </div>
      </div>
      <datalist id="client-address-labels">
        <option value="{html.escape(tr(lang, 'admin.clients.addresses_label_home'))}"></option>
        <option value="{html.escape(tr(lang, 'admin.clients.addresses_label_work'))}"></option>
        <option value="{html.escape(tr(lang, 'admin.clients.addresses_label_cottage'))}"></option>
        <option value="{html.escape(tr(lang, 'admin.clients.addresses_label_custom'))}"></option>
      </datalist>
      <div class="stack">
        {address_cards_html}
      </div>
      <form class="stack" method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/addresses/create">
        <div class="form-group">
          <label>{html.escape(tr(lang, "admin.clients.addresses_label_label"))}</label>
          <input class="input" type="text" name="label" list="client-address-labels" placeholder="{html.escape(tr(lang, 'admin.clients.addresses_placeholder_label'))}" required />
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, "admin.clients.addresses_label_address"))}</label>
          <input class="input" type="text" name="address_text" placeholder="{html.escape(tr(lang, 'admin.clients.addresses_placeholder_address'))}" required />
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, "admin.clients.addresses_label_notes"))}</label>
          <textarea class="input" name="notes" rows="2" placeholder="{html.escape(tr(lang, 'admin.clients.addresses_placeholder_notes'))}"></textarea>
        </div>
        {csrf_input}
        <button class="btn secondary" type="submit">{html.escape(tr(lang, "admin.clients.addresses_add"))}</button>
      </form>
    </div>
    {finance_card}
    {feedback_card}
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.bookings_title"))}</div>
          <div class="muted">
            {html.escape(tr(lang, "admin.clients.bookings_total"))}: {booking_stats["total"]}
            · {html.escape(tr(lang, "admin.clients.bookings_completed"))}: {booking_stats["completed"]}
            · {html.escape(tr(lang, "admin.clients.bookings_cancelled"))}: {booking_stats["cancelled"]}
          </div>
        </div>
      </div>
      {bookings_table}
    </div>
    <div class="card" id="client-notes">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(tr(lang, "admin.clients.notes_title"))}</div>
          <div class="muted">{html.escape(tr(lang, "admin.clients.notes_hint"))}</div>
        </div>
      </div>
      {notes_filter}
      <div class="stack">
        {notes_block}
      </div>
      <form class="stack" method="post" action="/v1/admin/ui/clients/{html.escape(client.client_id)}/notes/create">
        <input type="hidden" name="note_type_filter" value="{html.escape(note_filter)}" />
        <div class="form-group">
          <label>{html.escape(tr(lang, "admin.clients.note_type_label"))}</label>
          <select class="input" name="note_type" id="client-note-type">
            <option value="{ClientNote.NOTE_TYPE_NOTE}" {'selected' if note_type_default == ClientNote.NOTE_TYPE_NOTE else ''}>{html.escape(tr(lang, "admin.clients.note_type_note"))}</option>
            <option value="{ClientNote.NOTE_TYPE_COMPLAINT}" {'selected' if note_type_default == ClientNote.NOTE_TYPE_COMPLAINT else ''}>{html.escape(tr(lang, "admin.clients.note_type_complaint"))}</option>
            <option value="{ClientNote.NOTE_TYPE_PRAISE}" {'selected' if note_type_default == ClientNote.NOTE_TYPE_PRAISE else ''}>{html.escape(tr(lang, "admin.clients.note_type_praise"))}</option>
          </select>
        </div>
        <div class="actions">
          <button class="btn secondary" type="button" onclick="document.getElementById('client-note-type').value='{ClientNote.NOTE_TYPE_NOTE}';document.getElementById('client-note-text').focus();">{html.escape(tr(lang, "admin.clients.note_type_note"))}</button>
          <button class="btn secondary" type="button" onclick="document.getElementById('client-note-type').value='{ClientNote.NOTE_TYPE_COMPLAINT}';document.getElementById('client-note-text').focus();">{html.escape(tr(lang, "admin.clients.note_type_complaint"))}</button>
          <button class="btn secondary" type="button" onclick="document.getElementById('client-note-type').value='{ClientNote.NOTE_TYPE_PRAISE}';document.getElementById('client-note-text').focus();">{html.escape(tr(lang, "admin.clients.note_type_praise"))}</button>
        </div>
        <textarea class="input" name="note_text" id="client-note-text" rows="3" placeholder="{html.escape(tr(lang, "admin.clients.notes_placeholder"))}"></textarea>
        {csrf_input}
        <button class="btn secondary" type="submit">{html.escape(tr(lang, "admin.clients.notes_add"))}</button>
      </form>
    </div>
    """
    content = (
        overview_card
        + _render_client_form(client, lang, csrf_input)
        + _render_client_danger_zone(client, lang, csrf_input)
    )
    response = HTMLResponse(
        _wrap_page(
            request,
            content,
            title="Admin — Edit Client",
            active="clients",
            page_lang=lang,
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response


def _render_client_quick_action_page(
    request: Request,
    *,
    title: str,
    heading: str,
    message: str,
    back_label: str,
    client_id: str,
    lang: str,
    csrf_token: str,
) -> HTMLResponse:
    content = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{html.escape(heading)}</div>
          <div class="muted">{html.escape(message)}</div>
        </div>
        <a class="btn secondary" href="/v1/admin/ui/clients/{html.escape(client_id)}">{html.escape(back_label)}</a>
      </div>
    </div>
    """
    response = HTMLResponse(_wrap_page(request, content, title=title, active="clients", page_lang=lang))
    issue_csrf_token(request, response, csrf_token)
    return response


@router.get("/v1/admin/ui/clients/{client_id}/chat", response_class=HTMLResponse)
async def admin_client_chat_stub(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_admin),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = await session.scalar(
        select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
    )
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    redirect_template = getattr(settings, "client_chat_redirect_url", None)
    if redirect_template:
        redirect_url = redirect_template.format(client_id=client.client_id)
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    csrf_token = get_csrf_token(request)
    return _render_client_quick_action_page(
        request,
        title=f"Admin — {tr(lang, 'admin.clients.chat_title')}",
        heading=tr(lang, "admin.clients.chat_title"),
        message=tr(lang, "admin.clients.chat_coming_soon"),
        back_label=tr(lang, "admin.clients.back_to_client"),
        client_id=client.client_id,
        lang=lang,
        csrf_token=csrf_token,
    )


@router.get("/v1/admin/ui/clients/{client_id}/promos", response_class=HTMLResponse)
async def admin_client_promos_stub(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_admin),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = await session.scalar(
        select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
    )
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    redirect_template = getattr(settings, "client_promos_redirect_url", None)
    if redirect_template:
        redirect_url = redirect_template.format(client_id=client.client_id)
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    csrf_token = get_csrf_token(request)
    return _render_client_quick_action_page(
        request,
        title=f"Admin — {tr(lang, 'admin.clients.promos_title')}",
        heading=tr(lang, "admin.clients.promos_title"),
        message=tr(lang, "admin.clients.promos_not_configured"),
        back_label=tr(lang, "admin.clients.back_to_client"),
        client_id=client.client_id,
        lang=lang,
        csrf_token=csrf_token,
    )


@router.post("/v1/admin/ui/clients/{client_id}", response_class=HTMLResponse)
async def admin_clients_update(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    before = {
        "name": client.name,
        "phone": client.phone,
        "email": client.email,
        "address": client.address,
        "notes": client.notes,
    }

    form = await request.form()
    client.name = (form.get("name") or "").strip() or None
    client.phone = (form.get("phone") or "").strip() or None
    client.email = (form.get("email") or client.email).strip()
    client.address = (form.get("address") or "").strip() or None
    client.notes = (form.get("notes") or "").strip() or None

    if not client.email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is required")

    await audit_service.record_action(
        session,
        identity=identity,
        action="UPDATE_CLIENT",
        resource_type="client",
        resource_id=client_id,
        before=before,
        after={
            "name": client.name,
            "phone": client.phone,
            "email": client.email,
            "address": client.address,
            "notes": client.notes,
        },
    )
    await session.commit()
    return RedirectResponse("/v1/admin/ui/clients", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/addresses/create", response_class=HTMLResponse)
async def admin_client_addresses_create(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    form = await request.form()
    label = (form.get("label") or "").strip() or "Custom"
    address_text = (form.get("address_text") or "").strip()
    notes = (form.get("notes") or "").strip() or None
    if not address_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Address is required")

    session.add(
        ClientAddress(
            org_id=org_id,
            client_id=client_id,
            label=label,
            address_text=address_text,
            notes=notes,
        )
    )
    await audit_service.record_action(
        session,
        identity=identity,
        action="CREATE_CLIENT_ADDRESS",
        resource_type="client_address",
        resource_id=None,
        before=None,
        after={
            "client_id": client_id,
            "label": label,
            "address_text": address_text,
            "notes": notes,
        },
    )
    await session.commit()
    return RedirectResponse(f"/v1/admin/ui/clients/{client_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/addresses/{address_id}/update", response_class=HTMLResponse)
async def admin_client_addresses_update(
    client_id: str,
    address_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    address = (
        await session.execute(
            select(ClientAddress).where(
                ClientAddress.address_id == address_id,
                ClientAddress.client_id == client_id,
                ClientAddress.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if address is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")

    form = await request.form()
    label = (form.get("label") or "").strip() or "Custom"
    address_text = (form.get("address_text") or "").strip()
    notes = (form.get("notes") or "").strip() or None
    if not address_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Address is required")

    before = {
        "label": address.label,
        "address_text": address.address_text,
        "notes": address.notes,
    }
    address.label = label
    address.address_text = address_text
    address.notes = notes

    await audit_service.record_action(
        session,
        identity=identity,
        action="UPDATE_CLIENT_ADDRESS",
        resource_type="client_address",
        resource_id=str(address_id),
        before=before,
        after={
            "label": label,
            "address_text": address_text,
            "notes": notes,
        },
    )
    await session.commit()
    return RedirectResponse(f"/v1/admin/ui/clients/{client_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/addresses/{address_id}/archive", response_class=HTMLResponse)
async def admin_client_addresses_archive(
    client_id: str,
    address_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    address = (
        await session.execute(
            select(ClientAddress).where(
                ClientAddress.address_id == address_id,
                ClientAddress.client_id == client_id,
                ClientAddress.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if address is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")

    before = {"is_active": address.is_active}
    address.is_active = False

    await audit_service.record_action(
        session,
        identity=identity,
        action="ARCHIVE_CLIENT_ADDRESS",
        resource_type="client_address",
        resource_id=str(address_id),
        before=before,
        after={"is_active": address.is_active},
    )
    await session.commit()
    return RedirectResponse(f"/v1/admin/ui/clients/{client_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/addresses/{address_id}/unarchive", response_class=HTMLResponse)
async def admin_client_addresses_unarchive(
    client_id: str,
    address_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    address = (
        await session.execute(
            select(ClientAddress).where(
                ClientAddress.address_id == address_id,
                ClientAddress.client_id == client_id,
                ClientAddress.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if address is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")

    before = {"is_active": address.is_active}
    address.is_active = True

    await audit_service.record_action(
        session,
        identity=identity,
        action="UNARCHIVE_CLIENT_ADDRESS",
        resource_type="client_address",
        resource_id=str(address_id),
        before=before,
        after={"is_active": address.is_active},
    )
    await session.commit()
    return RedirectResponse(f"/v1/admin/ui/clients/{client_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/tags/update", response_class=HTMLResponse)
async def admin_clients_update_tags(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    form = await request.form()
    tags = normalize_tags(form.get("tags"))
    before = {"tags_json": client.tags_json}
    client.tags_json = json.dumps(tags, ensure_ascii=False)

    await audit_service.record_action(
        session,
        identity=identity,
        action="UPDATE_CLIENT_TAGS",
        resource_type="client",
        resource_id=client_id,
        before=before,
        after={"tags_json": client.tags_json},
    )
    await session.commit()
    return RedirectResponse(f"/v1/admin/ui/clients/{client_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/notes/create", response_class=HTMLResponse)
async def admin_clients_add_note(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    form = await request.form()
    note_text = (form.get("note_text") or "").strip()
    note_type_filter_raw = (form.get("note_type_filter") or "").strip().lower()
    allowed_filters = {"all", "note", "complaint", "praise"}
    note_type_filter = note_type_filter_raw if note_type_filter_raw in allowed_filters else "all"
    try:
        note_type = normalize_note_type(form.get("note_type"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid note type",
        ) from exc
    if not note_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Note text is required")

    note = ClientNote(
        org_id=org_id,
        client_id=client_id,
        note_text=note_text,
        note_type=note_type,
        created_by=identity.username,
    )
    session.add(note)
    await session.flush()

    await audit_service.record_action(
        session,
        identity=identity,
        action="CREATE_CLIENT_NOTE",
        resource_type="client_note",
        resource_id=str(note.note_id),
        before=None,
        after={"client_id": client_id},
    )
    await session.commit()
    redirect_params = {"note_type": note_type_filter} if note_type_filter != "all" else {}
    redirect_url = f"/v1/admin/ui/clients/{client_id}"
    if redirect_params:
        redirect_url = f"{redirect_url}?{urlencode(redirect_params)}"
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/feedback/create", response_class=HTMLResponse)
async def admin_clients_add_feedback(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    form = await request.form()
    booking_id = (form.get("booking_id") or "").strip()
    rating_raw = (form.get("rating") or "").strip()
    comment = (form.get("comment") or "").strip() or None
    if not booking_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking is required")
    try:
        rating = int(rating_raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid rating") from exc
    if rating < 1 or rating > 5:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid rating")

    await _resolve_client_booking(
        session,
        org_id=org_id,
        client_id=client_id,
        booking_id=booking_id,
    )
    existing_feedback = (
        await session.execute(
            select(ClientFeedback).where(
                ClientFeedback.org_id == org_id,
                ClientFeedback.booking_id == booking_id,
            )
        )
    ).scalar_one_or_none()
    if existing_feedback is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feedback already exists for this booking",
        )

    feedback = ClientFeedback(
        org_id=org_id,
        client_id=client_id,
        booking_id=booking_id,
        rating=rating,
        comment=comment,
        channel="admin",
    )
    session.add(feedback)
    await session.flush()

    await audit_service.record_action(
        session,
        identity=identity,
        action="CREATE_CLIENT_FEEDBACK",
        resource_type="client_feedback",
        resource_id=str(feedback.feedback_id),
        before=None,
        after={"client_id": client_id, "booking_id": booking_id, "rating": rating},
    )
    await session.commit()
    return RedirectResponse(f"/v1/admin/ui/clients/{client_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/block", response_class=HTMLResponse)
async def admin_clients_block(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    before = {"is_blocked": client.is_blocked}
    if not client.is_blocked:
        client.is_blocked = True

    await audit_service.record_action(
        session,
        identity=identity,
        action="BLOCK_CLIENT",
        resource_type="client",
        resource_id=client_id,
        before=before,
        after={"is_blocked": client.is_blocked},
    )
    await session.commit()
    return RedirectResponse(f"/v1/admin/ui/clients/{client_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/unblock", response_class=HTMLResponse)
async def admin_clients_unblock(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    before = {"is_blocked": client.is_blocked}
    if client.is_blocked:
        client.is_blocked = False

    await audit_service.record_action(
        session,
        identity=identity,
        action="UNBLOCK_CLIENT",
        resource_type="client",
        resource_id=client_id,
        before=before,
        after={"is_blocked": client.is_blocked},
    )
    await session.commit()
    return RedirectResponse(f"/v1/admin/ui/clients/{client_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/archive", response_class=HTMLResponse)
async def admin_clients_archive(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    before = {"is_active": client.is_active}
    if client.is_active:
        client.is_active = False

    await audit_service.record_action(
        session,
        identity=identity,
        action="ARCHIVE_CLIENT",
        resource_type="client",
        resource_id=client_id,
        before=before,
        after={"is_active": client.is_active},
    )
    await session.commit()
    return RedirectResponse("/v1/admin/ui/clients", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/clients/{client_id}/unarchive", response_class=HTMLResponse)
async def admin_clients_unarchive(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    before = {"is_active": client.is_active}
    if not client.is_active:
        client.is_active = True

    await audit_service.record_action(
        session,
        identity=identity,
        action="UNARCHIVE_CLIENT",
        resource_type="client",
        resource_id=client_id,
        before=before,
        after={"is_active": client.is_active},
    )
    await session.commit()
    return RedirectResponse("/v1/admin/ui/clients", status_code=status.HTTP_303_SEE_OTHER)


def _render_client_delete_content(
    *,
    delete_client_id: str,
    delete_counts: dict[str, int],
    csrf_token: str,
    banner_message: str | None = None,
) -> str:
    count_rows = "".join(
        f"<li><strong>{html.escape(label.replace('_', ' ').title())}:</strong> {count}</li>"
        for label, count in delete_counts.items()
    )
    banner_block = ""
    if banner_message:
        banner_block = f"""
        <div class="card" style="border-color:#fecaca;background:#fef2f2;color:#b91c1c;">
          <strong>{html.escape(banner_message)}</strong>
        </div>
        """
    return f"""
    {banner_block}
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">Delete client permanently</div>
          <div class="muted">Choose how to handle bookings linked to this client.</div>
        </div>
      </div>
      <div class="stack">
        <div class="muted">Dependent records found:</div>
        <ul>{count_rows}</ul>
      </div>
      <form class="stack" method="post" action="/v1/admin/ui/clients/{html.escape(delete_client_id)}/delete">
        <label class="muted">Booking strategy</label>
        <label><input type="radio" name="strategy" value="detach" required /> Detach bookings (set client to empty)</label>
        <label><input type="radio" name="strategy" value="cascade" required /> Cascade delete bookings (remove all client bookings)</label>
        <input class="input" type="text" name="confirm" placeholder="DELETE" required />
        {render_csrf_input(csrf_token)}
        <button class="btn danger" type="submit">Delete permanently</button>
      </form>
    </div>
    """


@router.get("/v1/admin/ui/clients/{client_id}/delete", response_class=HTMLResponse)
async def admin_clients_delete_confirm(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_admin),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    counts = await _client_delete_counts(session, org_id=org_id, client_id=client_id)
    csrf_token = get_csrf_token(request)
    content = _render_client_delete_content(
        delete_client_id=client_id,
        delete_counts=counts,
        csrf_token=csrf_token,
    )
    response = HTMLResponse(
        _wrap_page(
            request,
            content,
            title="Admin — Delete Client",
            active="clients",
            page_lang=lang,
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/clients/{client_id}/delete", response_class=HTMLResponse)
async def admin_clients_delete(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    confirmation = (form.get("confirm") or "").strip().upper()
    strategy = (form.get("strategy") or "").strip().lower()
    if confirmation != "DELETE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deletion confirmation required")
    if strategy not in {"detach", "cascade"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid deletion strategy")

    client = (
        await session.execute(
            select(ClientUser).where(ClientUser.client_id == client_id, ClientUser.org_id == org_id)
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    counts = await _client_delete_counts(session, org_id=org_id, client_id=client_id)
    if counts.get("subscriptions", 0) > 0:
        message = "Client has subscriptions; cancel/delete them first."
        csrf_token = get_csrf_token(request)
        content = _render_client_delete_content(
            delete_client_id=client_id,
            delete_counts=counts,
            csrf_token=csrf_token,
            banner_message=message,
        )
        response = HTMLResponse(
            _wrap_page(
                request,
                content,
                title="Admin — Delete Client",
                active="clients",
                page_lang=resolve_lang(request),
            ),
            status_code=status.HTTP_409_CONFLICT,
        )
        issue_csrf_token(request, response, csrf_token)
        return response

    booking_ids = (
        await session.execute(
            select(Booking.booking_id).where(
                Booking.client_id == client_id,
                Booking.org_id == org_id,
            )
        )
    ).scalars().all()

    if strategy == "detach":
        await session.execute(
            sa.update(Booking)
            .where(Booking.client_id == client_id, Booking.org_id == org_id)
            .values(client_id=None)
        )
    else:
        for booking_id in booking_ids:
            await hard_delete_booking(session, booking_id)

    before = {
        "name": client.name,
        "email": client.email,
        "strategy": strategy,
        "bookings": len(booking_ids),
    }
    await audit_service.record_action(
        session,
        identity=identity,
        action="DELETE_CLIENT",
        resource_type="client",
        resource_id=client_id,
        before=before,
        after=None,
    )
    await session.delete(client)
    await session.commit()
    return RedirectResponse("/v1/admin/ui/clients", status_code=status.HTTP_303_SEE_OTHER)


# ============================================================
# Booking Creation Routes
# ============================================================


def _render_booking_form(
    teams: list[Team],
    clients: list[ClientUser],
    workers: list[Worker],
    lang: str | None,
    csrf_input: str,
    *,
    action: str,
    booking: Booking | None = None,
    selected_worker_ids: list[int] | None = None,
    selected_client_id: str | None = None,
    address_value: str | None = None,
    address_id: int | None = None,
    banner_message: str | None = None,
    banner_is_error: bool = False,
) -> str:
    selected_team_id = getattr(booking, "team_id", None)
    if selected_client_id is None:
        selected_client_id = getattr(booking, "client_id", None)
    selected_worker_ids = list(dict.fromkeys(selected_worker_ids or []))
    starts_at_value = ""
    if getattr(booking, "starts_at", None):
        starts_at_dt = booking.starts_at
        if starts_at_dt.tzinfo is None:
            starts_at_dt = starts_at_dt.replace(tzinfo=timezone.utc)
        else:
            starts_at_dt = starts_at_dt.astimezone(timezone.utc)
        starts_at_value = starts_at_dt.strftime("%Y-%m-%dT%H:%M")
    duration_value = str(getattr(booking, "duration_minutes", 120) or 120)

    team_options = "".join(
        f'<option value="{team.team_id}" {"selected" if team.team_id == selected_team_id else ""}>'
        f"{html.escape(team.name)}</option>"
        for team in teams
    )

    client_options = '<option value="">—</option>' + "".join(
        f'<option value="{client.client_id}" {"selected" if client.client_id == selected_client_id else ""}>'
        f"{html.escape((client.name or client.email))}</option>"
        for client in clients
    )

    selected_worker_set = set(selected_worker_ids)
    worker_options = "".join(
        f'<option value="{worker.worker_id}" {"selected" if worker.worker_id in selected_worker_set else ""}>'
        f"{html.escape(worker.name)}</option>"
        for worker in workers
    )

    banner_block = ""
    if banner_message:
        banner_color = "#b91c1c" if banner_is_error else "#1d4ed8"
        banner_background = "#fef2f2" if banner_is_error else "#eff6ff"
        banner_border = "#fecaca" if banner_is_error else "#bfdbfe"
        banner_block = f"""
      <div class="card" style="border-color:{banner_border};background:{banner_background};color:{banner_color};">
        <strong>{html.escape(banner_message)}</strong>
      </div>
        """
    address_value = address_value or ""
    address_id_value = str(address_id) if address_id is not None else ""
    address_id_input = (
        f'<input type="hidden" name="address_id" value="{html.escape(address_id_value)}" />'
        if address_id_value
        else ""
    )

    return f"""
    {banner_block}
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title with-icon">{_icon('calendar')}{html.escape(tr(lang, 'admin.bookings.title'))}</div>
          <div class="muted">{html.escape(tr(lang, 'admin.bookings.subtitle'))}</div>
        </div>
      </div>
      <form class="stack" method="post" action="{html.escape(action)}">
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.bookings.team'))}</label>
          <select class="input" name="team_id" required>{team_options}</select>
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.bookings.client'))}</label>
          <select class="input" name="client_id" required>{client_options}</select>
          <div class="muted">{html.escape(tr(lang, 'admin.bookings.select_client'))}</div>
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.bookings.address'))}</label>
          <input class="input" type="text" name="address" value="{html.escape(address_value)}" />
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.bookings.worker'))} (crew)</label>
          <select class="input" name="worker_ids" multiple size="5">{worker_options}</select>
          <div class="muted">Select one or more workers.</div>
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.bookings.starts_at'))}</label>
          <input class="input" type="datetime-local" name="starts_at" value="{starts_at_value}" required />
        </div>
        <div class="form-group">
          <label>{html.escape(tr(lang, 'admin.bookings.duration'))}</label>
          <input class="input" type="number" name="duration_minutes" min="30" step="30" value="{duration_value}" required />
        </div>
        {address_id_input}
        {csrf_input}
        <button class="btn" type="submit">{html.escape(tr(lang, 'admin.bookings.save'))}</button>
      </form>
    </div>
    """


def _parse_admin_booking_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError("Invalid datetime format")


def _normalize_worker_ids(worker_ids_raw: Iterable[str | None]) -> list[int]:
    worker_ids: list[int] = []
    for raw in worker_ids_raw:
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        try:
            worker_ids.append(int(value))
        except (TypeError, ValueError) as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid worker ID") from exc
    return list(dict.fromkeys(worker_ids))


def _resolve_primary_worker_id(worker_ids: list[int], current_worker_id: int | None) -> int | None:
    if not worker_ids:
        return None
    if current_worker_id in worker_ids:
        return current_worker_id
    return worker_ids[0]


async def _validate_booking_worker_ids(
    session: AsyncSession,
    worker_ids: list[int],
    *,
    org_id: uuid.UUID,
    team_id: int,
) -> None:
    if not worker_ids:
        return
    unique_ids = set(worker_ids)
    workers = (
        await session.execute(
            select(Worker).where(
                Worker.worker_id.in_(unique_ids),
                Worker.org_id == org_id,
                Worker.is_active == True,  # noqa: E712
            )
        )
    ).scalars().all()
    if len(workers) != len(unique_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Worker not found or inactive")
    for worker in workers:
        if worker.team_id != team_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Worker must be on the same team")


async def _sync_booking_workers(
    session: AsyncSession,
    booking_id: str,
    worker_ids: list[int],
    *,
    replace: bool,
) -> None:
    unique_ids: list[int] = []
    seen: set[int] = set()
    for worker_id in worker_ids:
        if worker_id not in seen:
            unique_ids.append(worker_id)
            seen.add(worker_id)

    existing_ids = set(
        (
            await session.execute(
                select(BookingWorker.worker_id).where(BookingWorker.booking_id == booking_id)
            )
        ).scalars().all()
    )
    if replace:
        to_remove = existing_ids - seen
        if to_remove:
            await session.execute(
                sa.delete(BookingWorker).where(
                    BookingWorker.booking_id == booking_id,
                    BookingWorker.worker_id.in_(to_remove),
                )
            )

    to_add = [worker_id for worker_id in unique_ids if worker_id not in existing_ids]
    if to_add:
        session.add_all(
            [BookingWorker(booking_id=booking_id, worker_id=worker_id) for worker_id in to_add]
        )


def _apply_booking_active_filters(
    stmt: sa.Select,
    *,
    include_archived: bool,
    include_cancelled: bool,
) -> sa.Select:
    if not include_archived:
        stmt = stmt.where(Booking.archived_at.is_(None))
    if not include_cancelled:
        stmt = stmt.where(Booking.status != "CANCELLED")
    return stmt


async def _booking_delete_counts(session: AsyncSession, booking_id: str) -> dict[str, int]:
    invoice_ids = (
        await session.execute(select(Invoice.invoice_id).where(Invoice.order_id == booking_id))
    ).scalars().all()
    dispute_ids = (
        await session.execute(select(Dispute.dispute_id).where(Dispute.booking_id == booking_id))
    ).scalars().all()
    run_ids = (
        await session.execute(select(ChecklistRun.run_id).where(ChecklistRun.order_id == booking_id))
    ).scalars().all()
    event_logs = (
        await session.execute(
            select(func.count()).select_from(EventLog).where(EventLog.booking_id == booking_id)
        )
    ).scalar_one()
    booking_workers = (
        await session.execute(
            select(func.count())
            .select_from(BookingWorker)
            .where(BookingWorker.booking_id == booking_id)
        )
    ).scalar_one()
    order_addons = (
        await session.execute(
            select(func.count()).select_from(OrderAddon).where(OrderAddon.order_id == booking_id)
        )
    ).scalar_one()
    order_photos = (
        await session.execute(
            select(func.count()).select_from(OrderPhoto).where(OrderPhoto.order_id == booking_id)
        )
    ).scalar_one()
    order_photo_tombstones = (
        await session.execute(
            select(func.count())
            .select_from(OrderPhotoTombstone)
            .where(OrderPhotoTombstone.order_id == booking_id)
        )
    ).scalar_one()
    checklist_runs = (
        await session.execute(
            select(func.count()).select_from(ChecklistRun).where(ChecklistRun.order_id == booking_id)
        )
    ).scalar_one()
    checklist_items = (
        await session.execute(
            select(func.count())
            .select_from(ChecklistRunItem)
            .where(ChecklistRunItem.run_id.in_(run_ids or ["-1"]))
        )
    ).scalar_one()
    work_time_entries = (
        await session.execute(
            select(func.count())
            .select_from(WorkTimeEntry)
            .where(WorkTimeEntry.booking_id == booking_id)
        )
    ).scalar_one()
    reason_logs = (
        await session.execute(
            select(func.count()).select_from(ReasonLog).where(ReasonLog.order_id == booking_id)
        )
    ).scalar_one()
    email_events = (
        await session.execute(
            select(func.count()).select_from(EmailEvent).where(EmailEvent.booking_id == booking_id)
        )
    ).scalar_one()
    email_failures = (
        await session.execute(
            select(func.count())
            .select_from(EmailFailure)
            .where(EmailFailure.booking_id == booking_id)
        )
    ).scalar_one()
    policy_override_audits = (
        await session.execute(
            select(func.count())
            .select_from(PolicyOverrideAudit)
            .where(PolicyOverrideAudit.booking_id == booking_id)
        )
    ).scalar_one()
    disputes = (
        await session.execute(
            select(func.count()).select_from(Dispute).where(Dispute.booking_id == booking_id)
        )
    ).scalar_one()
    financial_adjustment_events = (
        await session.execute(
            select(func.count())
            .select_from(FinancialAdjustmentEvent)
            .where(FinancialAdjustmentEvent.dispute_id.in_(dispute_ids or ["-1"]))
        )
    ).scalar_one()
    invoices = (
        await session.execute(
            select(func.count()).select_from(Invoice).where(Invoice.order_id == booking_id)
        )
    ).scalar_one()
    invoice_items = (
        await session.execute(
            select(func.count())
            .select_from(InvoiceItem)
            .where(InvoiceItem.invoice_id.in_(invoice_ids or ["-1"]))
        )
    ).scalar_one()
    invoice_public_tokens = (
        await session.execute(
            select(func.count())
            .select_from(InvoicePublicToken)
            .where(InvoicePublicToken.invoice_id.in_(invoice_ids or ["-1"]))
        )
    ).scalar_one()
    payments = (
        await session.execute(
            select(func.count())
            .select_from(Payment)
            .where(
                or_(
                    Payment.booking_id == booking_id,
                    Payment.invoice_id.in_(invoice_ids or ["-1"]),
                )
            )
        )
    ).scalar_one()
    nps_responses = (
        await session.execute(
            select(func.count())
            .select_from(NpsResponse)
            .where(NpsResponse.order_id == booking_id)
        )
    ).scalar_one()
    support_tickets = (
        await session.execute(
            select(func.count())
            .select_from(SupportTicket)
            .where(SupportTicket.order_id == booking_id)
        )
    ).scalar_one()

    return {
        "event_logs": int(event_logs or 0),
        "booking_workers": int(booking_workers or 0),
        "order_addons": int(order_addons or 0),
        "order_photos": int(order_photos or 0),
        "order_photo_tombstones": int(order_photo_tombstones or 0),
        "checklist_runs": int(checklist_runs or 0),
        "checklist_items": int(checklist_items or 0),
        "work_time_entries": int(work_time_entries or 0),
        "reason_logs": int(reason_logs or 0),
        "email_events": int(email_events or 0),
        "email_failures": int(email_failures or 0),
        "policy_override_audits": int(policy_override_audits or 0),
        "disputes": int(disputes or 0),
        "financial_adjustment_events": int(financial_adjustment_events or 0),
        "invoices": int(invoices or 0),
        "invoice_items": int(invoice_items or 0),
        "invoice_public_tokens": int(invoice_public_tokens or 0),
        "payments": int(payments or 0),
        "nps_responses": int(nps_responses or 0),
        "support_tickets": int(support_tickets or 0),
    }


async def _delete_booking_dependencies(session: AsyncSession, booking_id: str) -> None:
    invoice_ids = (
        await session.execute(select(Invoice.invoice_id).where(Invoice.order_id == booking_id))
    ).scalars().all()
    dispute_ids = (
        await session.execute(select(Dispute.dispute_id).where(Dispute.booking_id == booking_id))
    ).scalars().all()
    run_ids = (
        await session.execute(select(ChecklistRun.run_id).where(ChecklistRun.order_id == booking_id))
    ).scalars().all()

    await session.execute(sa.delete(ReasonLog).where(ReasonLog.order_id == booking_id))
    await session.execute(sa.delete(EmailFailure).where(EmailFailure.booking_id == booking_id))
    await session.execute(sa.delete(EmailEvent).where(EmailEvent.booking_id == booking_id))
    await session.execute(sa.delete(PolicyOverrideAudit).where(PolicyOverrideAudit.booking_id == booking_id))
    await session.execute(sa.delete(WorkTimeEntry).where(WorkTimeEntry.booking_id == booking_id))
    if run_ids:
        await session.execute(
            sa.delete(ChecklistRunItem).where(ChecklistRunItem.run_id.in_(run_ids))
        )
    await session.execute(sa.delete(ChecklistRun).where(ChecklistRun.order_id == booking_id))
    if dispute_ids:
        await session.execute(
            sa.delete(FinancialAdjustmentEvent).where(
                FinancialAdjustmentEvent.dispute_id.in_(dispute_ids)
            )
        )
    await session.execute(sa.delete(Dispute).where(Dispute.booking_id == booking_id))
    if invoice_ids:
        await session.execute(
            sa.delete(InvoicePublicToken).where(InvoicePublicToken.invoice_id.in_(invoice_ids))
        )
        await session.execute(
            sa.delete(InvoiceItem).where(InvoiceItem.invoice_id.in_(invoice_ids))
        )
        await session.execute(sa.delete(Payment).where(Payment.invoice_id.in_(invoice_ids)))
    await session.execute(sa.delete(Payment).where(Payment.booking_id == booking_id))
    await session.execute(sa.delete(Invoice).where(Invoice.order_id == booking_id))
    await session.execute(sa.delete(BookingWorker).where(BookingWorker.booking_id == booking_id))
    await session.execute(sa.delete(EventLog).where(EventLog.booking_id == booking_id))


async def hard_delete_booking(session: AsyncSession, booking_id: uuid.UUID) -> None:
    booking_id_str = str(booking_id)
    booking = (
        await session.execute(select(Booking).where(Booking.booking_id == booking_id_str))
    ).scalar_one_or_none()
    if booking is None:
        return
    await _delete_booking_dependencies(session, booking.booking_id)
    await session.delete(booking)


@router.get("/v1/admin/ui/bookings/new", response_class=HTMLResponse)
async def admin_bookings_new_form(
    request: Request,
    client_id: str | None = Query(default=None),
    address_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)

    # Fetch teams
    teams = (
        await session.execute(
            select(Team)
            .where(Team.org_id == org_id, Team.archived_at.is_(None))
            .order_by(Team.name)
        )
    ).scalars().all()

    # Fetch clients
    clients = (
        await session.execute(
            select(ClientUser)
            .where(ClientUser.org_id == org_id, ClientUser.is_active.is_(True))
            .order_by(ClientUser.created_at.desc())
        )
    ).scalars().all()

    # Fetch active workers
    workers = (
        await session.execute(
            select(Worker).where(Worker.org_id == org_id, Worker.is_active == True).order_by(Worker.name)  # noqa: E712
        )
    ).scalars().all()

    prefill_client_id = None
    prefill_address = ""
    banner_message = None
    banner_is_error = False
    selected_address_label = None
    selected_address = None
    if address_id is not None:
        selected_address = (
            await session.execute(
                select(ClientAddress).where(
                    ClientAddress.address_id == address_id,
                    ClientAddress.org_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if selected_address is None:
            banner_message = "Selected address not found. Please choose a client."
            banner_is_error = True
        elif not selected_address.is_active:
            banner_message = "Selected address is archived. Please choose another address."
            banner_is_error = True
        else:
            prefill_address = selected_address.address_text
            selected_address_label = selected_address.label
            if client_id and selected_address.client_id != client_id:
                banner_message = "Selected address does not belong to chosen client."
                banner_is_error = True
                prefill_address = ""
                selected_address_label = None
                selected_address = None

    client = None
    if client_id:
        client = (
            await session.execute(
                select(ClientUser).where(
                    ClientUser.client_id == client_id,
                    ClientUser.org_id == org_id,
                    ClientUser.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if client is None:
            banner_message = "Selected client not found. Please choose a client."
            banner_is_error = True
    elif selected_address and not banner_is_error:
        client = (
            await session.execute(
                select(ClientUser).where(
                    ClientUser.client_id == selected_address.client_id,
                    ClientUser.org_id == org_id,
                    ClientUser.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if client is None:
            banner_message = "Selected client not found. Please choose a client."
            banner_is_error = True

    if client and not banner_is_error:
        prefill_client_id = client.client_id
        if not selected_address:
            prefill_address = client.address or ""
        client_label = client.name or client.email or "client"
        if client.is_blocked:
            banner_message = "Client is blocked"
        else:
            banner_message = f"Creating booking for {client_label}"
        if selected_address_label:
            banner_message = f"{banner_message} · Using address {selected_address_label}"

    csrf_token = get_csrf_token(request)
    content = _render_booking_form(
        teams,
        clients,
        workers,
        lang,
        render_csrf_input(csrf_token),
        action="/v1/admin/ui/bookings/create",
        selected_client_id=prefill_client_id,
        address_value=prefill_address,
        address_id=selected_address.address_id if selected_address else None,
        banner_message=banner_message,
        banner_is_error=banner_is_error,
    )
    response = HTMLResponse(_wrap_page(request, content, title="Admin — Create Booking", active="dispatch", page_lang=lang))
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/bookings/create", response_class=HTMLResponse)
async def admin_bookings_create(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()

    team_id_raw = form.get("team_id")
    client_id = (form.get("client_id") or "").strip() or None
    address_id_raw = (form.get("address_id") or "").strip()
    assigned_worker_id_raw = form.get("assigned_worker_id")
    worker_ids = _normalize_worker_ids(form.getlist("worker_ids"))
    if not worker_ids and assigned_worker_id_raw:
        worker_ids = _normalize_worker_ids([assigned_worker_id_raw])
    starts_at_raw = form.get("starts_at")
    duration_minutes_raw = form.get("duration_minutes")

    if not team_id_raw or not starts_at_raw or not duration_minutes_raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required fields")
    if not client_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Client is required")

    team_id = int(team_id_raw)
    duration_minutes = int(duration_minutes_raw)
    assigned_worker_id = _resolve_primary_worker_id(worker_ids, None)

    # Validate team exists
    team = (
        await session.execute(
            select(Team).where(
                Team.team_id == team_id, Team.org_id == org_id, Team.archived_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    await _validate_booking_worker_ids(session, worker_ids, org_id=org_id, team_id=team_id)

    # Validate client if specified (org-scoped)
    client = (
        await session.execute(
            select(ClientUser).where(
                ClientUser.client_id == client_id,
                ClientUser.org_id == org_id,
                ClientUser.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client not found or does not belong to your organization",
        )
    address_id = None
    if address_id_raw:
        try:
            address_id = int(address_id_raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid address selection",
            ) from exc
        address = (
            await session.execute(
                select(ClientAddress).where(
                    ClientAddress.address_id == address_id,
                    ClientAddress.client_id == client_id,
                    ClientAddress.org_id == org_id,
                    ClientAddress.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if address is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected address not found for client",
            )
    missing = []
    if not client.name or not client.name.strip():
        missing.append("name")
    if not client.phone or not client.phone.strip():
        missing.append("phone")
    if not client.address or not client.address.strip():
        missing.append("address")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Client missing required fields: {', '.join(missing)}",
        )

    # Parse datetime
    try:
        starts_at = _parse_admin_booking_datetime(starts_at_raw).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid datetime format") from exc

    # Create booking
    booking = Booking(
        booking_id=str(uuid.uuid4()),
        org_id=org_id,
        client_id=client_id,
        address_id=address_id,
        team_id=team_id,
        assigned_worker_id=assigned_worker_id,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        status="PENDING",
        deposit_cents=0,
        base_charge_cents=0,
        refund_total_cents=0,
        credit_note_total_cents=0,
    )
    session.add(booking)
    if worker_ids:
        await _sync_booking_workers(session, booking.booking_id, worker_ids, replace=True)
    await session.flush()

    await audit_service.record_action(
        session,
        identity=identity,
        action="CREATE_BOOKING",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=None,
        after={
            "team_id": team_id,
            "client_id": client_id,
            "assigned_worker_id": assigned_worker_id,
            "starts_at": starts_at.isoformat(),
            "duration_minutes": duration_minutes,
        },
    )
    await session.commit()

    # Redirect to dispatch board for the booking's date
    booking_date = starts_at.date().isoformat()
    return RedirectResponse(f"/v1/admin/ui/dispatch?date={booking_date}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/v1/admin/ui/bookings/{booking_id}/edit", response_class=HTMLResponse)
async def admin_bookings_edit_form(
    request: Request,
    booking_id: str,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)

    booking = (
        await session.execute(
            select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        )
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    teams = (
        await session.execute(
            select(Team)
            .where(Team.org_id == org_id, Team.archived_at.is_(None))
            .order_by(Team.name)
        )
    ).scalars().all()
    clients = (
        await session.execute(
            select(ClientUser).where(
                ClientUser.org_id == org_id,
                or_(
                    ClientUser.is_active.is_(True),
                    ClientUser.client_id == booking.client_id,
                ),
            ).order_by(ClientUser.created_at.desc())
        )
    ).scalars().all()
    workers = (
        await session.execute(
            select(Worker).where(Worker.org_id == org_id, Worker.is_active == True).order_by(Worker.name)  # noqa: E712
        )
    ).scalars().all()
    assigned_worker_ids = (
        await session.execute(
            select(BookingWorker.worker_id)
            .where(BookingWorker.booking_id == booking_id)
            .order_by(BookingWorker.created_at)
        )
    ).scalars().all()
    if booking.assigned_worker_id and booking.assigned_worker_id not in assigned_worker_ids:
        assigned_worker_ids = [booking.assigned_worker_id, *assigned_worker_ids]

    selected_address = ""
    if booking.client_id:
        for client in clients:
            if client.client_id == booking.client_id:
                selected_address = client.address or ""
                break

    csrf_token = get_csrf_token(request)
    form_html = _render_booking_form(
        teams,
        clients,
        workers,
        lang,
        render_csrf_input(csrf_token),
        action=f"/v1/admin/ui/bookings/{booking_id}/update",
        booking=booking,
        selected_worker_ids=assigned_worker_ids,
        address_value=selected_address,
    )
    archive_action = "unarchive" if booking.archived_at else "archive"
    archive_label = "Unarchive Booking" if booking.archived_at else "Archive Booking"
    archive_note = (
        f"Archived at {booking.archived_at.astimezone(timezone.utc).isoformat()}"
        if booking.archived_at
        else "Archived bookings are hidden from active views by default."
    )
    archive_html = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">{archive_label}</div>
          <div class="muted">{html.escape(archive_note)}</div>
        </div>
      </div>
      <form class="stack" method="post" action="/v1/admin/ui/bookings/{html.escape(booking_id)}/{archive_action}">
        {render_csrf_input(csrf_token)}
        <button class="btn secondary" type="submit">{archive_label}</button>
      </form>
    </div>
    """
    delete_html = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">Delete Booking</div>
          <div class="muted">Delete permanently (requires confirmation).</div>
        </div>
        <div class="actions">
          <a class="btn danger" href="/v1/admin/ui/bookings/{html.escape(booking_id)}/delete">Delete permanently</a>
        </div>
      </div>
    </div>
    """
    content = form_html + archive_html + delete_html
    response = HTMLResponse(_wrap_page(request, content, title="Admin — Edit Booking", active="dispatch", page_lang=lang))
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/bookings/{booking_id}/update", response_class=HTMLResponse)
async def admin_bookings_update(
    request: Request,
    booking_id: str,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()

    booking = (
        await session.execute(
            select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        )
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    team_id_raw = form.get("team_id")
    client_id = (form.get("client_id") or "").strip() or None
    assigned_worker_id_raw = form.get("assigned_worker_id")
    worker_ids = _normalize_worker_ids(form.getlist("worker_ids"))
    if not worker_ids and assigned_worker_id_raw:
        worker_ids = _normalize_worker_ids([assigned_worker_id_raw])
    starts_at_raw = form.get("starts_at")
    duration_minutes_raw = form.get("duration_minutes")

    if not team_id_raw or not starts_at_raw or not duration_minutes_raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required fields")

    team_id = int(team_id_raw)
    duration_minutes = int(duration_minutes_raw)
    assigned_worker_id = _resolve_primary_worker_id(worker_ids, booking.assigned_worker_id)

    team = (
        await session.execute(
            select(Team).where(
                Team.team_id == team_id, Team.org_id == org_id, Team.archived_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    await _validate_booking_worker_ids(session, worker_ids, org_id=org_id, team_id=team_id)

    if not client_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Client is required")
    client_query = select(ClientUser).where(
        ClientUser.client_id == client_id,
        ClientUser.org_id == org_id,
    )
    if client_id != booking.client_id:
        client_query = client_query.where(ClientUser.is_active.is_(True))
    client = (await session.execute(client_query)).scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client not found or does not belong to your organization",
        )

    try:
        starts_at = _parse_admin_booking_datetime(starts_at_raw).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid datetime format") from exc

    previous_client_id = booking.client_id
    before = {
        "team_id": booking.team_id,
        "client_id": booking.client_id,
        "assigned_worker_id": booking.assigned_worker_id,
        "starts_at": booking.starts_at.isoformat() if booking.starts_at else None,
        "duration_minutes": booking.duration_minutes,
    }
    if client_id != previous_client_id and booking.address_id:
        address = (
            await session.execute(
                select(ClientAddress).where(
                    ClientAddress.address_id == booking.address_id,
                    ClientAddress.org_id == org_id,
                    ClientAddress.client_id == client_id,
                    ClientAddress.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if address is None:
            booking.address_id = None
    booking.team_id = team_id
    booking.client_id = client_id
    booking.assigned_worker_id = assigned_worker_id
    booking.starts_at = starts_at
    booking.duration_minutes = duration_minutes
    await _sync_booking_workers(session, booking.booking_id, worker_ids, replace=True)

    await audit_service.record_action(
        session,
        identity=identity,
        action="UPDATE_BOOKING",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before,
        after={
            "team_id": team_id,
            "client_id": client_id,
            "assigned_worker_id": assigned_worker_id,
            "starts_at": starts_at.isoformat(),
            "duration_minutes": duration_minutes,
        },
    )
    await session.commit()

    booking_date = starts_at.date().isoformat()
    return RedirectResponse(f"/v1/admin/ui/dispatch?date={booking_date}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/bookings/{booking_id}/archive", response_class=HTMLResponse)
async def admin_bookings_archive(
    request: Request,
    booking_id: str,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    booking = (
        await session.execute(
            select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        )
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    if booking.archived_at is None:
        booking.archived_at = datetime.now(timezone.utc)
        await audit_service.record_action(
            session,
            identity=identity,
            action="ARCHIVE_BOOKING",
            resource_type="booking",
            resource_id=booking.booking_id,
            before={"archived_at": None},
            after={"archived_at": booking.archived_at.isoformat()},
        )
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/bookings/{booking.booking_id}/edit", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/v1/admin/ui/bookings/{booking_id}/unarchive", response_class=HTMLResponse)
async def admin_bookings_unarchive(
    request: Request,
    booking_id: str,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    booking = (
        await session.execute(
            select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        )
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    if booking.archived_at is not None:
        previous = booking.archived_at
        booking.archived_at = None
        await audit_service.record_action(
            session,
            identity=identity,
            action="UNARCHIVE_BOOKING",
            resource_type="booking",
            resource_id=booking.booking_id,
            before={"archived_at": previous.isoformat()},
            after={"archived_at": None},
        )
    await session.commit()
    return RedirectResponse(
        f"/v1/admin/ui/bookings/{booking.booking_id}/edit", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/v1/admin/ui/bookings/{booking_id}/delete", response_class=HTMLResponse)
async def admin_bookings_delete_confirm(
    request: Request,
    booking_id: str,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    booking = (
        await session.execute(
            select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        )
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    counts = await _booking_delete_counts(session, booking_id)
    count_rows = "".join(
        f"<li><strong>{html.escape(label.replace('_', ' ').title())}:</strong> {count}</li>"
        for label, count in counts.items()
        if count
    )
    counts_html = count_rows or "<li>None</li>"
    csrf_token = get_csrf_token(request)
    content = f"""
    <div class="card">
      <div class="card-row">
        <div>
          <div class="title">Delete booking permanently</div>
          <div class="muted">This action removes the booking and related records.</div>
        </div>
      </div>
      <div class="stack">
        <div class="muted">Dependent records found:</div>
        <ul>{counts_html}</ul>
      </div>
      <form class="stack" method="post" action="/v1/admin/ui/bookings/{html.escape(booking_id)}/delete">
        <input class="input" type="text" name="confirm" placeholder="DELETE" required />
        {render_csrf_input(csrf_token)}
        <button class="btn danger" type="submit">Delete permanently</button>
      </form>
    </div>
    """
    response = HTMLResponse(
        _wrap_page(
            request,
            content,
            title="Admin — Delete Booking",
            active="dispatch",
            page_lang=lang,
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/bookings/{booking_id}/delete", response_class=HTMLResponse)
async def admin_bookings_delete(
    request: Request,
    booking_id: str,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    confirmation = (form.get("confirm") or "").strip().upper()
    if confirmation != "DELETE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Deletion confirmation required")

    booking = (
        await session.execute(
            select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
        )
    ).scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    before = {
        "team_id": booking.team_id,
        "client_id": booking.client_id,
        "assigned_worker_id": booking.assigned_worker_id,
        "starts_at": booking.starts_at.isoformat() if booking.starts_at else None,
        "duration_minutes": booking.duration_minutes,
    }
    await audit_service.record_action(
        session,
        identity=identity,
        action="DELETE_BOOKING",
        resource_type="booking",
        resource_id=booking.booking_id,
        before=before,
        after=None,
    )
    await hard_delete_booking(session, booking.booking_id)
    await session.commit()
    return RedirectResponse("/v1/admin/ui/dispatch", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/v1/admin/ui/bookings/purge", response_class=HTMLResponse)
async def admin_bookings_purge(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_admin),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    confirmation = (form.get("confirm") or "").strip().upper()
    if confirmation != "PURGE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Purge confirmation required")

    date_from_raw = (form.get("date_from") or "").strip() or None
    date_to_raw = (form.get("date_to") or "").strip() or None
    try:
        date_from_val = date.fromisoformat(date_from_raw) if date_from_raw else None
        date_to_val = date.fromisoformat(date_to_raw) if date_to_raw else None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format") from exc
    if date_from_val and date_to_val and date_from_val > date_to_val:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date range")

    conditions = [Booking.org_id == org_id]
    if date_from_val:
        start_dt = datetime.combine(date_from_val, time.min).replace(tzinfo=timezone.utc)
        conditions.append(Booking.starts_at >= start_dt)
    if date_to_val:
        end_dt = datetime.combine(date_to_val + timedelta(days=1), time.min).replace(tzinfo=timezone.utc)
        conditions.append(Booking.starts_at < end_dt)

    count_stmt = select(func.count()).select_from(Booking).where(and_(*conditions))
    to_delete = (await session.execute(count_stmt)).scalar_one()

    delete_stmt = sa.delete(Booking).where(and_(*conditions))
    await session.execute(delete_stmt)

    await audit_service.record_action(
        session,
        identity=identity,
        action="PURGE_BOOKINGS",
        resource_type="booking",
        resource_id=str(org_id),
        before={"filters": {"date_from": date_from_raw, "date_to": date_to_raw}, "count": to_delete},
        after={"deleted": to_delete},
    )
    await session.commit()
    redirect_date = date_from_val or datetime.now(timezone.utc).date()
    return RedirectResponse(f"/v1/admin/ui/dispatch?date={redirect_date.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/v1/admin/dispatch/board", response_model=booking_schemas.DispatchBoardResponse)
async def dispatch_board_data(
    request: Request,
    day: str | None = Query(default=None, alias="date"),
    show_archived: bool = Query(default=False, alias="show_archived"),
    show_cancelled: bool = Query(default=False, alias="show_cancelled"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> booking_schemas.DispatchBoardResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    try:
        target_date = date.fromisoformat(day) if day else datetime.now(timezone.utc).date()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date") from exc
    start_dt = datetime.combine(target_date, time.min).replace(tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)
    stmt = (
        select(Booking)
        .where(
            Booking.starts_at >= start_dt,
            Booking.starts_at < end_dt,
            Booking.org_id == org_id,
        )
        .options(
            selectinload(Booking.lead),
            selectinload(Booking.team),
            selectinload(Booking.worker_assignments).selectinload(BookingWorker.worker),
        )
        .order_by(Booking.starts_at)
    )
    stmt = _apply_booking_active_filters(
        stmt, include_archived=show_archived, include_cancelled=show_cancelled
    )
    bookings = (await session.execute(stmt)).scalars().all()
    return booking_schemas.DispatchBoardResponse(
        day=target_date,
        bookings=[
            booking_schemas.DispatchBooking(
                booking_id=booking.booking_id,
                starts_at=booking.starts_at,
                duration_minutes=booking.duration_minutes,
                status=booking.status,
                team_id=booking.team_id,
                team_name=getattr(booking.team, "name", ""),
                lead_name=getattr(getattr(booking, "lead", None), "name", None),
                assigned_workers=[
                    booking_schemas.DispatchWorker(worker_id=assignment.worker.worker_id, name=assignment.worker.name)
                    for assignment in booking.worker_assignments
                    if assignment.worker is not None
                ],
            )
            for booking in bookings
        ],
    )


@router.get("/v1/admin/ui/dispatch", response_class=HTMLResponse)
async def admin_dispatch_board(
    request: Request,
    day: str | None = Query(default=None, alias="date"),
    show_archived: bool = Query(default=False, alias="show_archived"),
    show_cancelled: bool = Query(default=False, alias="show_cancelled"),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    lang = resolve_lang(request)
    try:
        target_date = date.fromisoformat(day) if day else datetime.now(timezone.utc).date()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date") from exc
    start_dt = datetime.combine(target_date, time.min).replace(tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    stmt = (
        select(Booking)
        .where(
            Booking.starts_at >= start_dt,
            Booking.starts_at < end_dt,
            Booking.org_id == org_id,
        )
        .options(
            selectinload(Booking.lead),
            selectinload(Booking.assigned_worker),
            selectinload(Booking.worker_assignments).selectinload(BookingWorker.worker),
            selectinload(Booking.team),
        )
        .order_by(Booking.starts_at)
    )
    stmt = _apply_booking_active_filters(
        stmt, include_archived=show_archived, include_cancelled=show_cancelled
    )
    bookings = (await session.execute(stmt)).scalars().all()
    team_ids = {booking.team_id for booking in bookings}
    workers_stmt = (
        select(Worker)
        .where(
            Worker.team_id.in_(team_ids or {0}),
            Worker.org_id == org_id,
            Worker.is_active == True,  # noqa: E712
        )
        .options(selectinload(Worker.team))
        .order_by(Worker.name)
    )
    workers = (await session.execute(workers_stmt)).scalars().all()
    workers_by_team: dict[int, list[Worker]] = {}
    for worker in workers:
        workers_by_team.setdefault(worker.team_id, []).append(worker)

    csrf_token = get_csrf_token(request)
    csrf_input = render_csrf_input(csrf_token)

    cards: list[str] = []
    for booking in bookings:
        lead: Lead | None = getattr(booking, "lead", None)
        assigned_workers = [
            assignment.worker
            for assignment in booking.worker_assignments
            if assignment.worker is not None
        ]
        assigned_ids = {worker.worker_id for worker in assigned_workers}
        assigned_names = [worker.name for worker in assigned_workers]
        worker_options: list[str] = []
        for worker in workers_by_team.get(booking.team_id, []):
            selected = "selected" if worker.worker_id in assigned_ids else ""
            status_hint = "" if worker.is_active else " (inactive)"
            worker_options.append(
                f'<option value="{worker.worker_id}" {selected}>{html.escape(worker.name + status_hint)}</option>'
            )
        cards.append(
            """
            <div class=\"card\">
              <div class=\"card-row\">
                <div>
                  <div class=\"title\">{starts}</div>
                  <div class=\"muted\">{customer}</div>
                  <div class=\"muted\">{team_label}: {team}</div>
                </div>
                <div class=\"actions\">
                  <span>{status}</span>
                  <a class=\"btn secondary\" href=\"/v1/admin/ui/bookings/{booking_id}/edit\">Edit</a>
                </div>
              </div>
              <form class=\"actions\" method=\"post\" action=\"/v1/admin/ui/dispatch/assign\">
                <input type=\"hidden\" name=\"booking_id\" value=\"{booking_id}\" />
                {csrf_input}
                <label class=\"muted\">{assign_label}</label>
                <select class=\"input\" name=\"worker_ids\" multiple size=\"4\">{options}</select>
                <button class=\"btn secondary\" type=\"submit\">{save_label}</button>
              </form>
              <div class=\"muted small\">{current}</div>
            </div>
            """.format(
                starts=html.escape(_format_dt(booking.starts_at)),
                customer=html.escape(getattr(lead, "name", tr(lang, "admin.dispatch.customer"))),
                team_label=html.escape(tr(lang, "admin.dispatch.team")),
                team=html.escape(getattr(booking.team, "name", "")),
                status=html.escape(booking.status),
                booking_id=html.escape(booking.booking_id),
                assign_label=html.escape(tr(lang, "admin.dispatch.assigned_workers")),
                options="".join(worker_options),
                save_label=html.escape(tr(lang, "admin.dispatch.save")),
                current=html.escape(
                    ", ".join(assigned_names) if assigned_names else tr(lang, "admin.dispatch.unassigned")
                ),
                csrf_input=csrf_input,
            )
        )

    date_value = target_date.isoformat()
    show_archived_checked = "checked" if show_archived else ""
    show_cancelled_checked = "checked" if show_cancelled else ""
    content = "".join(
        [
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            f"<div><div class=\"title with-icon\">{_icon('calendar')}{html.escape(tr(lang, 'admin.dispatch.title'))}</div>",
            f"<div class=\"muted\">{html.escape(tr(lang, 'admin.dispatch.subtitle'))}</div></div>",
            "<form class=\"actions\" method=\"get\">",
            f"<label class=\"muted\">{html.escape(tr(lang, 'admin.dispatch.date_label'))}</label>",
            f"<input class=\"input\" type=\"date\" name=\"date\" value=\"{date_value}\" />",
            "<label class=\"muted\"><input type=\"checkbox\" name=\"show_archived\" value=\"true\" "
            f"{show_archived_checked} /> Show archived</label>",
            "<label class=\"muted\"><input type=\"checkbox\" name=\"show_cancelled\" value=\"true\" "
            f"{show_cancelled_checked} /> Show cancelled</label>",
            "<button class=\"btn secondary\" type=\"submit\">Go</button>",
            "</form>",
            "</div>",
            f"<div class=\"stack\">{''.join(cards) if cards else _render_empty(tr(lang, 'admin.workers.none'))}</div>",
            "<div class=\"card\">",
            "<div class=\"card-row\">",
            "<div>",
            "<div class=\"title\">Bulk purge bookings</div>",
            "<div class=\"muted\">Type PURGE to delete bookings (optional date range).</div>",
            "</div>",
            "</div>",
            "<form class=\"stack\" method=\"post\" action=\"/v1/admin/ui/bookings/purge\">",
            "<div class=\"form-group\">",
            "<label class=\"muted\">From</label>",
            "<input class=\"input\" type=\"date\" name=\"date_from\" />",
            "</div>",
            "<div class=\"form-group\">",
            "<label class=\"muted\">To</label>",
            "<input class=\"input\" type=\"date\" name=\"date_to\" />",
            "</div>",
            "<input class=\"input\" type=\"text\" name=\"confirm\" placeholder=\"PURGE\" required />",
            csrf_input,
            "<button class=\"btn danger\" type=\"submit\">Purge bookings</button>",
            "</form>",
            "</div>",
            "</div>",
        ]
    )
    response = HTMLResponse(_wrap_page(request, content, title="Admin — Dispatch", active="dispatch", page_lang=lang))
    issue_csrf_token(request, response, csrf_token)
    return response


@router.post("/v1/admin/ui/dispatch/assign", response_class=HTMLResponse)
async def admin_assign_worker(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = getattr(request.state, "org_id", None) or entitlements.resolve_org_id(request)
    form = await request.form()
    booking_id = (form.get("booking_id") or "").strip()
    if not booking_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking ID is required")
    worker_ids_raw = form.getlist("worker_ids")
    worker_ids: list[int] = []
    for raw in worker_ids_raw:
        if raw is None or str(raw).strip() == "":
            continue
        try:
            worker_ids.append(int(raw))
        except (TypeError, ValueError) as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid worker ID") from exc
    unique_worker_ids = list(dict.fromkeys(worker_ids))
    booking_result = await session.execute(
        select(Booking).where(Booking.booking_id == booking_id, Booking.org_id == org_id)
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    previous_ids = (
        await session.execute(
            select(BookingWorker.worker_id).where(BookingWorker.booking_id == booking_id)
        )
    ).scalars().all()
    if unique_worker_ids:
        workers = (
            await session.execute(
                select(Worker).where(
                    Worker.worker_id.in_(set(unique_worker_ids)),
                    Worker.org_id == org_id,
                )
            )
        ).scalars().all()
        if len(workers) != len(set(unique_worker_ids)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker not found")
        for worker in workers:
            if worker.team_id != booking.team_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Worker must be on the same team")
    booking.assigned_worker_id = unique_worker_ids[0] if unique_worker_ids else None
    await _sync_booking_workers(session, booking.booking_id, unique_worker_ids, replace=True)

    await audit_service.record_action(
        session,
        identity=identity,
        action="ASSIGN_WORKERS" if booking.assigned_worker_id else "UNASSIGN_WORKERS",
        resource_type="booking",
        resource_id=booking.booking_id,
        before={"assigned_worker_ids": previous_ids},
        after={"assigned_worker_ids": unique_worker_ids},
    )
    await session.commit()
    target_date = getattr(booking.starts_at, "date", lambda: None)() if hasattr(booking.starts_at, "date") else None
    redirect_url = "/v1/admin/ui/dispatch"
    if target_date:
        redirect_url = f"{redirect_url}?date={target_date.isoformat()}"
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)
