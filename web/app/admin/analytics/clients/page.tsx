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

type ClientClvEntry = {
  client_id: string;
  name: string | null;
  email: string | null;
  total_paid_cents: number;
  payments_count: number;
  first_payment_at: string | null;
  last_payment_at: string | null;
};

type ClientClvResponse = {
  range_start: string;
  range_end: string;
  average_clv_cents: number | null;
  median_clv_cents: number | null;
  top_clients: ClientClvEntry[];
};

type ClientRetentionCohort = {
  cohort_month: string;
  customers: number;
  retention: Array<number | null>;
};

type ClientRetentionResponse = {
  cohort: string;
  months: number;
  cohorts: ClientRetentionCohort[];
};

function currencyFromCents(value: number) {
  return `$${(value / 100).toFixed(2)}`;
}

function formatPercent(value: number | null) {
  if (value === null) return "—";
  return `${(value * 100).toFixed(0)}%`;
}

function toIsoDate(value: string, endOfDay = false) {
  if (!value) return null;
  return endOfDay ? `${value}T23:59:59Z` : `${value}T00:00:00Z`;
}

function formatMonthLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short" });
}

export default function ClientAnalyticsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [clvFromDate, setClvFromDate] = useState("");
  const [clvToDate, setClvToDate] = useState("");
  const [clvTop, setClvTop] = useState(10);
  const [clv, setClv] = useState<ClientClvResponse | null>(null);
  const [clvLoading, setClvLoading] = useState(false);
  const [clvError, setClvError] = useState<string | null>(null);
  const [retentionMonths, setRetentionMonths] = useState(12);
  const [retention, setRetention] = useState<ClientRetentionResponse | null>(null);
  const [retentionLoading, setRetentionLoading] = useState(false);
  const [retentionError, setRetentionError] = useState<string | null>(null);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

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
        key: "analytics-attribution",
        label: "Attribution",
        href: "/admin/analytics/attribution",
        featureKey: "analytics.attribution_multitouch",
      },
      {
        key: "analytics-competitors",
        label: "Competitors",
        href: "/admin/analytics/competitors",
        featureKey: "analytics.competitors",
      },
      {
        key: "analytics-clients",
        label: "Client Analytics",
        href: "/admin/analytics/clients",
        featureKey: "module.analytics",
      },
      {
        key: "analytics-funnel",
        label: "Booking Funnel",
        href: "/admin/analytics/funnel",
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

  const loadClv = useCallback(async () => {
    if (!username || !password) return;
    setClvError(null);
    setClvLoading(true);
    const params = new URLSearchParams();
    const fromIso = toIsoDate(clvFromDate);
    const toIso = toIsoDate(clvToDate, true);
    if (fromIso) params.set("from", fromIso);
    if (toIso) params.set("to", toIso);
    params.set("top", String(clvTop));
    const response = await fetch(
      `${API_BASE}/v1/admin/analytics/clients/clv?${params.toString()}`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as ClientClvResponse;
      setClv(data);
    } else {
      setClvError("Failed to load client lifetime value.");
      setClv(null);
    }
    setClvLoading(false);
  }, [authHeaders, clvFromDate, clvToDate, clvTop, password, username]);

  const loadRetention = useCallback(async () => {
    if (!username || !password) return;
    setRetentionError(null);
    setRetentionLoading(true);
    const params = new URLSearchParams();
    params.set("cohort", "monthly");
    params.set("months", String(retentionMonths));
    const response = await fetch(
      `${API_BASE}/v1/admin/analytics/clients/retention?${params.toString()}`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as ClientRetentionResponse;
      setRetention(data);
    } else {
      setRetentionError("Failed to load retention cohorts.");
      setRetention(null);
    }
    setRetentionLoading(false);
  }, [authHeaders, password, retentionMonths, username]);

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
    void loadClv();
    void loadRetention();
  }, [loadClv, loadRetention, pageVisible, password, username]);

  const retentionCohorts = retention?.cohorts ?? [];
  const retentionColumns = retention?.months ?? retentionMonths;
  const clvTopClients = clv?.top_clients ?? [];

  return (
    <div className="admin-page">
      {navLinks.length > 0 ? <AdminNav links={navLinks} activeKey="analytics-clients" /> : null}
      <div className="admin-content">
        <div className="page-header">
          <div>
            <h1>Client Analytics</h1>
            <p className="muted">
              CLV and retention are based on successful payments tied to client bookings.
            </p>
          </div>
        </div>

        {!pageVisible && visibilityReady ? (
          <div className="card">You do not have access to Analytics.</div>
        ) : (
          <>
            <div className="card">
              <div className="card-header">
                <h2>Client lifetime value (CLV)</h2>
                <p className="muted">
                  Uses paid invoice or booking payments within the selected date range.
                </p>
              </div>
              <div className="filters">
                <label className="field">
                  <span>From</span>
                  <input
                    type="date"
                    value={clvFromDate}
                    onChange={(event) => setClvFromDate(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>To</span>
                  <input
                    type="date"
                    value={clvToDate}
                    onChange={(event) => setClvToDate(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Top clients</span>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={clvTop}
                    onChange={(event) => setClvTop(Number(event.target.value))}
                  />
                </label>
                <button
                  className="primary"
                  onClick={() => {
                    void loadClv();
                  }}
                  disabled={clvLoading}
                >
                  {clvLoading ? "Refreshing..." : "Refresh"}
                </button>
              </div>
              {clvError ? <div className="error-banner">{clvError}</div> : null}

              <div className="card-grid">
                <div className="card-body">
                  <div className="muted">Average CLV</div>
                  <h3>
                    {clv?.average_clv_cents === null || clv?.average_clv_cents === undefined
                      ? "—"
                      : currencyFromCents(clv.average_clv_cents)}
                  </h3>
                </div>
                <div className="card-body">
                  <div className="muted">Median CLV</div>
                  <h3>
                    {clv?.median_clv_cents === null || clv?.median_clv_cents === undefined
                      ? "—"
                      : currencyFromCents(clv.median_clv_cents)}
                  </h3>
                </div>
                <div className="card-body">
                  <div className="muted">Range</div>
                  <h3>
                    {clv?.range_start && clv?.range_end
                      ? `${new Date(clv.range_start).toLocaleDateString()} → ${new Date(
                          clv.range_end
                        ).toLocaleDateString()}`
                      : "—"}
                  </h3>
                </div>
              </div>

              {clvTopClients.length === 0 ? (
                <div className="empty-state">
                  <h3>No paid client revenue yet</h3>
                  <p>Once payments land, top clients will show here.</p>
                </div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Client</th>
                        <th>Email</th>
                        <th>Total paid</th>
                        <th>Payments</th>
                        <th>First payment</th>
                        <th>Last payment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {clvTopClients.map((entry) => (
                        <tr key={entry.client_id}>
                          <td>{entry.name ?? "Unnamed client"}</td>
                          <td>{entry.email ?? "—"}</td>
                          <td>{currencyFromCents(entry.total_paid_cents)}</td>
                          <td>{entry.payments_count}</td>
                          <td>
                            {entry.first_payment_at
                              ? new Date(entry.first_payment_at).toLocaleDateString()
                              : "—"}
                          </td>
                          <td>
                            {entry.last_payment_at
                              ? new Date(entry.last_payment_at).toLocaleDateString()
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="card">
              <div className="card-header">
                <h2>Retention cohorts</h2>
                <p className="muted">
                  Monthly cohorts based on the first paid month. Each column shows the share of the
                  cohort that paid again.
                </p>
              </div>
              <div className="filters">
                <label className="field">
                  <span>Months</span>
                  <input
                    type="number"
                    min={1}
                    max={36}
                    value={retentionMonths}
                    onChange={(event) => setRetentionMonths(Number(event.target.value))}
                  />
                </label>
                <button
                  className="primary"
                  onClick={() => {
                    void loadRetention();
                  }}
                  disabled={retentionLoading}
                >
                  {retentionLoading ? "Refreshing..." : "Refresh"}
                </button>
              </div>
              {retentionError ? <div className="error-banner">{retentionError}</div> : null}

              {retentionCohorts.length === 0 ? (
                <div className="empty-state">
                  <h3>No retention data yet</h3>
                  <p>Retention cohorts populate after paid invoices are recorded.</p>
                </div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Cohort month</th>
                        <th>Customers</th>
                        {Array.from({ length: retentionColumns }, (_, index) => (
                          <th key={`month-${index}`}>{`M${index}`}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {retentionCohorts.map((cohort) => (
                        <tr key={cohort.cohort_month}>
                          <td>{formatMonthLabel(cohort.cohort_month)}</td>
                          <td>{cohort.customers}</td>
                          {cohort.retention.map((rate, index) => (
                            <td key={`${cohort.cohort_month}-${index}`}>{formatPercent(rate)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
