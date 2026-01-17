"""Admin API endpoints for finance expenses, categories, and budgets."""

from __future__ import annotations

import csv
import io
import uuid
import zipfile
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_auth import AdminIdentity, get_admin_identity, permission_keys_for_request
from app.api.org_context import require_org_context
from app.api.problem_details import PROBLEM_TYPE_DOMAIN, problem_details
from app.domain.finance import schemas, service
from app.infra.db import get_db_session

router = APIRouter(tags=["admin-finance"])


def _require_finance_view(request: Request, identity: AdminIdentity) -> None:
    permission_keys = permission_keys_for_request(request, identity)
    if "finance.view" not in permission_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: requires finance.view permission",
        )


def _require_finance_manage(request: Request, identity: AdminIdentity) -> None:
    permission_keys = permission_keys_for_request(request, identity)
    if "finance.manage" not in permission_keys and "admin.manage" not in permission_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: requires finance.manage or admin.manage permission",
        )


@router.get(
    "/v1/admin/finance/expense-categories",
    response_model=schemas.FinanceExpenseCategoryListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_finance_expense_categories(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> schemas.FinanceExpenseCategoryListResponse:
    _require_finance_view(request, identity)

    if page_size > 100:
        page_size = 100
    if page < 1:
        page = 1

    categories, total = await service.list_expense_categories(
        session,
        org_id,
        query=query,
        page=page,
        page_size=page_size,
    )

    return schemas.FinanceExpenseCategoryListResponse(
        items=[schemas.FinanceExpenseCategoryResponse.model_validate(c) for c in categories],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/v1/admin/finance/expense-categories",
    response_model=schemas.FinanceExpenseCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_finance_expense_category(
    request: Request,
    data: schemas.FinanceExpenseCategoryCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.FinanceExpenseCategoryResponse:
    _require_finance_manage(request, identity)

    category = await service.create_expense_category(
        session,
        org_id,
        name=data.name,
        default=data.default,
        sort_order=data.sort_order,
    )
    await session.commit()

    return schemas.FinanceExpenseCategoryResponse.model_validate(category)


@router.patch(
    "/v1/admin/finance/expense-categories/{category_id}",
    response_model=schemas.FinanceExpenseCategoryResponse,
    status_code=status.HTTP_200_OK,
)
async def update_finance_expense_category(
    category_id: uuid.UUID,
    data: schemas.FinanceExpenseCategoryUpdate,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    category = await service.update_expense_category(
        session,
        org_id,
        category_id,
        name=data.name,
        default=data.default,
        sort_order=data.sort_order,
    )
    if not category:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Category Not Found",
            detail=f"Category {category_id} not found",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return schemas.FinanceExpenseCategoryResponse.model_validate(category)


@router.delete(
    "/v1/admin/finance/expense-categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_finance_expense_category(
    category_id: uuid.UUID,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    deleted = await service.delete_expense_category(session, org_id, category_id)
    if not deleted:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Category Not Found",
            detail=f"Category {category_id} not found",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/v1/admin/finance/expenses",
    response_model=schemas.FinanceExpenseListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_finance_expenses(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    category_id: uuid.UUID | None = None,
    query: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> schemas.FinanceExpenseListResponse:
    _require_finance_view(request, identity)

    if page_size > 100:
        page_size = 100
    if page < 1:
        page = 1

    expenses, total = await service.list_expenses(
        session,
        org_id,
        from_date=from_date,
        to_date=to_date,
        category_id=category_id,
        query=query,
        page=page,
        page_size=page_size,
    )

    items = [
        schemas.FinanceExpenseResponse
        .model_validate(expense)
        .model_copy(update={"category_name": category_name})
        for expense, category_name in expenses
    ]

    return schemas.FinanceExpenseListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/v1/admin/finance/expenses",
    response_model=schemas.FinanceExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_finance_expense(
    request: Request,
    data: schemas.FinanceExpenseCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    expense = await service.create_expense(
        session,
        org_id,
        occurred_on=data.occurred_on,
        category_id=data.category_id,
        vendor=data.vendor,
        description=data.description,
        amount_cents=data.amount_cents,
        tax_cents=data.tax_cents,
        receipt_url=data.receipt_url,
        payment_method=data.payment_method,
        created_by_user_id=None,
    )
    if not expense:
        return problem_details(
            request=request,
            status=status.HTTP_400_BAD_REQUEST,
            title="Invalid Category",
            detail="Expense category does not exist in this organization",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    response = schemas.FinanceExpenseResponse.model_validate(expense)
    return response


@router.patch(
    "/v1/admin/finance/expenses/{expense_id}",
    response_model=schemas.FinanceExpenseResponse,
    status_code=status.HTTP_200_OK,
)
async def update_finance_expense(
    expense_id: uuid.UUID,
    data: schemas.FinanceExpenseUpdate,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    existing = await service.get_expense(session, org_id, expense_id)
    if not existing:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Expense Not Found",
            detail=f"Expense {expense_id} not found",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    fields_set = data.model_fields_set
    if "category_id" in fields_set:
        if data.category_id is None:
            return problem_details(
                request=request,
                status=status.HTTP_400_BAD_REQUEST,
                title="Invalid Category",
                detail="Expense category is required",
                type_=PROBLEM_TYPE_DOMAIN,
            )
        category = await service.get_expense_category(session, org_id, data.category_id)
        if not category:
            return problem_details(
                request=request,
                status=status.HTTP_400_BAD_REQUEST,
                title="Invalid Category",
                detail="Expense category does not exist in this organization",
                type_=PROBLEM_TYPE_DOMAIN,
            )

    updated = await service.update_expense(
        session,
        org_id,
        expense_id,
        occurred_on=data.occurred_on,
        category_id=data.category_id,
        vendor=data.vendor,
        vendor_set="vendor" in fields_set,
        description=data.description,
        amount_cents=data.amount_cents,
        tax_cents=data.tax_cents,
        receipt_url=data.receipt_url,
        receipt_url_set="receipt_url" in fields_set,
        payment_method=data.payment_method,
        payment_method_set="payment_method" in fields_set,
    )
    if not updated:
        return problem_details(
            request=request,
            status=status.HTTP_400_BAD_REQUEST,
            title="Expense Update Failed",
            detail="Unable to update expense with provided data",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return schemas.FinanceExpenseResponse.model_validate(updated)


@router.delete(
    "/v1/admin/finance/expenses/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_finance_expense(
    expense_id: uuid.UUID,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    deleted = await service.delete_expense(session, org_id, expense_id)
    if not deleted:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Expense Not Found",
            detail=f"Expense {expense_id} not found",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/v1/admin/finance/budgets",
    response_model=schemas.FinanceBudgetListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_finance_budgets(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    month: str | None = None,
    category_id: uuid.UUID | None = None,
) -> schemas.FinanceBudgetListResponse:
    _require_finance_view(request, identity)

    budgets = await service.list_budgets(
        session,
        org_id,
        month_yyyymm=month,
        category_id=category_id,
    )

    items = [
        schemas.FinanceBudgetResponse
        .model_validate(budget)
        .model_copy(update={"category_name": category_name})
        for budget, category_name in budgets
    ]

    return schemas.FinanceBudgetListResponse(items=items)


@router.post(
    "/v1/admin/finance/budgets",
    response_model=schemas.FinanceBudgetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_finance_budget(
    request: Request,
    data: schemas.FinanceBudgetCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    budget = await service.create_budget(
        session,
        org_id,
        month_yyyymm=data.month_yyyymm,
        category_id=data.category_id,
        amount_cents=data.amount_cents,
    )
    if not budget:
        return problem_details(
            request=request,
            status=status.HTTP_400_BAD_REQUEST,
            title="Invalid Category",
            detail="Budget category does not exist in this organization",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return schemas.FinanceBudgetResponse.model_validate(budget)


@router.patch(
    "/v1/admin/finance/budgets/{budget_id}",
    response_model=schemas.FinanceBudgetResponse,
    status_code=status.HTTP_200_OK,
)
async def update_finance_budget(
    budget_id: uuid.UUID,
    data: schemas.FinanceBudgetUpdate,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    existing = await service.get_budget(session, org_id, budget_id)
    if not existing:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Budget Not Found",
            detail=f"Budget {budget_id} not found",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    fields_set = data.model_fields_set
    if "category_id" in fields_set:
        if data.category_id is None:
            return problem_details(
                request=request,
                status=status.HTTP_400_BAD_REQUEST,
                title="Invalid Category",
                detail="Budget category is required",
                type_=PROBLEM_TYPE_DOMAIN,
            )
        category = await service.get_expense_category(session, org_id, data.category_id)
        if not category:
            return problem_details(
                request=request,
                status=status.HTTP_400_BAD_REQUEST,
                title="Invalid Category",
                detail="Budget category does not exist in this organization",
                type_=PROBLEM_TYPE_DOMAIN,
            )

    updated = await service.update_budget(
        session,
        org_id,
        budget_id,
        month_yyyymm=data.month_yyyymm,
        category_id=data.category_id,
        amount_cents=data.amount_cents,
    )
    if not updated:
        return problem_details(
            request=request,
            status=status.HTTP_400_BAD_REQUEST,
            title="Budget Update Failed",
            detail="Unable to update budget with provided data",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return schemas.FinanceBudgetResponse.model_validate(updated)


@router.delete(
    "/v1/admin/finance/budgets/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_finance_budget(
    budget_id: uuid.UUID,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    deleted = await service.delete_budget(session, org_id, budget_id)
    if not deleted:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Budget Not Found",
            detail=f"Budget {budget_id} not found",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/v1/admin/finance/expenses/summary",
    response_model=schemas.FinanceExpenseSummaryResponse,
    status_code=status.HTTP_200_OK,
)
async def get_finance_expense_summary(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
) -> schemas.FinanceExpenseSummaryResponse:
    _require_finance_view(request, identity)

    categories, totals = await service.summarize_expenses(
        session,
        org_id,
        from_date=from_date,
        to_date=to_date,
    )

    percent_of_budget = None
    if totals["total_budget_cents"] > 0:
        percent_of_budget = totals["total_cents"] / totals["total_budget_cents"]

    return schemas.FinanceExpenseSummaryResponse(
        from_date=from_date,
        to_date=to_date,
        total_cents=totals["total_cents"],
        total_tax_cents=totals["total_tax_cents"],
        total_budget_cents=totals["total_budget_cents"],
        percent_of_budget=percent_of_budget,
        categories=[schemas.FinanceExpenseSummaryCategory(**item) for item in categories],
    )


@router.get(
    "/v1/admin/finance/pnl",
    response_model=schemas.FinancePnlResponse,
    status_code=status.HTTP_200_OK,
)
async def get_finance_pnl(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    format: str | None = Query(default=None, pattern="^(json|csv)$"),
) -> Response:
    _require_finance_view(request, identity)

    summary = await service.summarize_pnl(
        session,
        org_id,
        from_date=from_date,
        to_date=to_date,
    )

    payload = schemas.FinancePnlResponse(
        **summary,
        from_date=from_date,
        to_date=to_date,
        data_sources=schemas.FinancePnlDataSources(
            revenue="invoice_payments (status=SUCCEEDED, received_at/created_at)",
            expenses="finance_expenses",
        ),
    )

    if format == "csv":
        lines = [
            "section,label,total_cents,tax_cents",
            f"summary,revenue,{payload.revenue_cents},",
            f"summary,expenses,{payload.expense_cents},",
            f"summary,net,{payload.net_cents},",
        ]
        lines.extend(
            f"revenue_breakdown,{item.label},{item.total_cents},"
            for item in payload.revenue_breakdown
        )
        lines.extend(
            f"expense_category,{item.category_name},{item.total_cents},{item.tax_cents}"
            for item in payload.expense_breakdown_by_category
        )
        return Response("\n".join(lines), media_type="text/csv")

    return payload


@router.get(
    "/v1/admin/finance/cashflow",
    response_model=schemas.FinanceCashflowResponse,
    status_code=status.HTTP_200_OK,
)
async def get_finance_cashflow(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
) -> schemas.FinanceCashflowResponse:
    _require_finance_view(request, identity)

    summary = await service.summarize_cashflow(
        session,
        org_id,
        from_date=from_date,
        to_date=to_date,
    )

    start_snapshot = await service.get_cash_snapshot_on_or_before(session, org_id, from_date)
    end_snapshot = await service.get_cash_snapshot_on_or_before(session, org_id, to_date)

    payload = schemas.FinanceCashflowResponse(
        **summary,
        from_date=from_date,
        to_date=to_date,
        data_sources=schemas.FinanceCashflowDataSources(
            inflows="invoice_payments (status=SUCCEEDED, received_at/created_at)",
            outflows="finance_expenses",
        ),
        start_cash_snapshot=(
            schemas.FinanceCashSnapshotResponse.model_validate(start_snapshot)
            if start_snapshot
            else None
        ),
        end_cash_snapshot=(
            schemas.FinanceCashSnapshotResponse.model_validate(end_snapshot)
            if end_snapshot
            else None
        ),
    )

    return payload


@router.get(
    "/v1/admin/finance/balance_sheet",
    response_model=schemas.FinanceBalanceSheetResponse,
    status_code=status.HTTP_200_OK,
)
async def get_finance_balance_sheet(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    as_of: date = Query(...),
) -> schemas.FinanceBalanceSheetResponse:
    _require_finance_view(request, identity)

    cash_snapshot = await service.get_cash_snapshot_on_or_before(session, org_id, as_of)
    accounts_receivable_cents = await service.summarize_accounts_receivable(
        session,
        org_id,
        as_of_date=as_of,
    )

    cash_cents = cash_snapshot.cash_cents if cash_snapshot else None
    assets_total_cents = (
        cash_cents + accounts_receivable_cents if cash_cents is not None else None
    )

    liabilities_total_cents = 0
    equity_cents = (
        assets_total_cents - liabilities_total_cents if assets_total_cents is not None else None
    )

    data_coverage_notes = [
        "Accounts payable is not tracked; liabilities exclude unpaid expenses.",
        "GST payable is not tracked; liabilities exclude GST payable.",
    ]
    if cash_snapshot is None:
        data_coverage_notes.append(
            "Cash is reported as unknown because no cash snapshot exists on or before the as_of date."
        )

    return schemas.FinanceBalanceSheetResponse(
        as_of=as_of,
        assets=schemas.FinanceBalanceSheetAssets(
            cash=schemas.FinanceBalanceSheetCash(
                cash_cents=cash_cents,
                as_of_date=cash_snapshot.as_of_date if cash_snapshot else None,
                note=cash_snapshot.note if cash_snapshot else None,
            ),
            accounts_receivable_cents=accounts_receivable_cents,
            total_assets_cents=assets_total_cents,
        ),
        liabilities=schemas.FinanceBalanceSheetLiabilities(
            accounts_payable_cents=None,
            gst_payable_cents=None,
            total_liabilities_cents=liabilities_total_cents,
        ),
        equity=schemas.FinanceBalanceSheetEquity(
            simplified_equity_cents=equity_cents,
            formula="assets - liabilities (simplified)",
        ),
        data_sources=schemas.FinanceBalanceSheetDataSources(
            cash="finance_cash_snapshots (latest on or before as_of)",
            accounts_receivable=(
                "invoices (status SENT/PARTIAL/OVERDUE, issue_date <= as_of) "
                "minus payments received on or before as_of"
            ),
            liabilities="Not tracked (accounts payable, GST payable).",
        ),
        data_coverage_notes=data_coverage_notes,
    )


@router.get(
    "/v1/admin/finance/cash_snapshots",
    response_model=schemas.FinanceCashSnapshotListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_finance_cash_snapshots(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
) -> schemas.FinanceCashSnapshotListResponse:
    _require_finance_view(request, identity)

    snapshots = await service.list_cash_snapshots(
        session,
        org_id,
        from_date=from_date,
        to_date=to_date,
    )
    return schemas.FinanceCashSnapshotListResponse(
        items=[schemas.FinanceCashSnapshotResponse.model_validate(snapshot) for snapshot in snapshots]
    )


@router.post(
    "/v1/admin/finance/cash_snapshots",
    response_model=schemas.FinanceCashSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_finance_cash_snapshot(
    request: Request,
    data: schemas.FinanceCashSnapshotCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    snapshot = await service.create_cash_snapshot(
        session,
        org_id,
        as_of_date=data.as_of_date,
        cash_cents=data.cash_cents,
        note=data.note,
    )
    if not snapshot:
        return problem_details(
            request=request,
            status=status.HTTP_409_CONFLICT,
            title="Snapshot Exists",
            detail="A cash snapshot already exists for this date",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return schemas.FinanceCashSnapshotResponse.model_validate(snapshot)


@router.patch(
    "/v1/admin/finance/cash_snapshots/{snapshot_id}",
    response_model=schemas.FinanceCashSnapshotResponse,
    status_code=status.HTTP_200_OK,
)
async def update_finance_cash_snapshot(
    snapshot_id: uuid.UUID,
    data: schemas.FinanceCashSnapshotUpdate,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    existing = await service.get_cash_snapshot(session, org_id, snapshot_id)
    if not existing:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Cash Snapshot Not Found",
            detail=f"Cash snapshot {snapshot_id} not found",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    updated = await service.update_cash_snapshot(
        session,
        org_id,
        snapshot_id,
        as_of_date=data.as_of_date,
        cash_cents=data.cash_cents,
        note=data.note,
        note_set="note" in data.model_fields_set,
    )
    if not updated:
        return problem_details(
            request=request,
            status=status.HTTP_409_CONFLICT,
            title="Cash Snapshot Conflict",
            detail="Another cash snapshot already exists for this date",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return schemas.FinanceCashSnapshotResponse.model_validate(updated)


@router.delete(
    "/v1/admin/finance/cash_snapshots/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_finance_cash_snapshot(
    snapshot_id: uuid.UUID,
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    deleted = await service.delete_cash_snapshot(session, org_id, snapshot_id)
    if not deleted:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Cash Snapshot Not Found",
            detail=f"Cash snapshot {snapshot_id} not found",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/v1/admin/finance/taxes/gst_summary",
    response_model=schemas.FinanceGstSummaryResponse,
    status_code=status.HTTP_200_OK,
)
async def get_finance_gst_summary(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
) -> schemas.FinanceGstSummaryResponse:
    _require_finance_view(request, identity)

    summary = await service.summarize_gst(session, org_id, from_date=from_date, to_date=to_date)
    return schemas.FinanceGstSummaryResponse.model_validate(summary)


@router.get(
    "/v1/admin/finance/taxes/instalments",
    response_model=schemas.FinanceTaxInstalmentListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_finance_tax_instalments(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
) -> schemas.FinanceTaxInstalmentListResponse:
    _require_finance_view(request, identity)

    instalments = await service.list_tax_instalments(
        session,
        org_id,
        from_date=from_date,
        to_date=to_date,
    )
    return schemas.FinanceTaxInstalmentListResponse(
        items=[schemas.FinanceTaxInstalmentResponse.model_validate(item) for item in instalments]
    )


@router.post(
    "/v1/admin/finance/taxes/instalments",
    response_model=schemas.FinanceTaxInstalmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_finance_tax_instalment(
    request: Request,
    data: schemas.FinanceTaxInstalmentCreate,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> schemas.FinanceTaxInstalmentResponse:
    _require_finance_manage(request, identity)

    instalment = await service.create_tax_instalment(
        session,
        org_id,
        tax_type=data.tax_type,
        due_on=data.due_on,
        amount_cents=data.amount_cents,
        paid_on=data.paid_on,
        note=data.note,
        created_by_user_id=None,
    )
    await session.commit()
    return schemas.FinanceTaxInstalmentResponse.model_validate(instalment)


@router.patch(
    "/v1/admin/finance/taxes/instalments/{instalment_id}",
    response_model=schemas.FinanceTaxInstalmentResponse,
    status_code=status.HTTP_200_OK,
)
async def update_finance_tax_instalment(
    instalment_id: uuid.UUID,
    request: Request,
    data: schemas.FinanceTaxInstalmentUpdate,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _require_finance_manage(request, identity)

    updated = await service.update_tax_instalment(
        session,
        org_id,
        instalment_id,
        tax_type=data.tax_type,
        due_on=data.due_on,
        amount_cents=data.amount_cents,
        paid_on=data.paid_on,
        paid_on_set="paid_on" in data.model_fields_set,
        note=data.note,
        note_set="note" in data.model_fields_set,
    )
    if not updated:
        return problem_details(
            request=request,
            status=status.HTTP_404_NOT_FOUND,
            title="Tax Instalment Not Found",
            detail=f"Tax instalment {instalment_id} not found",
            type_=PROBLEM_TYPE_DOMAIN,
        )

    await session.commit()
    return schemas.FinanceTaxInstalmentResponse.model_validate(updated)


@router.get(
    "/v1/admin/finance/taxes/calendar",
    response_model=schemas.FinanceTaxCalendarResponse,
    status_code=status.HTTP_200_OK,
)
async def get_finance_tax_calendar(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
) -> schemas.FinanceTaxCalendarResponse:
    _require_finance_view(request, identity)

    today = date.today()
    effective_from = from_date or date(today.year, 1, 1)
    effective_to = to_date or date(today.year, 12, 31)
    entries = service.build_gst_calendar(effective_from, effective_to)
    return schemas.FinanceTaxCalendarResponse(items=entries)


@router.get(
    "/v1/admin/finance/taxes/export",
    status_code=status.HTTP_200_OK,
)
async def export_finance_taxes(
    request: Request,
    org_id: uuid.UUID = Depends(require_org_context),
    identity: AdminIdentity = Depends(get_admin_identity),
    session: AsyncSession = Depends(get_db_session),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
) -> Response:
    _require_finance_view(request, identity)

    summary = await service.summarize_gst(session, org_id, from_date=from_date, to_date=to_date)
    payments = await service.list_tax_payments(session, org_id, from_date=from_date, to_date=to_date)
    expenses = await service.list_tax_expenses(session, org_id, from_date=from_date, to_date=to_date)
    instalments = await service.list_tax_instalments(
        session,
        org_id,
        from_date=from_date,
        to_date=to_date,
    )
    await service.create_tax_export_log(
        session,
        org_id,
        from_date=from_date,
        to_date=to_date,
        created_by_user_id=None,
    )
    await session.commit()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        summary_csv = io.StringIO()
        summary_writer = csv.writer(summary_csv)
        summary_writer.writerow(
            [
                "from_date",
                "to_date",
                "tax_collected_cents",
                "tax_paid_cents",
                "tax_owed_cents",
                "currency_code",
            ]
        )
        summary_writer.writerow(
            [
                summary["from"],
                summary["to"],
                summary["tax_collected_cents"],
                summary["tax_paid_cents"],
                summary["tax_owed_cents"],
                summary["currency_code"],
            ]
        )
        zip_file.writestr("gst_summary.csv", summary_csv.getvalue())

        payments_csv = io.StringIO()
        payments_writer = csv.writer(payments_csv)
        payments_writer.writerow(
            [
                "payment_id",
                "invoice_id",
                "invoice_number",
                "paid_at",
                "amount_cents",
                "currency",
                "allocated_tax_cents",
            ]
        )
        for row in payments:
            payments_writer.writerow(
                [
                    row["payment_id"],
                    row["invoice_id"],
                    row["invoice_number"],
                    row["paid_at"],
                    row["amount_cents"],
                    row["currency"],
                    row["allocated_tax_cents"],
                ]
            )
        zip_file.writestr("gst_payments.csv", payments_csv.getvalue())

        expenses_csv = io.StringIO()
        expenses_writer = csv.writer(expenses_csv)
        expenses_writer.writerow(
            [
                "expense_id",
                "occurred_on",
                "vendor",
                "description",
                "amount_cents",
                "tax_cents",
                "payment_method",
            ]
        )
        for expense in expenses:
            expenses_writer.writerow(
                [
                    expense.expense_id,
                    expense.occurred_on,
                    expense.vendor or "",
                    expense.description,
                    expense.amount_cents,
                    expense.tax_cents,
                    expense.payment_method or "",
                ]
            )
        zip_file.writestr("gst_expenses.csv", expenses_csv.getvalue())

        instalments_csv = io.StringIO()
        instalments_writer = csv.writer(instalments_csv)
        instalments_writer.writerow(
            [
                "instalment_id",
                "tax_type",
                "due_on",
                "amount_cents",
                "paid_on",
                "note",
            ]
        )
        for instalment in instalments:
            instalments_writer.writerow(
                [
                    instalment.instalment_id,
                    instalment.tax_type,
                    instalment.due_on,
                    instalment.amount_cents,
                    instalment.paid_on,
                    instalment.note or "",
                ]
            )
        zip_file.writestr("tax_instalments.csv", instalments_csv.getvalue())

    filename = f"gst_export_{from_date.isoformat()}_{to_date.isoformat()}.zip"
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
