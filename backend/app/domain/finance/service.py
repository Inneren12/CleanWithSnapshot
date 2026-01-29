"""Finance domain service layer for expense tracking and budgets."""

from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.finance import db_models
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, Payment


def _month_range(start: date, end: date) -> list[str]:
    months: list[str] = []
    year = start.year
    month = start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        if month == 12:
            month = 1
            year += 1
        else:
            month += 1
    return months


async def list_expense_categories(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[db_models.FinanceExpenseCategory], int]:
    stmt = select(db_models.FinanceExpenseCategory).where(
        db_models.FinanceExpenseCategory.org_id == org_id
    )

    if query:
        search_term = f"%{query}%"
        stmt = stmt.where(db_models.FinanceExpenseCategory.name.ilike(search_term))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(
        db_models.FinanceExpenseCategory.sort_order.asc(),
        db_models.FinanceExpenseCategory.name.asc(),
    )
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)

    result = await session.execute(stmt)
    categories = list(result.scalars().all())

    return categories, total


async def get_expense_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    category_id: uuid.UUID,
) -> db_models.FinanceExpenseCategory | None:
    stmt = select(db_models.FinanceExpenseCategory).where(
        db_models.FinanceExpenseCategory.org_id == org_id,
        db_models.FinanceExpenseCategory.category_id == category_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_expense_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    name: str,
    default: bool,
    sort_order: int,
) -> db_models.FinanceExpenseCategory:
    category = db_models.FinanceExpenseCategory(
        category_id=uuid.uuid4(),
        org_id=org_id,
        name=name,
        default=default,
        sort_order=sort_order,
        created_at=datetime.now(timezone.utc),
    )
    session.add(category)
    await session.flush()
    return category


async def update_expense_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    category_id: uuid.UUID,
    *,
    name: str | None = None,
    default: bool | None = None,
    sort_order: int | None = None,
) -> db_models.FinanceExpenseCategory | None:
    category = await get_expense_category(session, org_id, category_id)
    if not category:
        return None

    if name is not None:
        category.name = name
    if default is not None:
        category.default = default
    if sort_order is not None:
        category.sort_order = sort_order

    await session.flush()
    return category


async def delete_expense_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    category_id: uuid.UUID,
) -> bool:
    category = await get_expense_category(session, org_id, category_id)
    if not category:
        return False
    await session.delete(category)
    await session.flush()
    return True


async def list_expenses(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    category_id: uuid.UUID | None = None,
    query: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[tuple[db_models.FinanceExpense, str]], int]:
    base_stmt = select(db_models.FinanceExpense).where(db_models.FinanceExpense.org_id == org_id)

    if from_date:
        base_stmt = base_stmt.where(db_models.FinanceExpense.occurred_on >= from_date)
    if to_date:
        base_stmt = base_stmt.where(db_models.FinanceExpense.occurred_on <= to_date)
    if category_id:
        base_stmt = base_stmt.where(db_models.FinanceExpense.category_id == category_id)
    if query:
        search_term = f"%{query}%"
        base_stmt = base_stmt.where(
            or_(
                db_models.FinanceExpense.vendor.ilike(search_term),
                db_models.FinanceExpense.description.ilike(search_term),
            )
        )

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = (
        select(db_models.FinanceExpense, db_models.FinanceExpenseCategory.name)
        .join(
            db_models.FinanceExpenseCategory,
            db_models.FinanceExpense.category_id == db_models.FinanceExpenseCategory.category_id,
        )
        .where(db_models.FinanceExpense.org_id == org_id)
    )

    if from_date:
        stmt = stmt.where(db_models.FinanceExpense.occurred_on >= from_date)
    if to_date:
        stmt = stmt.where(db_models.FinanceExpense.occurred_on <= to_date)
    if category_id:
        stmt = stmt.where(db_models.FinanceExpense.category_id == category_id)
    if query:
        search_term = f"%{query}%"
        stmt = stmt.where(
            or_(
                db_models.FinanceExpense.vendor.ilike(search_term),
                db_models.FinanceExpense.description.ilike(search_term),
            )
        )

    stmt = stmt.order_by(
        db_models.FinanceExpense.occurred_on.desc(),
        db_models.FinanceExpense.created_at.desc(),
    )
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)

    result = await session.execute(stmt)
    rows = list(result.all())

    return rows, total


