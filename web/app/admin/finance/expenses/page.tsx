"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const DEFAULT_PAGE_SIZE = 25;

type FinanceCategory = {
  category_id: string;
  name: string;
  default: boolean;
  sort_order: number;
};

type FinanceExpense = {
  expense_id: string;
  occurred_on: string;
  category_id: string;
  category_name?: string | null;
  vendor?: string | null;
  description: string;
  amount_cents: number;
  tax_cents: number;
  receipt_url?: string | null;
  payment_method?: string | null;
  created_at: string;
};

type FinanceCategoryListResponse = {
  items: FinanceCategory[];
  total: number;
  page: number;
  page_size: number;
};

type FinanceExpenseListResponse = {
  items: FinanceExpense[];
  total: number;
  page: number;
  page_size: number;
};

type FinanceSummaryCategory = {
  category_id: string;
  category_name: string;
  total_cents: number;
  tax_cents: number;
  budget_cents: number;
  percent_of_budget: number | null;
};

type FinanceExpenseSummaryResponse = {
  from_date: string;
  to_date: string;
  total_cents: number;
  total_tax_cents: number;
  total_budget_cents: number;
  percent_of_budget: number | null;
  categories: FinanceSummaryCategory[];
};

type ExpenseDraft = {
  occurred_on: string;
  category_id: string;
  vendor: string;
  description: string;
  amount: string;
  tax: string;
  receipt_url: string;
  payment_method: string;
};

type CategoryDraft = {
  name: string;
  default: boolean;
  sort_order: string;
};

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format(cents / 100);
}

function formatPercent(value: number | null) {
  if (value === null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatDateInput(value: Date) {
  return value.toISOString().slice(0, 10);
}

function formatCurrencyInput(cents: number) {
  return (cents / 100).toFixed(2);
}

function parseCurrencyInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed.length) return null;
  const normalized = trimmed.replace(/,/g, "");
  const numeric = Number(normalized);
  if (!Number.isFinite(numeric)) return null;
  return Math.round(numeric * 100);
}

function defaultFromDate() {
  const date = new Date();
  date.setDate(date.getDate() - 30);
  return formatDateInput(date);
}

