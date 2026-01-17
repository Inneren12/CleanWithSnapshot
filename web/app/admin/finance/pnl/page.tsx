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

type FinancePnlBreakdownItem = {
  label: string;
  total_cents: number;
};

type FinancePnlExpenseCategoryBreakdown = {
  category_id: string;
  category_name: string;
  total_cents: number;
  tax_cents: number;
};

type FinancePnlDataSources = {
  revenue: string;
  expenses: string;
};

type FinancePnlResponse = {
  from: string;
  to: string;
  revenue_cents: number;
  expense_cents: number;
  net_cents: number;
  revenue_breakdown: FinancePnlBreakdownItem[];
  expense_breakdown_by_category: FinancePnlExpenseCategoryBreakdown[];
  data_sources: FinancePnlDataSources;
};

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format(cents / 100);
}

function formatDateInput(value: Date) {
  return value.toISOString().slice(0, 10);
}

function defaultFromDate() {
  const date = new Date();
  date.setDate(date.getDate() - 30);
  return formatDateInput(date);
}

export default function FinancePnlPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [fromDate, setFromDate] = useState(defaultFromDate);
  const [toDate, setToDate] = useState(() => formatDateInput(new Date()));
  const [pnl, setPnl] = useState<FinancePnlResponse | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

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

  const loadPnl = useCallback(async () => {
    if (!username || !password) return;
    setErrorMessage(null);
    setStatusMessage(null);
    setIsLoading(true);
    const params = new URLSearchParams({ from: fromDate, to: toDate });
    const response = await fetch(`${API_BASE}/v1/admin/finance/pnl?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FinancePnlResponse;
      setPnl(data);
    } else {
      setErrorMessage("Unable to load profit & loss data.");
    }
    setIsLoading(false);
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
    setPnl(null);
    setStatusMessage("Cleared admin credentials.");
  }, []);

  const exportCsv = useCallback(async () => {
    if (!username || !password) return;
    const params = new URLSearchParams({ from: fromDate, to: toDate, format: "csv" });
    const response = await fetch(`${API_BASE}/v1/admin/finance/pnl?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (!response.ok) {
      setErrorMessage("Unable to export CSV.");
      return;
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `pnl_${fromDate}_${toDate}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(url);
  }, [authHeaders, fromDate, password, toDate, username]);

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY) ?? "";
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY) ?? "";
    setUsername(storedUsername);
    setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    loadProfile();
    loadFeatureConfig();
    loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (!username || !password || !canViewFinance) return;
    loadPnl();
  }, [canViewFinance, loadPnl, password, username]);

  if (!pageVisible) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100">
        <AdminNav title="Finance" />
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-16">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-10 text-center">
            <h1 className="text-2xl font-semibold">Finance module hidden</h1>
            <p className="mt-2 text-sm text-slate-300">
              Enable the finance module or update your visibility settings to access P&L reports.
            </p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <AdminNav title="Finance" links={navLinks} />
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-10">
        <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
          <h1 className="text-2xl font-semibold">Profit &amp; Loss</h1>
          <p className="mt-2 text-sm text-slate-300">
            Review realized revenue (payments) against logged expenses for a selected period.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-5">
            <input
              type="text"
              placeholder="Admin username"
              className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <input
              type="password"
              placeholder="Admin password"
              className="rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <button
              type="button"
              className="rounded-lg border border-white/10 bg-white/10 px-3 py-2 text-sm font-semibold"
              onClick={saveCredentials}
            >
              Save creds
            </button>
            <button
              type="button"
              className="rounded-lg border border-white/10 bg-transparent px-3 py-2 text-sm font-semibold text-slate-300"
              onClick={clearCredentials}
            >
              Clear creds
            </button>
          </div>
          {statusMessage ? <p className="mt-3 text-sm text-emerald-300">{statusMessage}</p> : null}
          {errorMessage ? <p className="mt-3 text-sm text-rose-300">{errorMessage}</p> : null}
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col text-sm text-slate-300">
                From
                <input
                  type="date"
                  className="mt-1 rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                  value={fromDate}
                  onChange={(event) => setFromDate(event.target.value)}
                />
              </label>
              <label className="flex flex-col text-sm text-slate-300">
                To
                <input
                  type="date"
                  className="mt-1 rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                  value={toDate}
                  onChange={(event) => setToDate(event.target.value)}
                />
              </label>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className="rounded-lg border border-white/10 bg-white/10 px-4 py-2 text-sm font-semibold"
                onClick={loadPnl}
                disabled={isLoading || !canViewFinance}
              >
                {isLoading ? "Loading..." : "Refresh"}
              </button>
              <button
                type="button"
                className="rounded-lg border border-white/10 bg-transparent px-4 py-2 text-sm font-semibold text-slate-300"
                onClick={exportCsv}
                disabled={!pnl}
              >
                Export CSV
              </button>
            </div>
          </div>
          {!canViewFinance ? (
            <p className="mt-4 text-sm text-rose-300">You need finance.view to access this report.</p>
          ) : null}
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
          <h2 className="text-lg font-semibold">Summary</h2>
          {pnl ? (
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4">
                <p className="text-sm text-slate-400">Revenue</p>
                <p className="mt-2 text-2xl font-semibold text-emerald-300">
                  {formatCurrency(pnl.revenue_cents)}
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4">
                <p className="text-sm text-slate-400">Expenses</p>
                <p className="mt-2 text-2xl font-semibold text-rose-300">
                  {formatCurrency(pnl.expense_cents)}
                </p>
              </div>
              <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4">
                <p className="text-sm text-slate-400">Net</p>
                <p className="mt-2 text-2xl font-semibold text-slate-100">
                  {formatCurrency(pnl.net_cents)}
                </p>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-400">Select a date range to load totals.</p>
          )}
          {pnl?.data_sources ? (
            <div className="mt-4 rounded-xl border border-white/10 bg-slate-950/60 p-4 text-sm text-slate-300">
              <p className="font-semibold text-slate-200">Data sources</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>Revenue: {pnl.data_sources.revenue}</li>
                <li>Expenses: {pnl.data_sources.expenses}</li>
              </ul>
            </div>
          ) : null}
        </section>

        <div className="grid gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
            <h2 className="text-lg font-semibold">Revenue breakdown</h2>
            <div className="mt-4 overflow-hidden rounded-xl border border-white/10">
              <table className="min-w-full text-sm">
                <thead className="bg-white/5 text-slate-300">
                  <tr>
                    <th className="px-4 py-2 text-left font-semibold">Method</th>
                    <th className="px-4 py-2 text-right font-semibold">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {pnl?.revenue_breakdown?.length ? (
                    pnl.revenue_breakdown.map((item) => (
                      <tr key={item.label} className="border-t border-white/10">
                        <td className="px-4 py-2 text-slate-100">{item.label}</td>
                        <td className="px-4 py-2 text-right text-slate-100">
                          {formatCurrency(item.total_cents)}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr className="border-t border-white/10">
                      <td className="px-4 py-3 text-sm text-slate-400" colSpan={2}>
                        No revenue recorded for this period.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
            <h2 className="text-lg font-semibold">Expense breakdown</h2>
            <div className="mt-4 overflow-hidden rounded-xl border border-white/10">
              <table className="min-w-full text-sm">
                <thead className="bg-white/5 text-slate-300">
                  <tr>
                    <th className="px-4 py-2 text-left font-semibold">Category</th>
                    <th className="px-4 py-2 text-right font-semibold">Total</th>
                    <th className="px-4 py-2 text-right font-semibold">Tax</th>
                  </tr>
                </thead>
                <tbody>
                  {pnl?.expense_breakdown_by_category?.length ? (
                    pnl.expense_breakdown_by_category.map((item) => (
                      <tr key={item.category_id} className="border-t border-white/10">
                        <td className="px-4 py-2 text-slate-100">{item.category_name}</td>
                        <td className="px-4 py-2 text-right text-slate-100">
                          {formatCurrency(item.total_cents)}
                        </td>
                        <td className="px-4 py-2 text-right text-slate-100">
                          {formatCurrency(item.tax_cents)}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr className="border-t border-white/10">
                      <td className="px-4 py-3 text-sm text-slate-400" colSpan={3}>
                        No expenses recorded for this period.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
