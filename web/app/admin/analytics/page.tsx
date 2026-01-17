"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type FinancialSummaryResponse = {
  ready: boolean;
  reason?: string | null;
  revenue_cents?: number;
  expenses_cents?: number;
  profit_cents?: number;
  margin_pp?: number;
  gst_owed_cents?: number;
};

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
  }).format(cents / 100);
}

function formatPercent(value: number) {
  return `${value.toFixed(1)}%`;
}

function formatDateInput(value: Date) {
  return value.toISOString().slice(0, 10);
}

function defaultFromDate() {
  const date = new Date();
  date.setDate(date.getDate() - 30);
  return formatDateInput(date);
}

export default function AnalyticsFinancialSummaryPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [fromDate, setFromDate] = useState(defaultFromDate);
  const [toDate, setToDate] = useState(() => formatDateInput(new Date()));
  const [summary, setSummary] = useState<FinancialSummaryResponse | null>(null);
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
    ? isVisible("module.analytics", permissionKeys, featureOverrides, hiddenKeys)
    : true;

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
      {
        key: "analytics-summary",
        label: "Financial Summary",
        href: "/admin/analytics",
        featureKey: "module.analytics",
      },
      {
        key: "analytics-funnel",
        label: "Booking Funnel",
        href: "/admin/analytics/funnel",
        featureKey: "module.analytics",
      },
      {
        key: "analytics-clients",
        label: "Client Analytics",
        href: "/admin/analytics/clients",
        featureKey: "module.analytics",
      },
      {
        key: "analytics-geo",
        label: "Geo Heatmap",
        href: "/admin/analytics/geo",
        featureKey: "module.analytics",
      },
      {
        key: "finance-pnl",
        label: "Finance",
        href: "/admin/finance/pnl",
        featureKey: "module.finance",
      },
      {
        key: "modules",
        label: "Modules & Visibility",
        href: "/admin/settings/modules",
        featureKey: "api.settings",
      },
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
    } else {
      setProfile(null);
    }
  }, [authHeaders, password, username]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    } else {
      setFeatureConfig(null);
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/ui-prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    } else {
      setUiPrefs(null);
    }
  }, [authHeaders, password, username]);

  const loadSummary = useCallback(async () => {
    if (!username || !password) return;
    setErrorMessage(null);
    setStatusMessage(null);
    setIsLoading(true);
    const params = new URLSearchParams({ from: fromDate, to: toDate });
    const response = await fetch(`${API_BASE}/v1/admin/analytics/financial_summary?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FinancialSummaryResponse;
      setSummary(data);
    } else {
      setErrorMessage("Unable to load financial summary.");
      setSummary(null);
    }
    setIsLoading(false);
  }, [authHeaders, fromDate, password, toDate, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (!username || !password) return;
    if (!pageVisible) return;
    void loadSummary();
  }, [loadSummary, pageVisible, password, username]);

  const ready = summary?.ready ?? false;

  return (
    <div className="admin-page">
      {navLinks.length > 0 ? <AdminNav links={navLinks} activeKey="analytics-summary" /> : null}
      <div className="admin-content">
        <div className="page-header">
          <div>
            <h1>Analytics · Financial Summary</h1>
            <p className="muted">Quick profitability snapshot based on payments and tracked expenses.</p>
          </div>
        </div>

        {!pageVisible ? (
          <div className="card">
            <p>You do not have access to analytics for this organization.</p>
          </div>
        ) : (
          <>
            <div className="card">
              <div className="kpi-controls">
                <div className="kpi-date-range">
                  <label>
                    From
                    <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
                  </label>
                  <label>
                    To
                    <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
                  </label>
                </div>
                <button type="button" className="btn" onClick={() => void loadSummary()}>
                  Refresh
                </button>
              </div>
              {statusMessage ? <p className="muted">{statusMessage}</p> : null}
              {errorMessage ? <p className="error">{errorMessage}</p> : null}
            </div>

            {isLoading ? <p className="muted">Loading summary…</p> : null}

            {!isLoading && summary && !ready ? (
              <div className="card">
                <p className="alert alert-warning">
                  {summary.reason ?? "Finance data not ready — enable expense tracking."}
                </p>
              </div>
            ) : null}

            {!isLoading && summary && ready ? (
              <div className="card">
                <div className="kpi-grid">
                  <div className="kpi-card">
                    <span className="kpi-label">Revenue</span>
                    <span className="kpi-value">{formatCurrency(summary.revenue_cents ?? 0)}</span>
                  </div>
                  <div className="kpi-card">
                    <span className="kpi-label">Expenses</span>
                    <span className="kpi-value">{formatCurrency(summary.expenses_cents ?? 0)}</span>
                  </div>
                  <div className="kpi-card">
                    <span className="kpi-label">Profit</span>
                    <span className="kpi-value">{formatCurrency(summary.profit_cents ?? 0)}</span>
                  </div>
                  <div className="kpi-card">
                    <span className="kpi-label">Margin</span>
                    <span className="kpi-value">
                      {summary.margin_pp !== undefined && summary.margin_pp !== null
                        ? formatPercent(summary.margin_pp)
                        : "—"}
                    </span>
                  </div>
                  {summary.gst_owed_cents !== undefined ? (
                    <div className="kpi-card">
                      <span className="kpi-label">GST owed</span>
                      <span className="kpi-value">{formatCurrency(summary.gst_owed_cents ?? 0)}</span>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
