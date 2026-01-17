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

type FinanceCategory = {
  category_id: string;
  name: string;
  default: boolean;
  sort_order: number;
};

type FinanceBudget = {
  budget_id: string;
  month_yyyymm: string;
  category_id: string;
  amount_cents: number;
  category_name?: string | null;
};

type FinanceCategoryListResponse = {
  items: FinanceCategory[];
  total: number;
  page: number;
  page_size: number;
};

type FinanceBudgetListResponse = {
  items: FinanceBudget[];
};

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format(cents / 100);
}

function formatCurrencyInput(cents: number) {
  return (cents / 100).toFixed(2);
}

function parseCurrencyInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed.length) return 0;
  const normalized = trimmed.replace(/,/g, "");
  const numeric = Number(normalized);
  if (!Number.isFinite(numeric)) return null;
  return Math.round(numeric * 100);
}

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export default function FinanceBudgetsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [categories, setCategories] = useState<FinanceCategory[]>([]);
  const [budgets, setBudgets] = useState<FinanceBudget[]>([]);
  const [month, setMonth] = useState(currentMonth);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});

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
        key: "finance-balance-sheet",
        label: "Balance sheet",
        href: "/admin/finance/balance-sheet",
        featureKey: "module.finance",
      },
      {
        key: "finance-cashflow",
        label: "Cashflow",
        href: "/admin/finance/cashflow",
        featureKey: "module.finance",
      },
      {
        key: "finance-pnl",
        label: "P&L",
        href: "/admin/finance/pnl",
        featureKey: "module.finance",
      },
      {
        key: "finance-expenses",
        label: "Expenses",
        href: "/admin/finance/expenses",
        featureKey: "module.finance",
      },
      {
        key: "finance-taxes",
        label: "Taxes",
        href: "/admin/finance/taxes",
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

  const loadBudgets = useCallback(async () => {
    if (!username || !password) return;
    setErrorMessage(null);
    const params = new URLSearchParams({ month });
    const response = await fetch(`${API_BASE}/v1/admin/finance/budgets?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FinanceBudgetListResponse;
      setBudgets(data.items);
    } else {
      setErrorMessage("Unable to load budgets.");
    }
  }, [authHeaders, month, password, username]);

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

  const budgetByCategory = useMemo(() => {
    return budgets.reduce<Record<string, FinanceBudget>>((acc, budget) => {
      acc[budget.category_id] = budget;
      return acc;
    }, {});
  }, [budgets]);

  const totalBudgetCents = useMemo(() => {
    return budgets.reduce((sum, budget) => sum + budget.amount_cents, 0);
  }, [budgets]);

  const updateEditValue = useCallback((categoryId: string, value: string) => {
    setEdits((prev) => ({ ...prev, [categoryId]: value }));
  }, []);

  const saveBudget = useCallback(
    async (categoryId: string) => {
      if (!canManageFinance) return;
      const amount = edits[categoryId] ?? "";
      const amountCents = parseCurrencyInput(amount);
      if (amountCents === null) {
        setStatusMessage("Budget amount must be a number.");
        return;
      }

      setSaving((prev) => ({ ...prev, [categoryId]: true }));
      const existing = budgetByCategory[categoryId];
      const payload = {
        month_yyyymm: month,
        category_id: categoryId,
        amount_cents: amountCents,
      };
      const endpoint = existing
        ? `${API_BASE}/v1/admin/finance/budgets/${existing.budget_id}`
        : `${API_BASE}/v1/admin/finance/budgets`;
      const method = existing ? "PATCH" : "POST";

      const response = await fetch(endpoint, {
        method,
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (response.ok) {
        setStatusMessage("Budget saved.");
        void loadBudgets();
      } else {
        setStatusMessage("Unable to save budget.");
      }
      setSaving((prev) => ({ ...prev, [categoryId]: false }));
    },
    [authHeaders, budgetByCategory, canManageFinance, edits, loadBudgets, month]
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
    if (username && password) {
      void loadBudgets();
    }
  }, [loadBudgets, password, username]);

  useEffect(() => {
    setEdits(() => {
      const next: Record<string, string> = {};
      categories.forEach((category) => {
        const existing = budgetByCategory[category.category_id];
        next[category.category_id] = existing ? formatCurrencyInput(existing.amount_cents) : "0.00";
      });
      return next;
    });
  }, [budgetByCategory, categories]);

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
      <AdminNav links={navLinks} activeKey="finance-budgets" />

      <section className="admin-card admin-section">
        <div className="section-heading" style={{ alignItems: "flex-start" }}>
          <div>
            <h1>Budgets by category</h1>
            <p className="muted">Set monthly budget targets per expense category.</p>
          </div>
          <div className="admin-actions">
            <a className="btn btn-ghost" href="/admin/finance/expenses">
              Expenses
            </a>
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
          <label>
            <span className="label">Month</span>
            <input type="month" value={month} onChange={(event) => setMonth(event.target.value)} />
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
            <h2>Monthly budgets</h2>
            <p className="muted">Update targets for {month} and keep finance on track.</p>
          </div>
          <div className="admin-actions">
            <div className="card">
              <div className="card-body">
                <p className="muted">Total budget</p>
                <h3>{formatCurrency(totalBudgetCents)}</h3>
              </div>
            </div>
          </div>
        </div>

        {categories.length === 0 ? (
          <div className="card-body">
            No expense categories yet. Create categories in the expenses page to start budgeting.
          </div>
        ) : (
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Budget (CAD)</th>
                  <th>Current</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {categories.map((category) => {
                  const existing = budgetByCategory[category.category_id];
                  const current = existing ? formatCurrency(existing.amount_cents) : "—";
                  return (
                    <tr key={category.category_id}>
                      <td>{category.name}</td>
                      <td>
                        <input
                          value={edits[category.category_id] ?? "0.00"}
                          onChange={(event) => updateEditValue(category.category_id, event.target.value)}
                          disabled={!canManageFinance}
                        />
                      </td>
                      <td>{current}</td>
                      <td>
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => saveBudget(category.category_id)}
                          disabled={!canManageFinance || saving[category.category_id]}
                        >
                          {saving[category.category_id] ? "Saving..." : "Save"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
