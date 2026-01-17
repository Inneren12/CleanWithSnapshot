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

type FinanceBalanceSheetCash = {
  cash_cents: number | null;
  as_of_date: string | null;
  note: string | null;
};

type FinanceBalanceSheetAssets = {
  cash: FinanceBalanceSheetCash;
  accounts_receivable_cents: number;
  total_assets_cents: number | null;
};

type FinanceBalanceSheetLiabilities = {
  accounts_payable_cents: number | null;
  gst_payable_cents: number | null;
  total_liabilities_cents: number;
};

type FinanceBalanceSheetEquity = {
  simplified_equity_cents: number | null;
  formula: string;
};

type FinanceBalanceSheetDataSources = {
  cash: string;
  accounts_receivable: string;
  liabilities: string;
};

type FinanceBalanceSheetResponse = {
  as_of: string;
  assets: FinanceBalanceSheetAssets;
  liabilities: FinanceBalanceSheetLiabilities;
  equity: FinanceBalanceSheetEquity;
  data_sources: FinanceBalanceSheetDataSources;
  data_coverage_notes: string[];
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

export default function FinanceBalanceSheetPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [asOfDate, setAsOfDate] = useState(() => formatDateInput(new Date()));
  const [balanceSheet, setBalanceSheet] = useState<FinanceBalanceSheetResponse | null>(null);
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

  const loadBalanceSheet = useCallback(async () => {
    if (!username || !password) return;
    setErrorMessage(null);
    setStatusMessage(null);
    setIsLoading(true);
    const params = new URLSearchParams({ as_of: asOfDate });
    const response = await fetch(`${API_BASE}/v1/admin/finance/balance_sheet?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FinanceBalanceSheetResponse;
      setBalanceSheet(data);
    } else {
      setErrorMessage("Unable to load balance sheet data.");
    }
    setIsLoading(false);
  }, [asOfDate, authHeaders, password, username]);

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
    setBalanceSheet(null);
    setStatusMessage("Cleared admin credentials.");
  }, []);

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
    loadBalanceSheet();
  }, [canViewFinance, loadBalanceSheet, password, username]);

  if (!pageVisible) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100">
        <AdminNav links={navLinks} activeKey="finance-balance-sheet" />
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-16">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-10 text-center">
            <h1 className="text-2xl font-semibold">Finance module hidden</h1>
            <p className="mt-2 text-sm text-slate-300">
              Enable the finance module or update your visibility settings to access balance sheet reports.
            </p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <AdminNav links={navLinks} activeKey="finance-balance-sheet" />
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-10">
        <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
          <h1 className="text-2xl font-semibold">Balance sheet (simplified)</h1>
          <p className="mt-2 text-sm text-slate-300">
            Snapshot of assets, liabilities, and simplified equity as of a selected date.
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
            <label className="flex flex-col text-sm text-slate-300">
              As of
              <input
                type="date"
                className="mt-1 rounded-lg border border-white/10 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                value={asOfDate}
                onChange={(event) => setAsOfDate(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="rounded-lg border border-white/10 bg-white/10 px-4 py-2 text-sm font-semibold"
              onClick={loadBalanceSheet}
              disabled={isLoading || !canViewFinance}
            >
              {isLoading ? "Loading..." : "Refresh"}
            </button>
          </div>
          {!canViewFinance ? (
            <p className="mt-4 text-sm text-rose-300">You need finance.view to access this report.</p>
          ) : null}
        </section>

        <div className="grid gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
            <h2 className="text-lg font-semibold">Assets</h2>
            {balanceSheet ? (
              <div className="mt-4 space-y-3 text-sm text-slate-200">
                <div className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-950/60 p-4">
                  <div>
                    <p className="text-slate-400">Cash</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {balanceSheet.assets.cash.as_of_date
                        ? `Snapshot as of ${balanceSheet.assets.cash.as_of_date}`
                        : "No snapshot on or before as_of"}
                      {balanceSheet.assets.cash.note ? ` • ${balanceSheet.assets.cash.note}` : ""}
                    </p>
                  </div>
                  <p className="text-base font-semibold">
                    {balanceSheet.assets.cash.cash_cents === null
                      ? "Unknown"
                      : formatCurrency(balanceSheet.assets.cash.cash_cents)}
                  </p>
                </div>
                <div className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-950/60 p-4">
                  <p>Accounts receivable</p>
                  <p className="text-base font-semibold text-emerald-300">
                    {formatCurrency(balanceSheet.assets.accounts_receivable_cents)}
                  </p>
                </div>
                <div className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-950/60 p-4">
                  <p>Total assets</p>
                  <p className="text-base font-semibold">
                    {balanceSheet.assets.total_assets_cents === null
                      ? "Unknown"
                      : formatCurrency(balanceSheet.assets.total_assets_cents)}
                  </p>
                </div>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-400">Select a date to load assets.</p>
            )}
          </section>

          <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
            <h2 className="text-lg font-semibold">Liabilities</h2>
            {balanceSheet ? (
              <div className="mt-4 space-y-3 text-sm text-slate-200">
                <div className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-950/60 p-4">
                  <p>Accounts payable</p>
                  <p className="text-base font-semibold">
                    {balanceSheet.liabilities.accounts_payable_cents === null
                      ? "Not tracked"
                      : formatCurrency(balanceSheet.liabilities.accounts_payable_cents)}
                  </p>
                </div>
                <div className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-950/60 p-4">
                  <p>GST payable</p>
                  <p className="text-base font-semibold">
                    {balanceSheet.liabilities.gst_payable_cents === null
                      ? "Not tracked"
                      : formatCurrency(balanceSheet.liabilities.gst_payable_cents)}
                  </p>
                </div>
                <div className="flex items-center justify-between rounded-xl border border-white/10 bg-slate-950/60 p-4">
                  <p>Total liabilities</p>
                  <p className="text-base font-semibold">
                    {formatCurrency(balanceSheet.liabilities.total_liabilities_cents)}
                  </p>
                </div>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-400">Select a date to load liabilities.</p>
            )}
          </section>
        </div>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
          <h2 className="text-lg font-semibold">Equity</h2>
          {balanceSheet ? (
            <div className="mt-4 rounded-xl border border-white/10 bg-slate-950/60 p-4">
              <p className="text-sm text-slate-400">{balanceSheet.equity.formula}</p>
              <p className="mt-2 text-2xl font-semibold">
                {balanceSheet.equity.simplified_equity_cents === null
                  ? "Unknown"
                  : formatCurrency(balanceSheet.equity.simplified_equity_cents)}
              </p>
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-400">Select a date to load equity.</p>
          )}
        </section>

        {balanceSheet?.data_coverage_notes?.length ? (
          <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
            <h2 className="text-lg font-semibold">Data coverage notes</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-300">
              {balanceSheet.data_coverage_notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {balanceSheet?.data_sources ? (
          <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
            <h2 className="text-lg font-semibold">Data sources</h2>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-300">
              <li>Cash: {balanceSheet.data_sources.cash}</li>
              <li>Accounts receivable: {balanceSheet.data_sources.accounts_receivable}</li>
              <li>Liabilities: {balanceSheet.data_sources.liabilities}</li>
            </ul>
          </section>
        ) : null}
      </div>
    </main>
  );
}
