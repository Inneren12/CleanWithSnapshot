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

type AttributionPathSummary = {
  path: string;
  lead_count: number;
};

type AttributionPathsResponse = {
  range_start: string;
  range_end: string;
  items: AttributionPathSummary[];
};

function formatDateInput(value: Date) {
  return value.toISOString().slice(0, 10);
}

function defaultFromDate() {
  const date = new Date();
  date.setDate(date.getDate() - 30);
  return formatDateInput(date);
}

function toIsoDate(value: string, endOfDay = false) {
  if (!value) return null;
  return endOfDay ? `${value}T23:59:59Z` : `${value}T00:00:00Z`;
}

export default function AttributionPathsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [fromDate, setFromDate] = useState(defaultFromDate);
  const [toDate, setToDate] = useState(() => formatDateInput(new Date()));
  const [limit, setLimit] = useState("10");
  const [paths, setPaths] = useState<AttributionPathsResponse | null>(null);
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
    ? isVisible("analytics.attribution_multitouch", permissionKeys, featureOverrides, hiddenKeys)
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

  const loadPaths = useCallback(async () => {
    if (!username || !password) return;
    setStatusMessage(null);
    setErrorMessage(null);
    setIsLoading(true);
    const params = new URLSearchParams();
    const fromValue = toIsoDate(fromDate);
    const toValue = toIsoDate(toDate, true);
    const parsedLimit = Number(limit);
    if (fromValue) params.set("from", fromValue);
    if (toValue) params.set("to", toValue);
    if (!Number.isNaN(parsedLimit) && parsedLimit > 0) {
      params.set("limit", String(parsedLimit));
    }
    const response = await fetch(`${API_BASE}/v1/admin/analytics/attribution/paths?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as AttributionPathsResponse;
      setPaths(data);
      setStatusMessage(`Loaded ${data.items.length} paths.`);
    } else if (response.status === 403) {
      setErrorMessage("You do not have permission to view attribution paths.");
      setPaths(null);
    } else {
      setErrorMessage("Unable to load attribution paths.");
      setPaths(null);
    }
    setIsLoading(false);
  }, [authHeaders, fromDate, limit, password, toDate, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadUiPrefs]);

  useEffect(() => {
    void loadPaths();
  }, [loadPaths]);

  return (
    <div className="page">
      <AdminNav links={navLinks} activeKey="analytics-attribution" />
      <section className="admin-card admin-section">
        <div className="section-heading">
          <h1>Attribution Paths</h1>
          <p className="muted">Top lead touchpoint paths within a date range.</p>
        </div>
        {!pageVisible ? <p className="alert alert-warning">Attribution analytics are hidden for your profile.</p> : null}
        <div className="admin-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
          <label>
            <span className="label">From</span>
            <input className="input" type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
          </label>
          <label>
            <span className="label">To</span>
            <input className="input" type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
          </label>
          <label>
            <span className="label">Limit</span>
            <input className="input" type="number" min={1} max={100} value={limit} onChange={(event) => setLimit(event.target.value)} />
          </label>
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <button className="btn btn-primary" type="button" onClick={() => void loadPaths()} disabled={isLoading}>
              {isLoading ? "Loading..." : "Refresh"}
            </button>
          </div>
        </div>
        {statusMessage ? (
          <p className="alert alert-success" style={{ marginTop: "12px" }}>
            {statusMessage}
          </p>
        ) : null}
        {errorMessage ? (
          <p className="alert alert-error" style={{ marginTop: "12px" }}>
            {errorMessage}
          </p>
        ) : null}
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading">
          <h2>Top Paths</h2>
          <p className="muted">Most common touchpoint sequences for leads in the selected range.</p>
        </div>
        {paths && paths.items.length > 0 ? (
          <div className="table-wrapper">
            <table className="table">
              <thead>
                <tr>
                  <th>Path</th>
                  <th>Leads</th>
                </tr>
              </thead>
              <tbody>
                {paths.items.map((item) => (
                  <tr key={item.path}>
                    <td>{item.path}</td>
                    <td>{item.lead_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No attribution paths found for the selected range.</p>
        )}
      </section>
    </div>
  );
}
