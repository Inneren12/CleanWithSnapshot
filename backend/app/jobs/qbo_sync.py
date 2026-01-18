from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feature_modules import service as feature_service
from app.domain.integrations import qbo_service
from app.domain.integrations.db_models import AccountingSyncState, IntegrationsAccountingAccount
from app.settings import settings

logger = logging.getLogger(__name__)


def _parse_cursor(value: str | None) -> date | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        try:
            parsed_dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed_dt.date()
    return parsed


async def _ensure_sync_state(session: AsyncSession, *, org_id: uuid.UUID) -> AccountingSyncState:
    state = await session.get(AccountingSyncState, {"org_id": org_id, "provider": qbo_service.QBO_PROVIDER})
    if state is None:
        state = AccountingSyncState(org_id=org_id, provider=qbo_service.QBO_PROVIDER)
        session.add(state)
        await session.flush()
    return state


def _should_run(state: AccountingSyncState | None, *, now: datetime) -> bool:
    if not state or not state.last_sync_at:
        return True
    last_sync_at = state.last_sync_at
    if last_sync_at.tzinfo is None:
        last_sync_at = last_sync_at.replace(tzinfo=timezone.utc)
    interval_seconds = max(settings.qbo_sync_interval_seconds, 1)
    return (now - last_sync_at).total_seconds() >= interval_seconds


def _sync_window(state: AccountingSyncState | None, *, now: datetime) -> tuple[date, date]:
    cursor = _parse_cursor(state.cursor) if state else None
    if cursor is None:
        cursor = (now - timedelta(days=settings.qbo_sync_initial_days)).date()
    from_date = cursor - timedelta(days=settings.qbo_sync_backfill_days)
    to_date = now.date()
    if from_date > to_date:
        from_date = to_date
    return from_date, to_date


async def run_qbo_sync(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(tz=timezone.utc)
    accounts_stmt = sa.select(IntegrationsAccountingAccount).where(
        IntegrationsAccountingAccount.provider == qbo_service.QBO_PROVIDER
    )
    if org_id:
        accounts_stmt = accounts_stmt.where(IntegrationsAccountingAccount.org_id == org_id)
    accounts = (await session.scalars(accounts_stmt)).all()
    if not accounts:
        return {"processed": 0, "skipped": 1, "errors": 0}

    processed = 0
    skipped = 0
    errors = 0
    for account in accounts:
        module_enabled = await feature_service.effective_feature_enabled(
            session, account.org_id, "module.integrations"
        )
        qbo_enabled = await feature_service.effective_feature_enabled(
            session, account.org_id, "integrations.accounting.quickbooks"
        )
        if not (module_enabled and qbo_enabled):
            skipped += 1
            continue
        if not qbo_service.oauth_configured():
            skipped += 1
            continue

        state = await qbo_service.get_sync_state(session, account.org_id)
        if not _should_run(state, now=now):
            skipped += 1
            continue

        from_date, to_date = _sync_window(state, now=now)
        try:
            push_result = await qbo_service.push_invoices_to_qbo(
                session,
                account.org_id,
                from_date=from_date,
                to_date=to_date,
            )
            pull_result = await qbo_service.pull_invoice_status_from_qbo(
                session,
                account.org_id,
                from_date=from_date,
                to_date=to_date,
            )
            state = await _ensure_sync_state(session, org_id=account.org_id)
            state.last_sync_at = now
            state.last_error = None
            state.cursor = now.date().isoformat()
            await session.commit()
            logger.info(
                "qbo_sync_complete",
                extra={
                    "extra": {
                        "org_id": str(account.org_id),
                        "push_created": push_result.created,
                        "push_updated": push_result.updated,
                        "push_skipped": push_result.skipped,
                        "pull_payments_recorded": pull_result.payments_recorded,
                        "pull_payments_skipped": pull_result.payments_skipped,
                    }
                },
            )
            processed += 1
        except Exception as exc:  # noqa: BLE001
            error_message = str(exc) or type(exc).__name__
            await qbo_service.record_sync_error(session, account.org_id, error_message)
            state = await _ensure_sync_state(session, org_id=account.org_id)
            state.last_sync_at = now
            state.last_error = error_message
            await session.commit()
            logger.warning(
                "qbo_sync_failed",
                extra={
                    "extra": {
                        "org_id": str(account.org_id),
                        "reason": type(exc).__name__,
                    }
                },
            )
            errors += 1

    return {"processed": processed, "skipped": skipped, "errors": errors}
