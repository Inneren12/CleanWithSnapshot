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

type GeoAreaSummary = {
  area: string;
  bookings: number;
  revenue_cents: number;
  avg_ticket_cents: number | null;
};

type GeoPointSummary = {
  lat: number;
  lng: number;
  count: number;
};

type GeoAnalyticsResponse = {
  by_area: GeoAreaSummary[];
  points?: GeoPointSummary[] | null;
};

function currencyFromCents(value: number) {
  return `$${(value / 100).toFixed(2)}`;
}

function toIsoDate(value: string) {
  if (!value) return null;
  return `${value}T00:00:00Z`;
}

export default function GeoAnalyticsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [analytics, setAnalytics] = useState<GeoAnalyticsResponse | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

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
        key: "analytics-geo",
        label: "Geo Heatmap",
        href: "/admin/analytics/geo",
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

  const loadAnalytics = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const params = new URLSearchParams();
    const fromIso = toIsoDate(fromDate);
    const toIso = toIsoDate(toDate);
    if (fromIso) params.set("from", fromIso);
    if (toIso) params.set("to", toIso);
    const response = await fetch(`${API_BASE}/v1/admin/analytics/geo?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as GeoAnalyticsResponse;
      setAnalytics(data);
      setStatusMessage(null);
    } else {
      setSettingsError("Failed to load geo analytics");
    }
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
    void loadAnalytics();
  }, [loadAnalytics, pageVisible, password, username]);

  const areaRows = analytics?.by_area ?? [];
  const maxBookings = areaRows.reduce((acc, row) => Math.max(acc, row.bookings), 0);

  return (
    <div className="admin-page">
      {navLinks.length > 0 ? <AdminNav links={navLinks} activeKey="analytics-geo" /> : null}
      <div className="admin-content">
        <div className="page-header">
          <div>
            <h1>Geo Heatmap</h1>
            <p className="muted">
              Bookings by area with lightweight heat bars. Lat/lng points appear when available.
            </p>
          </div>
        </div>

        {!pageVisible && visibilityReady ? (
          <div className="card">You do not have access to Analytics.</div>
        ) : (
          <div className="card">
            <div className="filters">
              <label className="field">
                <span>From</span>
                <input
                  type="date"
                  value={fromDate}
                  onChange={(event) => setFromDate(event.target.value)}
                />
              </label>
              <label className="field">
                <span>To</span>
                <input
                  type="date"
                  value={toDate}
                  onChange={(event) => setToDate(event.target.value)}
                />
              </label>
              <button
                className="primary"
                onClick={() => {
                  setStatusMessage("Refreshing...");
                  void loadAnalytics();
                }}
              >
                Refresh
              </button>
              {statusMessage ? <span className="muted">{statusMessage}</span> : null}
            </div>

            {settingsError ? <div className="error-banner">{settingsError}</div> : null}

            {areaRows.length === 0 ? (
              <div className="empty-state">
                <h3>No area data yet</h3>
                <p>Capture address labels or team zones to populate the geo heatmap.</p>
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Area</th>
                      <th>Bookings</th>
                      <th>Revenue</th>
                      <th>Avg Ticket</th>
                      <th>Heat</th>
                    </tr>
                  </thead>
                  <tbody>
                    {areaRows.map((row) => {
                      const intensity = maxBookings > 0 ? Math.round((row.bookings / maxBookings) * 100) : 0;
                      return (
                        <tr key={row.area}>
                          <td>{row.area}</td>
                          <td>{row.bookings}</td>
                          <td>{currencyFromCents(row.revenue_cents)}</td>
                          <td>
                            {row.avg_ticket_cents === null
                              ? "—"
                              : currencyFromCents(row.avg_ticket_cents)}
                          </td>
                          <td>
                            <div
                              style={{
                                height: "10px",
                                borderRadius: "6px",
                                background: "rgba(15, 118, 110, 0.15)",
                                overflow: "hidden",
                              }}
                            >
                              <div
                                style={{
                                  width: `${intensity}%`,
                                  height: "100%",
                                  background: "rgba(15, 118, 110, 0.6)",
                                }}
                              />
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {analytics?.points && analytics.points.length > 0 ? (
              <div className="subtle-note">
                {analytics.points.length} coordinate cluster
                {analytics.points.length === 1 ? "" : "s"} available for map overlays.
              </div>
            ) : (
              <div className="subtle-note">No coordinate points available yet.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