async def expenses_exist(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> bool:
    stmt = (
        select(db_models.FinanceExpense.expense_id)
        .where(
            db_models.FinanceExpense.org_id == org_id,
            db_models.FinanceExpense.occurred_on >= from_date,
            db_models.FinanceExpense.occurred_on <= to_date,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


def _date_bounds(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_dt, end_dt


async def summarize_pnl(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> dict[str, object]:
    start_dt, end_dt = _date_bounds(from_date, to_date)
    payment_timestamp = func.coalesce(Payment.received_at, Payment.created_at)

    revenue_stmt = select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
        Payment.org_id == org_id,
        Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
        payment_timestamp >= start_dt,
        payment_timestamp < end_dt,
    )
    revenue_result = await session.execute(revenue_stmt)
    revenue_cents = int(revenue_result.scalar_one() or 0)

    revenue_breakdown_stmt = (
        select(
            Payment.method,
            func.coalesce(func.sum(Payment.amount_cents), 0).label("total_cents"),
        )
        .where(
            Payment.org_id == org_id,
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            payment_timestamp >= start_dt,
            payment_timestamp < end_dt,
        )
        .group_by(Payment.method)
        .order_by(func.coalesce(func.sum(Payment.amount_cents), 0).desc())
    )
    revenue_breakdown_result = await session.execute(revenue_breakdown_stmt)
    revenue_breakdown = [
        {"label": row.method or "unknown", "total_cents": int(row.total_cents or 0)}
        for row in revenue_breakdown_result.all()
    ]

    expense_total_stmt = select(
        func.coalesce(func.sum(db_models.FinanceExpense.amount_cents + db_models.FinanceExpense.tax_cents), 0)
    ).where(
        db_models.FinanceExpense.org_id == org_id,
        db_models.FinanceExpense.occurred_on >= from_date,
        db_models.FinanceExpense.occurred_on <= to_date,
    )
    expense_total_result = await session.execute(expense_total_stmt)
    expense_cents = int(expense_total_result.scalar_one() or 0)

    expense_breakdown_stmt = (
        select(
            db_models.FinanceExpense.category_id,
            db_models.FinanceExpenseCategory.name,
            func.coalesce(
                func.sum(
                    db_models.FinanceExpense.amount_cents
                    + db_models.FinanceExpense.tax_cents
                ),
                0,
            ).label("total_cents"),
            func.coalesce(func.sum(db_models.FinanceExpense.tax_cents), 0).label("tax_cents"),
        )
        .join(
            db_models.FinanceExpenseCategory,
            db_models.FinanceExpense.category_id == db_models.FinanceExpenseCategory.category_id,
        )
        .where(
            db_models.FinanceExpense.org_id == org_id,
            db_models.FinanceExpense.occurred_on >= from_date,
            db_models.FinanceExpense.occurred_on <= to_date,
        )
        .group_by(
            db_models.FinanceExpense.category_id,
            db_models.FinanceExpenseCategory.name,
        )
        .order_by(func.coalesce(func.sum(db_models.FinanceExpense.amount_cents), 0).desc())
    )
    expense_breakdown_result = await session.execute(expense_breakdown_stmt)
    expense_breakdown = [
        {
            "category_id": row.category_id,
            "category_name": row.name,
            "total_cents": int(row.total_cents or 0),
            "tax_cents": int(row.tax_cents or 0),
        }
        for row in expense_breakdown_result.all()
    ]

    return {
        "revenue_cents": revenue_cents,
        "expense_cents": expense_cents,
        "net_cents": revenue_cents - expense_cents,
        "revenue_breakdown": revenue_breakdown,
        "expense_breakdown_by_category": expense_breakdown,
    }


async def summarize_cashflow(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> dict[str, object]:
    start_dt, end_dt = _date_bounds(from_date, to_date)
    payment_timestamp = func.coalesce(Payment.received_at, Payment.created_at)

    inflow_stmt = select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
        Payment.org_id == org_id,
        Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
        payment_timestamp >= start_dt,
        payment_timestamp < end_dt,
    )
    inflow_result = await session.execute(inflow_stmt)
    inflows_cents = int(inflow_result.scalar_one() or 0)

    inflow_breakdown_stmt = (
        select(
            Payment.method,
            func.coalesce(func.sum(Payment.amount_cents), 0).label("total_cents"),
        )
        .where(
            Payment.org_id == org_id,
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            payment_timestamp >= start_dt,
            payment_timestamp < end_dt,
        )
        .group_by(Payment.method)
        .order_by(func.coalesce(func.sum(Payment.amount_cents), 0).desc())
    )
    inflow_breakdown_result = await session.execute(inflow_breakdown_stmt)
    inflow_breakdown = [
        {"method": row.method or "unknown", "total_cents": int(row.total_cents or 0)}
        for row in inflow_breakdown_result.all()
    ]

    outflow_stmt = select(
        func.coalesce(func.sum(db_models.FinanceExpense.amount_cents + db_models.FinanceExpense.tax_cents), 0)
    ).where(
        db_models.FinanceExpense.org_id == org_id,
        db_models.FinanceExpense.occurred_on >= from_date,
        db_models.FinanceExpense.occurred_on <= to_date,
    )
    outflow_result = await session.execute(outflow_stmt)
    outflows_cents = int(outflow_result.scalar_one() or 0)

    outflow_breakdown_stmt = (
        select(
            db_models.FinanceExpense.category_id,
            db_models.FinanceExpenseCategory.name,
            func.coalesce(
                func.sum(
                    db_models.FinanceExpense.amount_cents
                    + db_models.FinanceExpense.tax_cents
                ),
                0,
            ).label("total_cents"),
            func.coalesce(func.sum(db_models.FinanceExpense.tax_cents), 0).label("tax_cents"),
        )
        .join(
            db_models.FinanceExpenseCategory,
            db_models.FinanceExpense.category_id == db_models.FinanceExpenseCategory.category_id,
        )
        .where(
            db_models.FinanceExpense.org_id == org_id,
            db_models.FinanceExpense.occurred_on >= from_date,
            db_models.FinanceExpense.occurred_on <= to_date,
        )
        .group_by(
            db_models.FinanceExpense.category_id,
            db_models.FinanceExpenseCategory.name,
        )
        .order_by(func.coalesce(func.sum(db_models.FinanceExpense.amount_cents), 0).desc())
    )
    outflow_breakdown_result = await session.execute(outflow_breakdown_stmt)
    outflow_breakdown = [
        {
            "category_id": row.category_id,
            "category_name": row.name,
            "total_cents": int(row.total_cents or 0),
            "tax_cents": int(row.tax_cents or 0),
        }
        for row in outflow_breakdown_result.all()
    ]

    return {
        "inflows_cents": inflows_cents,
        "outflows_cents": outflows_cents,
        "net_movement_cents": inflows_cents - outflows_cents,
        "inflows_breakdown": inflow_breakdown,
        "outflows_breakdown_by_category": outflow_breakdown,
    }


async def summarize_accounts_receivable(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    as_of_date: date,
) -> int:
    end_dt = datetime.combine(as_of_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    payment_timestamp = func.coalesce(Payment.received_at, Payment.created_at)

    payments_subquery = (
        select(
            Payment.invoice_id,
            func.coalesce(func.sum(Payment.amount_cents), 0).label("paid_cents"),
        )
        .where(
            Payment.org_id == org_id,
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            payment_timestamp < end_dt,
        )
        .group_by(Payment.invoice_id)
        .subquery()
    )

    outstanding_expr = case(
        (
            Invoice.total_cents - func.coalesce(payments_subquery.c.paid_cents, 0) < 0,
            0,
        ),
        else_=Invoice.total_cents - func.coalesce(payments_subquery.c.paid_cents, 0),
    )

    receivable_stmt = (
        select(func.coalesce(func.sum(outstanding_expr), 0))
        .select_from(Invoice)
        .outerjoin(
            payments_subquery,
            payments_subquery.c.invoice_id == Invoice.invoice_id,
        )
        .where(
            Invoice.org_id == org_id,
            Invoice.issue_date <= as_of_date,
            Invoice.status.in_(
                [
                    invoice_statuses.INVOICE_STATUS_SENT,
                    invoice_statuses.INVOICE_STATUS_PARTIAL,
                    invoice_statuses.INVOICE_STATUS_OVERDUE,
                ]
            ),
        )
    )
    result = await session.execute(receivable_stmt)
    return int(result.scalar_one() or 0)


async def get_expense(
    session: AsyncSession,
    org_id: uuid.UUID,
    expense_id: uuid.UUID,
) -> db_models.FinanceExpense | None:
    stmt = select(db_models.FinanceExpense).where(
        db_models.FinanceExpense.org_id == org_id,
        db_models.FinanceExpense.expense_id == expense_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_cash_snapshot(
    session: AsyncSession,
    org_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> db_models.FinanceCashSnapshot | None:
    stmt = select(db_models.FinanceCashSnapshot).where(
        db_models.FinanceCashSnapshot.org_id == org_id,
        db_models.FinanceCashSnapshot.snapshot_id == snapshot_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_cash_snapshot_on_or_before(
    session: AsyncSession,
    org_id: uuid.UUID,
    as_of_date: date,
) -> db_models.FinanceCashSnapshot | None:
    stmt = (
        select(db_models.FinanceCashSnapshot)
        .where(
            db_models.FinanceCashSnapshot.org_id == org_id,
            db_models.FinanceCashSnapshot.as_of_date <= as_of_date,
        )
        .order_by(
            db_models.FinanceCashSnapshot.as_of_date.desc(),
            db_models.FinanceCashSnapshot.created_at.desc(),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_cash_snapshots(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[db_models.FinanceCashSnapshot]:
    stmt = select(db_models.FinanceCashSnapshot).where(
        db_models.FinanceCashSnapshot.org_id == org_id
    )
    if from_date:
        stmt = stmt.where(db_models.FinanceCashSnapshot.as_of_date >= from_date)
    if to_date:
        stmt = stmt.where(db_models.FinanceCashSnapshot.as_of_date <= to_date)

    stmt = stmt.order_by(
        db_models.FinanceCashSnapshot.as_of_date.desc(),
        db_models.FinanceCashSnapshot.created_at.desc(),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_cash_snapshot(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    as_of_date: date,
    cash_cents: int,
    note: str | None,
) -> db_models.FinanceCashSnapshot | None:
    existing_stmt = select(db_models.FinanceCashSnapshot.snapshot_id).where(
        db_models.FinanceCashSnapshot.org_id == org_id,
        db_models.FinanceCashSnapshot.as_of_date == as_of_date,
    )
    existing = await session.execute(existing_stmt)
    if existing.scalar_one_or_none() is not None:
        return None

    snapshot = db_models.FinanceCashSnapshot(
        snapshot_id=uuid.uuid4(),
        org_id=org_id,
        as_of_date=as_of_date,
        cash_cents=cash_cents,
        note=note,
        created_at=datetime.now(timezone.utc),
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def update_cash_snapshot(
    session: AsyncSession,
    org_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    *,
    as_of_date: date | None = None,
    cash_cents: int | None = None,
    note: str | None = None,
    note_set: bool = False,
) -> db_models.FinanceCashSnapshot | None:
    snapshot = await get_cash_snapshot(session, org_id, snapshot_id)
    if not snapshot:
        return None

    if as_of_date is not None and as_of_date != snapshot.as_of_date:
        existing_stmt = select(db_models.FinanceCashSnapshot.snapshot_id).where(
            db_models.FinanceCashSnapshot.org_id == org_id,
            db_models.FinanceCashSnapshot.as_of_date == as_of_date,
            db_models.FinanceCashSnapshot.snapshot_id != snapshot_id,
        )
        existing = await session.execute(existing_stmt)
        if existing.scalar_one_or_none() is not None:
            return None
        snapshot.as_of_date = as_of_date

    if cash_cents is not None:
        snapshot.cash_cents = cash_cents
    if note_set:
        snapshot.note = note

    await session.flush()
    return snapshot


async def delete_cash_snapshot(
    session: AsyncSession,
    org_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> bool:
    snapshot = await get_cash_snapshot(session, org_id, snapshot_id)
    if not snapshot:
        return False
    await session.delete(snapshot)
    await session.flush()
    return True


async def create_expense(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    occurred_on: date,
    category_id: uuid.UUID,
    vendor: str | None,
    description: str,
    amount_cents: int,
    tax_cents: int,
    receipt_url: str | None,
    payment_method: str | None,
    created_by_user_id: uuid.UUID | None = None,
) -> db_models.FinanceExpense | None:
    category = await get_expense_category(session, org_id, category_id)
    if not category:
        return None

    expense = db_models.FinanceExpense(
        expense_id=uuid.uuid4(),
        org_id=org_id,
        occurred_on=occurred_on,
        category_id=category_id,
        vendor=vendor,
        description=description,
        amount_cents=amount_cents,
        tax_cents=tax_cents,
        receipt_url=receipt_url,
        payment_method=payment_method,
        created_at=datetime.now(timezone.utc),
        created_by_user_id=created_by_user_id,
    )
    session.add(expense)
    await session.flush()
    return expense


async def update_expense(
    session: AsyncSession,
    org_id: uuid.UUID,
    expense_id: uuid.UUID,
    *,
    occurred_on: date | None = None,
    category_id: uuid.UUID | None = None,
    vendor: str | None = None,
    vendor_set: bool = False,
    description: str | None = None,
    amount_cents: int | None = None,
    tax_cents: int | None = None,
    receipt_url: str | None = None,
    receipt_url_set: bool = False,
    payment_method: str | None = None,
    payment_method_set: bool = False,
) -> db_models.FinanceExpense | None:
    expense = await get_expense(session, org_id, expense_id)
    if not expense:
        return None

    if category_id is not None:
        category = await get_expense_category(session, org_id, category_id)
        if not category:
            return None
        expense.category_id = category_id

    if occurred_on is not None:
        expense.occurred_on = occurred_on
    if vendor_set:
        expense.vendor = vendor
    if description is not None:
        expense.description = description
    if amount_cents is not None:
        expense.amount_cents = amount_cents
    if tax_cents is not None:
        expense.tax_cents = tax_cents
    if receipt_url_set:
        expense.receipt_url = receipt_url
    if payment_method_set:
        expense.payment_method = payment_method

    await session.flush()
    return expense


async def delete_expense(
    session: AsyncSession,
    org_id: uuid.UUID,
    expense_id: uuid.UUID,
) -> bool:
    expense = await get_expense(session, org_id, expense_id)
    if not expense:
        return False
    await session.delete(expense)
    await session.flush()
    return True


async def list_budgets(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    month_yyyymm: str | None = None,
    category_id: uuid.UUID | None = None,
) -> list[tuple[db_models.FinanceBudget, str]]:
    stmt = (
        select(db_models.FinanceBudget, db_models.FinanceExpenseCategory.name)
        .join(
            db_models.FinanceExpenseCategory,
            db_models.FinanceBudget.category_id == db_models.FinanceExpenseCategory.category_id,
        )
        .where(db_models.FinanceBudget.org_id == org_id)
    )
    if month_yyyymm:
        stmt = stmt.where(db_models.FinanceBudget.month_yyyymm == month_yyyymm)
    if category_id:
        stmt = stmt.where(db_models.FinanceBudget.category_id == category_id)

    stmt = stmt.order_by(
        db_models.FinanceBudget.month_yyyymm.desc(),
        db_models.FinanceExpenseCategory.name.asc(),
    )
    result = await session.execute(stmt)
    return list(result.all())


async def get_budget(
    session: AsyncSession,
    org_id: uuid.UUID,
    budget_id: uuid.UUID,
) -> db_models.FinanceBudget | None:
    stmt = select(db_models.FinanceBudget).where(
        db_models.FinanceBudget.org_id == org_id,
        db_models.FinanceBudget.budget_id == budget_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_budget(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    month_yyyymm: str,
    category_id: uuid.UUID,
    amount_cents: int,
) -> db_models.FinanceBudget | None:
    category = await get_expense_category(session, org_id, category_id)
    if not category:
        return None

    budget = db_models.FinanceBudget(
        budget_id=uuid.uuid4(),
        org_id=org_id,
        month_yyyymm=month_yyyymm,
        category_id=category_id,
        amount_cents=amount_cents,
        created_at=datetime.now(timezone.utc),
    )
    session.add(budget)
    await session.flush()
    return budget


async def update_budget(
    session: AsyncSession,
    org_id: uuid.UUID,
    budget_id: uuid.UUID,
    *,
    month_yyyymm: str | None = None,
    category_id: uuid.UUID | None = None,
    amount_cents: int | None = None,
) -> db_models.FinanceBudget | None:
    budget = await get_budget(session, org_id, budget_id)
    if not budget:
        return None

    if category_id is not None:
        category = await get_expense_category(session, org_id, category_id)
        if not category:
            return None
        budget.category_id = category_id

    if month_yyyymm is not None:
        budget.month_yyyymm = month_yyyymm
    if amount_cents is not None:
        budget.amount_cents = amount_cents

    await session.flush()
    return budget


async def delete_budget(
    session: AsyncSession,
    org_id: uuid.UUID,
    budget_id: uuid.UUID,
) -> bool:
    budget = await get_budget(session, org_id, budget_id)
    if not budget:
        return False
    await session.delete(budget)
    await session.flush()
    return True


async def summarize_expenses(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    expense_stmt = (
        select(
            db_models.FinanceExpense.category_id,
            func.sum(db_models.FinanceExpense.amount_cents).label("total_cents"),
            func.sum(db_models.FinanceExpense.tax_cents).label("tax_cents"),
        )
        .where(
            db_models.FinanceExpense.org_id == org_id,
            db_models.FinanceExpense.occurred_on >= from_date,
            db_models.FinanceExpense.occurred_on <= to_date,
        )
        .group_by(db_models.FinanceExpense.category_id)
    )
    expense_result = await session.execute(expense_stmt)
    expense_rows = expense_result.all()

    month_keys = _month_range(from_date, to_date)
    budget_stmt = (
        select(
            db_models.FinanceBudget.category_id,
            func.sum(db_models.FinanceBudget.amount_cents).label("budget_cents"),
        )
        .where(
            db_models.FinanceBudget.org_id == org_id,
            db_models.FinanceBudget.month_yyyymm.in_(month_keys),
        )
        .group_by(db_models.FinanceBudget.category_id)
    )
    budget_result = await session.execute(budget_stmt)
    budget_rows = budget_result.all()

    expense_totals = {
        row.category_id: {
            "total_cents": int(row.total_cents or 0),
            "tax_cents": int(row.tax_cents or 0),
        }
        for row in expense_rows
    }
    budget_totals = {row.category_id: int(row.budget_cents or 0) for row in budget_rows}

    category_ids = set(expense_totals.keys()) | set(budget_totals.keys())
    categories: dict[uuid.UUID, str] = {}
    if category_ids:
        category_stmt = select(
            db_models.FinanceExpenseCategory.category_id,
            db_models.FinanceExpenseCategory.name,
        ).where(
            db_models.FinanceExpenseCategory.org_id == org_id,
            db_models.FinanceExpenseCategory.category_id.in_(category_ids),
        )
        category_result = await session.execute(category_stmt)
        categories = {row.category_id: row.name for row in category_result.all()}

    summary_rows: list[dict[str, object]] = []
    total_cents = 0
    total_tax_cents = 0
    total_budget_cents = 0

    for category_id in sorted(category_ids, key=lambda cid: categories.get(cid, "")):
        totals = expense_totals.get(category_id, {"total_cents": 0, "tax_cents": 0})
        budget_cents = budget_totals.get(category_id, 0)
        percent_of_budget = None
        if budget_cents > 0:
            percent_of_budget = totals["total_cents"] / budget_cents

        total_cents += totals["total_cents"]
        total_tax_cents += totals["tax_cents"]
        total_budget_cents += budget_cents

        summary_rows.append(
            {
                "category_id": category_id,
                "category_name": categories.get(category_id, "Uncategorized"),
                "total_cents": totals["total_cents"],
                "tax_cents": totals["tax_cents"],
                "budget_cents": budget_cents,
                "percent_of_budget": percent_of_budget,
            }
        )

    totals_summary = {
        "total_cents": total_cents,
        "total_tax_cents": total_tax_cents,
        "total_budget_cents": total_budget_cents,
    }

    return summary_rows, totals_summary


def _quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    if quarter == 1:
        start = date(year, 1, 1)
        end = date(year, 3, 31)
    elif quarter == 2:
        start = date(year, 4, 1)
        end = date(year, 6, 30)
    elif quarter == 3:
        start = date(year, 7, 1)
        end = date(year, 9, 30)
    else:
        start = date(year, 10, 1)
        end = date(year, 12, 31)
    return start, end


def _gst_due_date(period_end: date) -> date:
    next_month = period_end.month + 1
    year = period_end.year
    if next_month > 12:
        next_month = 1
        year += 1
    last_day = calendar.monthrange(year, next_month)[1]
    return date(year, next_month, last_day)


def build_gst_calendar(from_date: date, to_date: date) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for year in range(from_date.year, to_date.year + 1):
        for quarter in range(1, 5):
            period_start, period_end = _quarter_bounds(year, quarter)
            due_on = _gst_due_date(period_end)
            if due_on < from_date or due_on > to_date:
                continue
            entries.append(
                {
                    "tax_type": "GST",
                    "label": f"GST Q{quarter} {year}",
                    "period_start": period_start,
                    "period_end": period_end,
                    "due_on": due_on,
                }
            )
    return entries


async def summarize_gst(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> dict[str, object]:
    start_dt, end_dt = _date_bounds(from_date, to_date)
    payment_timestamp = func.coalesce(Payment.received_at, Payment.created_at)

    payment_stmt = (
        select(
            Payment.amount_cents,
            Payment.currency,
            Invoice.tax_cents,
            Invoice.total_cents,
        )
        .join(Invoice, Payment.invoice_id == Invoice.invoice_id)
        .where(
            Payment.org_id == org_id,
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            payment_timestamp >= start_dt,
            payment_timestamp < end_dt,
        )
    )
    payment_result = await session.execute(payment_stmt)
    payment_rows = payment_result.all()

    tax_collected_cents = 0
    currency_code = "CAD"
    if payment_rows:
        currency_code = payment_rows[0].currency or "CAD"
    for row in payment_rows:
        if row.total_cents and row.total_cents > 0:
            ratio = Decimal(row.tax_cents) / Decimal(row.total_cents)
            allocated = Decimal(row.amount_cents) * ratio
            tax_collected_cents += int(allocated.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    expense_tax_stmt = select(func.coalesce(func.sum(db_models.FinanceExpense.tax_cents), 0)).where(
        db_models.FinanceExpense.org_id == org_id,
        db_models.FinanceExpense.occurred_on >= from_date,
        db_models.FinanceExpense.occurred_on <= to_date,
    )
    expense_tax_result = await session.execute(expense_tax_stmt)
    tax_paid_cents = int(expense_tax_result.scalar_one() or 0)

    tax_owed_cents = tax_collected_cents - tax_paid_cents
    return {
        "from": from_date,
        "to": to_date,
        "tax_collected_cents": tax_collected_cents,
        "tax_paid_cents": tax_paid_cents,
        "tax_owed_cents": tax_owed_cents,
        "currency_code": currency_code,
    }


async def list_tax_instalments(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[db_models.FinanceTaxInstalment]:
    stmt = select(db_models.FinanceTaxInstalment).where(db_models.FinanceTaxInstalment.org_id == org_id)
    if from_date:
        stmt = stmt.where(db_models.FinanceTaxInstalment.due_on >= from_date)
    if to_date:
        stmt = stmt.where(db_models.FinanceTaxInstalment.due_on <= to_date)
    stmt = stmt.order_by(db_models.FinanceTaxInstalment.due_on.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_tax_instalment(
    session: AsyncSession,
    org_id: uuid.UUID,
    instalment_id: uuid.UUID,
) -> db_models.FinanceTaxInstalment | None:
    stmt = select(db_models.FinanceTaxInstalment).where(
        db_models.FinanceTaxInstalment.org_id == org_id,
        db_models.FinanceTaxInstalment.instalment_id == instalment_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_tax_instalment(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    tax_type: str,
    due_on: date,
    amount_cents: int,
    paid_on: date | None,
    note: str | None,
    created_by_user_id: uuid.UUID | None,
) -> db_models.FinanceTaxInstalment:
    instalment = db_models.FinanceTaxInstalment(
        instalment_id=uuid.uuid4(),
        org_id=org_id,
        tax_type=tax_type,
        due_on=due_on,
        amount_cents=amount_cents,
        paid_on=paid_on,
        note=note,
        created_at=datetime.now(timezone.utc),
        created_by_user_id=created_by_user_id,
    )
    session.add(instalment)
    await session.flush()
    return instalment


async def update_tax_instalment(
    session: AsyncSession,
    org_id: uuid.UUID,
    instalment_id: uuid.UUID,
    *,
    tax_type: str | None = None,
    due_on: date | None = None,
    amount_cents: int | None = None,
    paid_on: date | None = None,
    paid_on_set: bool = False,
    note: str | None = None,
    note_set: bool = False,
) -> db_models.FinanceTaxInstalment | None:
    instalment = await get_tax_instalment(session, org_id, instalment_id)
    if not instalment:
        return None
    if tax_type is not None:
        instalment.tax_type = tax_type
    if due_on is not None:
        instalment.due_on = due_on
    if amount_cents is not None:
        instalment.amount_cents = amount_cents
    if paid_on_set:
        instalment.paid_on = paid_on
    if note_set:
        instalment.note = note
    await session.flush()
    return instalment


async def create_tax_export_log(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
    created_by_user_id: uuid.UUID | None,
) -> db_models.FinanceTaxExport:
    export_log = db_models.FinanceTaxExport(
        export_id=uuid.uuid4(),
        org_id=org_id,
        from_date=from_date,
        to_date=to_date,
        created_at=datetime.now(timezone.utc),
        created_by_user_id=created_by_user_id,
    )
    session.add(export_log)
    await session.flush()
    return export_log


async def list_tax_payments(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> list[dict[str, object]]:
    start_dt, end_dt = _date_bounds(from_date, to_date)
    payment_timestamp = func.coalesce(Payment.received_at, Payment.created_at)
    stmt = (
        select(
            Payment.payment_id,
            Payment.invoice_id,
            Payment.amount_cents,
            Payment.currency,
            payment_timestamp.label("paid_at"),
            Invoice.invoice_number,
            Invoice.tax_cents,
            Invoice.total_cents,
        )
        .join(Invoice, Payment.invoice_id == Invoice.invoice_id)
        .where(
            Payment.org_id == org_id,
            Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
            payment_timestamp >= start_dt,
            payment_timestamp < end_dt,
        )
        .order_by(payment_timestamp.asc())
    )
    result = await session.execute(stmt)
    rows = result.all()
    entries: list[dict[str, object]] = []
    for row in rows:
        allocated_tax = 0
        if row.total_cents and row.total_cents > 0:
            ratio = Decimal(row.tax_cents) / Decimal(row.total_cents)
            allocated_tax = int(
                (Decimal(row.amount_cents) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
        entries.append(
            {
                "payment_id": row.payment_id,
                "invoice_id": row.invoice_id,
                "invoice_number": row.invoice_number,
                "paid_at": row.paid_at,
                "amount_cents": row.amount_cents,
                "currency": row.currency,
                "allocated_tax_cents": allocated_tax,
            }
        )
    return entries


async def list_tax_expenses(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> list[db_models.FinanceExpense]:
    stmt = select(db_models.FinanceExpense).where(
        db_models.FinanceExpense.org_id == org_id,
        db_models.FinanceExpense.occurred_on >= from_date,
        db_models.FinanceExpense.occurred_on <= to_date,
    )
    stmt = stmt.order_by(db_models.FinanceExpense.occurred_on.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())