export default function FinanceExpensesPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [categories, setCategories] = useState<FinanceCategory[]>([]);
  const [expenses, setExpenses] = useState<FinanceExpense[]>([]);
  const [summary, setSummary] = useState<FinanceExpenseSummaryResponse | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(DEFAULT_PAGE_SIZE);
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [fromDate, setFromDate] = useState(defaultFromDate);
  const [toDate, setToDate] = useState(() => formatDateInput(new Date()));
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingExpense, setEditingExpense] = useState<FinanceExpense | null>(null);
  const [draft, setDraft] = useState<ExpenseDraft>(() => ({
    occurred_on: formatDateInput(new Date()),
    category_id: "",
    vendor: "",
    description: "",
    amount: "",
    tax: "0.00",
    receipt_url: "",
    payment_method: "",
  }));
  const [draftErrors, setDraftErrors] = useState<string[]>([]);
  const [categoryModalOpen, setCategoryModalOpen] = useState(false);
  const [editingCategory, setEditingCategory] = useState<FinanceCategory | null>(null);
  const [categoryDraft, setCategoryDraft] = useState<CategoryDraft>({
    name: "",
    default: false,
    sort_order: "0",
  });
  const [categoryErrors, setCategoryErrors] = useState<string[]>([]);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [password, username]);

  const permissionKeys = profile?.permissions ?? [];
  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const pageVisible = visibilityReady
    ? isVisible("module.finance", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const canViewFinance = permissionKeys.includes("finance.view");
  const canManageFinance =
    permissionKeys.includes("finance.manage") || permissionKeys.includes("admin.manage");

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      {
        key: "notifications",
        label: "Notifications",
        href: "/admin/notifications",
        featureKey: "module.notifications_center",
      },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      {
        key: "finance-expenses",
        label: "Expenses",
        href: "/admin/finance/expenses",
        featureKey: "module.finance",
      },
      {
        key: "finance-budgets",
        label: "Budgets",
        href: "/admin/finance/budgets",
        featureKey: "module.finance",
      },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
    ];
    return candidates
      .filter((entry) => isVisible(entry.featureKey, permissionKeys, featureOverrides, hiddenKeys))
      .map(({ featureKey, ...link }) => link);
  }, [featureOverrides, hiddenKeys, permissionKeys, profile, visibilityReady]);

  const loadProfile = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/profile`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as AdminProfile;
      setProfile(data);
    }
  }, [authHeaders, password, username]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/feature-config`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/ui-prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    }
  }, [authHeaders, password, username]);

  const loadCategories = useCallback(async () => {
    if (!username || !password) return;
    const params = new URLSearchParams({ page: "1", page_size: "100" });
    const response = await fetch(
      `${API_BASE}/v1/admin/finance/expense-categories?${params.toString()}`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as FinanceCategoryListResponse;
      setCategories(data.items);
    }
  }, [authHeaders, password, username]);

  const loadExpenses = useCallback(async () => {
    if (!username || !password) return;
    setIsLoading(true);
    setErrorMessage(null);
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (fromDate) params.set("from", fromDate);
    if (toDate) params.set("to", toDate);
    if (categoryFilter) params.set("category_id", categoryFilter);
    if (query) params.set("query", query);

    const response = await fetch(`${API_BASE}/v1/admin/finance/expenses?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FinanceExpenseListResponse;
      setExpenses(data.items);
      setTotal(data.total);
    } else {
      setErrorMessage("Unable to load expenses.");
    }
    setIsLoading(false);
  }, [authHeaders, categoryFilter, fromDate, page, pageSize, password, query, toDate, username]);

  const loadSummary = useCallback(async () => {
    if (!username || !password || !fromDate || !toDate) return;
    setSummaryError(null);
    const params = new URLSearchParams({ from: fromDate, to: toDate });
    const response = await fetch(`${API_BASE}/v1/admin/finance/expenses/summary?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FinanceExpenseSummaryResponse;
      setSummary(data);
    } else {
      setSummaryError("Unable to load expense summary.");
    }
  }, [authHeaders, fromDate, password, toDate, username]);

  const saveCredentials = useCallback(() => {
    localStorage.setItem(STORAGE_USERNAME_KEY, username);
    localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Saved admin credentials.");
  }, [password, username]);

  const clearCredentials = useCallback(() => {
    localStorage.removeItem(STORAGE_USERNAME_KEY);
    localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setProfile(null);
    setFeatureConfig(null);
    setUiPrefs(null);
    setStatusMessage("Cleared admin credentials.");
  }, []);

  const resetExpenseDraft = useCallback(() => {
    setDraft({
      occurred_on: formatDateInput(new Date()),
      category_id: "",
      vendor: "",
      description: "",
      amount: "",
      tax: "0.00",
      receipt_url: "",
      payment_method: "",
    });
    setDraftErrors([]);
  }, []);

  const openCreateModal = useCallback(() => {
    setEditingExpense(null);
    resetExpenseDraft();
    setModalOpen(true);
  }, [resetExpenseDraft]);

  const openEditModal = useCallback((expense: FinanceExpense) => {
    setEditingExpense(expense);
    setDraft({
      occurred_on: expense.occurred_on,
      category_id: expense.category_id,
      vendor: expense.vendor ?? "",
      description: expense.description,
      amount: formatCurrencyInput(expense.amount_cents),
      tax: formatCurrencyInput(expense.tax_cents),
      receipt_url: expense.receipt_url ?? "",
      payment_method: expense.payment_method ?? "",
    });
    setDraftErrors([]);
    setModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setModalOpen(false);
    setEditingExpense(null);
  }, []);

  const submitExpense = useCallback(async () => {
    if (!canManageFinance) return;
    const errors: string[] = [];
    const amountCents = parseCurrencyInput(draft.amount);
    const taxCents = parseCurrencyInput(draft.tax || "0");

    if (!draft.occurred_on) errors.push("Date is required.");
    if (!draft.category_id) errors.push("Category is required.");
    if (!draft.description.trim()) errors.push("Description is required.");
    if (amountCents === null) errors.push("Amount must be a number.");
    if (taxCents === null) errors.push("Tax must be a number.");

    if (errors.length) {
      setDraftErrors(errors);
      return;
    }

    const payload = {
      occurred_on: draft.occurred_on,
      category_id: draft.category_id,
      vendor: draft.vendor.trim() || null,
      description: draft.description.trim(),
      amount_cents: amountCents ?? 0,
      tax_cents: taxCents ?? 0,
      receipt_url: draft.receipt_url.trim() || null,
      payment_method: draft.payment_method.trim() || null,
    };

    const endpoint = editingExpense
      ? `${API_BASE}/v1/admin/finance/expenses/${editingExpense.expense_id}`
      : `${API_BASE}/v1/admin/finance/expenses`;
    const method = editingExpense ? "PATCH" : "POST";

    const response = await fetch(endpoint, {
      method,
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (response.ok) {
      setStatusMessage(editingExpense ? "Expense updated." : "Expense created.");
      closeModal();
      void loadExpenses();
      void loadSummary();
    } else {
      setDraftErrors(["Unable to save expense."]);
    }
  }, [authHeaders, canManageFinance, closeModal, draft, editingExpense, loadExpenses, loadSummary]);

  const deleteExpense = useCallback(
    async (expense: FinanceExpense) => {
      if (!canManageFinance) return;
      const response = await fetch(`${API_BASE}/v1/admin/finance/expenses/${expense.expense_id}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (response.ok) {
        setStatusMessage("Expense deleted.");
        void loadExpenses();
        void loadSummary();
      } else {
        setStatusMessage("Unable to delete expense.");
      }
    },
    [authHeaders, canManageFinance, loadExpenses, loadSummary]
  );

  const openCategoryModal = useCallback((category?: FinanceCategory) => {
    if (category) {
      setEditingCategory(category);
      setCategoryDraft({
        name: category.name,
        default: category.default,
        sort_order: String(category.sort_order),
      });
    } else {
      setEditingCategory(null);
      setCategoryDraft({ name: "", default: false, sort_order: "0" });
    }
    setCategoryErrors([]);
    setCategoryModalOpen(true);
  }, []);

  const closeCategoryModal = useCallback(() => {
    setCategoryModalOpen(false);
    setEditingCategory(null);
  }, []);

  const submitCategory = useCallback(async () => {
    if (!canManageFinance) return;
    const errors: string[] = [];
    if (!categoryDraft.name.trim()) {
      errors.push("Name is required.");
    }
    const sortOrder = Number(categoryDraft.sort_order);
    if (!Number.isFinite(sortOrder) || sortOrder < 0) {
      errors.push("Sort order must be a non-negative number.");
    }
    if (errors.length) {
      setCategoryErrors(errors);
      return;
    }

    const payload = {
      name: categoryDraft.name.trim(),
      default: categoryDraft.default,
      sort_order: sortOrder,
    };

    const endpoint = editingCategory
      ? `${API_BASE}/v1/admin/finance/expense-categories/${editingCategory.category_id}`
      : `${API_BASE}/v1/admin/finance/expense-categories`;
    const method = editingCategory ? "PATCH" : "POST";

    const response = await fetch(endpoint, {
      method,
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (response.ok) {
      setStatusMessage(editingCategory ? "Category updated." : "Category created.");
      closeCategoryModal();
      void loadCategories();
    } else {
      setCategoryErrors(["Unable to save category."]);
    }
  }, [authHeaders, canManageFinance, categoryDraft, closeCategoryModal, editingCategory, loadCategories]);

  const deleteCategory = useCallback(
    async (category: FinanceCategory) => {
      if (!canManageFinance) return;
      const response = await fetch(
        `${API_BASE}/v1/admin/finance/expense-categories/${category.category_id}`,
        {
          method: "DELETE",
          headers: authHeaders,
        }
      );
      if (response.ok) {
        setStatusMessage("Category deleted.");
        void loadCategories();
        if (categoryFilter === category.category_id) {
          setCategoryFilter("");
        }
      } else {
        setStatusMessage("Unable to delete category.");
      }
    },
    [authHeaders, canManageFinance, categoryFilter, loadCategories]
  );

  useEffect(() => {
    const savedUsername = localStorage.getItem(STORAGE_USERNAME_KEY);
    const savedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (savedUsername) setUsername(savedUsername);
    if (savedPassword) setPassword(savedPassword);
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadCategories();
  }, [loadCategories, loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    setPage(1);
  }, [categoryFilter, query, fromDate, toDate]);

  useEffect(() => {
    if (username && password) {
      void loadExpenses();
      void loadSummary();
    }
  }, [loadExpenses, loadSummary, password, username]);

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <div className="card">
          <div className="card-body">Finance module is disabled for your account.</div>
        </div>
      </div>
    );
  }

  if (!canViewFinance) {
    return (
      <div className="admin-page">
        <div className="card">
          <div className="card-body">You do not have permission to view finance.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="finance-expenses" />

      <section className="admin-card admin-section">
        <div className="section-heading" style={{ alignItems: "flex-start" }}>
          <div>
            <h1>Expense tracking</h1>
            <p className="muted">Capture expenses, receipts, and vendor details for reporting.</p>
          </div>
          <div className="admin-actions">
            <a className="btn btn-ghost" href="/admin/finance/budgets">
              Budgets
            </a>
            {canManageFinance ? (
              <button className="btn btn-primary" type="button" onClick={openCreateModal}>
                New expense
              </button>
            ) : null}
          </div>
        </div>
        <div className="admin-actions" style={{ flexWrap: "wrap" }}>
          <label style={{ minWidth: 200 }}>
            <span className="label">Username</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label style={{ minWidth: 200 }}>
            <span className="label">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <div className="admin-actions">
            <button className="btn btn-primary" type="button" onClick={saveCredentials}>
              Save
            </button>
            <button className="btn btn-ghost" type="button" onClick={clearCredentials}>
              Clear
            </button>
          </div>
        </div>
        {statusMessage ? <p className="alert">{statusMessage}</p> : null}
        {errorMessage ? <p className="alert alert-error">{errorMessage}</p> : null}
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading" style={{ alignItems: "flex-start" }}>
          <div>
            <h2>Expense summary</h2>
            <p className="muted">Totals by category with budget utilization.</p>
          </div>
          <div className="admin-actions" style={{ flexWrap: "wrap" }}>
            <label>
              <span className="label">From</span>
              <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
            </label>
            <label>
              <span className="label">To</span>
              <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
            </label>
            <button className="btn btn-ghost" type="button" onClick={loadSummary}>
              Refresh summary
            </button>
          </div>
        </div>
        {summaryError ? <p className="alert alert-error">{summaryError}</p> : null}
        {summary ? (
          summary.categories.length ? (
            <div style={{ display: "grid", gap: "16px" }}>
              <div
                style={{
                  display: "grid",
                  gap: "12px",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                }}
              >
                <div className="card">
                  <div className="card-body">
                    <p className="muted">Total spend</p>
                    <h3>{formatCurrency(summary.total_cents)}</h3>
                  </div>
                </div>
                <div className="card">
                  <div className="card-body">
                    <p className="muted">Total tax</p>
                    <h3>{formatCurrency(summary.total_tax_cents)}</h3>
                  </div>
                </div>
                <div className="card">
                  <div className="card-body">
                    <p className="muted">Budget coverage</p>
                    <h3>{formatPercent(summary.percent_of_budget)}</h3>
                  </div>
                </div>
              </div>
              <div className="table-responsive">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Category</th>
                      <th>Spend</th>
                      <th>Tax</th>
                      <th>Budget</th>
                      <th>% Budget</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.categories.map((entry) => (
                      <tr key={entry.category_id}>
                        <td>{entry.category_name}</td>
                        <td>{formatCurrency(entry.total_cents)}</td>
                        <td>{formatCurrency(entry.tax_cents)}</td>
                        <td>{formatCurrency(entry.budget_cents)}</td>
                        <td>{formatPercent(entry.percent_of_budget)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="card-body">No expenses recorded for this range.</div>
          )
        ) : (
          <div className="card-body">Select a date range to view summary.</div>
        )}
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading" style={{ alignItems: "flex-start" }}>
          <div>
            <h2>Expenses</h2>
            <p className="muted">Search, filter, and manage expense entries.</p>
          </div>
          <div className="admin-actions" style={{ flexWrap: "wrap" }}>
            <label>
              <span className="label">Search</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} />
            </label>
            <label>
              <span className="label">Category</span>
              <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
                <option value="">All categories</option>
                {categories.map((category) => (
                  <option key={category.category_id} value={category.category_id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
        {isLoading ? <p className="muted">Loading expenses…</p> : null}
        {!isLoading && expenses.length === 0 ? (
          <div className="card-body">No expenses found for the selected filters.</div>
        ) : (
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Category</th>
                  <th>Description</th>
                  <th>Vendor</th>
                  <th>Amount</th>
                  <th>Tax</th>
                  <th>Receipt</th>
                  <th>Payment</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {expenses.map((expense) => (
                  <tr key={expense.expense_id}>
                    <td>{expense.occurred_on}</td>
                    <td>{expense.category_name ?? "—"}</td>
                    <td>{expense.description}</td>
                    <td>{expense.vendor ?? "—"}</td>
                    <td>{formatCurrency(expense.amount_cents)}</td>
                    <td>{formatCurrency(expense.tax_cents)}</td>
                    <td>
                      {expense.receipt_url ? (
                        <a className="link" href={expense.receipt_url} target="_blank" rel="noreferrer">
                          View
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{expense.payment_method ?? "—"}</td>
                    <td>
                      <div className="admin-actions">
                        {canManageFinance ? (
                          <>
                            <button
                              className="btn btn-ghost"
                              type="button"
                              onClick={() => openEditModal(expense)}
                            >
                              Edit
                            </button>
                            <button
                              className="btn btn-ghost"
                              type="button"
                              onClick={() => deleteExpense(expense)}
                            >
                              Delete
                            </button>
                          </>
                        ) : (
                          <span className="muted">Read only</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="admin-actions" style={{ justifyContent: "space-between" }}>
          <p className="muted">{total} expenses</p>
          <div className="admin-actions">
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page <= 1}
            >
              Previous
            </button>
            <span className="muted">
              Page {page} of {totalPages}
            </span>
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              disabled={page >= totalPages}
            >
              Next
            </button>
          </div>
        </div>
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading" style={{ alignItems: "flex-start" }}>
          <div>
            <h2>Expense categories</h2>
            <p className="muted">Organize expenses for reporting and budgets.</p>
          </div>
          {canManageFinance ? (
            <button className="btn btn-ghost" type="button" onClick={() => openCategoryModal()}>
              Add category
            </button>
          ) : null}
        </div>
        {categories.length === 0 ? (
          <div className="card-body">No categories yet. Add one to start tracking expenses.</div>
        ) : (
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Default</th>
                  <th>Sort order</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {categories.map((category) => (
                  <tr key={category.category_id}>
                    <td>{category.name}</td>
                    <td>{category.default ? "Yes" : "No"}</td>
                    <td>{category.sort_order}</td>
                    <td>
                      <div className="admin-actions">
                        {canManageFinance ? (
                          <>
                            <button
                              className="btn btn-ghost"
                              type="button"
                              onClick={() => openCategoryModal(category)}
                            >
                              Edit
                            </button>
                            <button
                              className="btn btn-ghost"
                              type="button"
                              onClick={() => deleteCategory(category)}
                            >
                              Delete
                            </button>
                          </>
                        ) : (
                          <span className="muted">Read only</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {modalOpen ? (
        <div className="schedule-modal" role="dialog" aria-modal="true">
          <div className="schedule-modal-backdrop" onClick={closeModal} />
          <div className="schedule-modal-panel" style={{ maxWidth: "640px" }}>
            <header className="schedule-modal-header">
              <div>
                <h3>{editingExpense ? "Edit expense" : "New expense"}</h3>
                <p className="muted">Track receipts and allocate to categories.</p>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeModal}>
                Close
              </button>
            </header>
            <div className="schedule-modal-body" style={{ display: "grid", gap: "16px" }}>
              {draftErrors.length ? (
                <div className="alert alert-error">
                  <ul>
                    {draftErrors.map((error) => (
                      <li key={error}>{error}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div className="schedule-modal-grid">
                <div className="schedule-modal-section">
                  <label>
                    <span className="label">Date</span>
                    <input
                      type="date"
                      value={draft.occurred_on}
                      onChange={(event) => setDraft((prev) => ({ ...prev, occurred_on: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span className="label">Category</span>
                    <select
                      value={draft.category_id}
                      onChange={(event) => setDraft((prev) => ({ ...prev, category_id: event.target.value }))}
                    >
                      <option value="">Select category</option>
                      {categories.map((category) => (
                        <option key={category.category_id} value={category.category_id}>
                          {category.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span className="label">Vendor</span>
                    <input
                      value={draft.vendor}
                      onChange={(event) => setDraft((prev) => ({ ...prev, vendor: event.target.value }))}
                      placeholder="Optional"
                    />
                  </label>
                  <label>
                    <span className="label">Description</span>
                    <textarea
                      value={draft.description}
                      onChange={(event) => setDraft((prev) => ({ ...prev, description: event.target.value }))}
                      rows={3}
                    />
                  </label>
                </div>
                <div className="schedule-modal-section">
                  <label>
                    <span className="label">Amount (CAD)</span>
                    <input
                      value={draft.amount}
                      onChange={(event) => setDraft((prev) => ({ ...prev, amount: event.target.value }))}
                      placeholder="0.00"
                    />
                  </label>
                  <label>
                    <span className="label">Tax (CAD)</span>
                    <input
                      value={draft.tax}
                      onChange={(event) => setDraft((prev) => ({ ...prev, tax: event.target.value }))}
                      placeholder="0.00"
                    />
                  </label>
                  <label>
                    <span className="label">Receipt URL</span>
                    <input
                      value={draft.receipt_url}
                      onChange={(event) => setDraft((prev) => ({ ...prev, receipt_url: event.target.value }))}
                      placeholder="https://..."
                    />
                  </label>
                  <label>
                    <span className="label">Payment method</span>
                    <input
                      value={draft.payment_method}
                      onChange={(event) => setDraft((prev) => ({ ...prev, payment_method: event.target.value }))}
                      placeholder="Card, cash, transfer"
                    />
                  </label>
                </div>
              </div>
            </div>
            <footer className="schedule-modal-footer">
              <button className="btn btn-ghost" type="button" onClick={closeModal}>
                Cancel
              </button>
              <button className="btn btn-primary" type="button" onClick={submitExpense}>
                {editingExpense ? "Save changes" : "Create expense"}
              </button>
            </footer>
          </div>
        </div>
      ) : null}

      {categoryModalOpen ? (
        <div className="schedule-modal" role="dialog" aria-modal="true">
          <div className="schedule-modal-backdrop" onClick={closeCategoryModal} />
          <div className="schedule-modal-panel" style={{ maxWidth: "520px" }}>
            <header className="schedule-modal-header">
              <div>
                <h3>{editingCategory ? "Edit category" : "New category"}</h3>
                <p className="muted">Use categories to organize expenses and budgets.</p>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeCategoryModal}>
                Close
              </button>
            </header>
            <div className="schedule-modal-body" style={{ display: "grid", gap: "16px" }}>
              {categoryErrors.length ? (
                <div className="alert alert-error">
                  <ul>
                    {categoryErrors.map((error) => (
                      <li key={error}>{error}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <label>
                <span className="label">Name</span>
                <input
                  value={categoryDraft.name}
                  onChange={(event) =>
                    setCategoryDraft((prev) => ({ ...prev, name: event.target.value }))
                  }
                />
              </label>
              <label>
                <span className="label">Sort order</span>
                <input
                  value={categoryDraft.sort_order}
                  onChange={(event) =>
                    setCategoryDraft((prev) => ({ ...prev, sort_order: event.target.value }))
                  }
                />
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={categoryDraft.default}
                  onChange={(event) =>
                    setCategoryDraft((prev) => ({ ...prev, default: event.target.checked }))
                  }
                />
                <span>Default category</span>
              </label>
            </div>
            <footer className="schedule-modal-footer">
              <button className="btn btn-ghost" type="button" onClick={closeCategoryModal}>
                Cancel
              </button>
              <button className="btn btn-primary" type="button" onClick={submitCategory}>
                {editingCategory ? "Save changes" : "Create category"}
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </div>
  );
}
