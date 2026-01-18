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

type FunnelLossReason = {
  reason: string;
  count: number;
};

type FunnelCounts = {
  inquiries: number;
  quotes: number;
  bookings_created: number;
  bookings_completed: number;
  reviews: number;
};

type FunnelConversionRates = {
  inquiry_to_quote: number;
  quote_to_booking: number;
  booking_to_completed: number;
  completed_to_review: number;
};

type FunnelAnalyticsResponse = {
  range_start: string;
  range_end: string;
  counts: FunnelCounts;
  conversion_rates: FunnelConversionRates;
  loss_reasons: FunnelLossReason[];
};

function formatPercent(value: number) {
  return `${(value * 100).toFixed(0)}%`;
}

function toIsoDate(value: string, endOfDay = false) {
  if (!value) return null;
  return endOfDay ? `${value}T23:59:59Z` : `${value}T00:00:00Z`;
}

export default function FunnelAnalyticsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [analytics, setAnalytics] = useState<FunnelAnalyticsResponse | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

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

  const loadAnalytics = useCallback(async () => {
    if (!username || !password) return;
    setErrorMessage(null);
    const params = new URLSearchParams();
    const fromIso = toIsoDate(fromDate);
    const toIso = toIsoDate(toDate, true);
    if (fromIso) params.set("from", fromIso);
    if (toIso) params.set("to", toIso);
    const response = await fetch(`${API_BASE}/v1/admin/analytics/funnel?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FunnelAnalyticsResponse;
      setAnalytics(data);
      setStatusMessage(null);
    } else {
      setErrorMessage("Failed to load funnel analytics");
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

  const counts = analytics?.counts;
  const lossReasons = analytics?.loss_reasons ?? [];
  const stageEntries = counts
    ? [
        { key: "inquiries", label: "Inquiries", value: counts.inquiries },
        { key: "quotes", label: "Quotes", value: counts.quotes },
        { key: "bookings_created", label: "Bookings Created", value: counts.bookings_created },
        { key: "bookings_completed", label: "Bookings Completed", value: counts.bookings_completed },
        { key: "reviews", label: "Reviews", value: counts.reviews },
      ]
    : [];
  const maxStageValue = stageEntries.reduce((max, stage) => Math.max(max, stage.value), 0);
  const conversions = analytics?.conversion_rates
    ? [
        {
          label: "Inquiry → Quote",
          value: analytics.conversion_rates.inquiry_to_quote,
        },
        {
          label: "Quote → Booking",
          value: analytics.conversion_rates.quote_to_booking,
        },
        {
          label: "Booking → Completed",
          value: analytics.conversion_rates.booking_to_completed,
        },
        {
          label: "Completed → Review",
          value: analytics.conversion_rates.completed_to_review,
        },
      ]
    : [];

  return (
    <div className="admin-page">
      {navLinks.length > 0 ? <AdminNav links={navLinks} activeKey="analytics-funnel" /> : null}
      <div className="admin-content">
        <div className="page-header">
          <div>
            <h1>Booking Funnel</h1>
            <p className="muted">
              Funnel performance based on real inquiries (leads), quotes, bookings, and reviews.
            </p>
          </div>
        </div>

        {!pageVisible ? (
          <div className="card">
            <p>You do not have access to analytics for this organization.</p>
          </div>
        ) : (
          <>
            <div className="card">
              <div className="filters">
                <label>
                  From
                  <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
                </label>
                <label>
                  To
                  <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
                </label>
                <button type="button" className="btn" onClick={() => void loadAnalytics()}>
                  Refresh
                </button>
              </div>
              {statusMessage ? <p className="muted">{statusMessage}</p> : null}
              {errorMessage ? <p className="error">{errorMessage}</p> : null}
            </div>

            <div className="card">
              <h2>Stage Counts</h2>
              {stageEntries.length === 0 ? (
                <p className="muted">No funnel activity in the selected range.</p>
              ) : (
                <div className="funnel-stages">
                  {stageEntries.map((stage) => {
                    const width = maxStageValue > 0 ? (stage.value / maxStageValue) * 100 : 0;
                    return (
                      <div key={stage.key} className="funnel-stage">
                        <div className="funnel-stage-header">
                          <span>{stage.label}</span>
                          <strong>{stage.value}</strong>
                        </div>
                        <div className="funnel-bar">
                          <div className="funnel-bar-fill" style={{ width: `${width}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="card">
              <h2>Conversion Rates</h2>
              {conversions.length === 0 ? (
                <p className="muted">No conversions to display yet.</p>
              ) : (
                <ul className="conversion-list">
                  {conversions.map((conversion) => (
                    <li key={conversion.label}>
                      <span>{conversion.label}</span>
                      <strong>{formatPercent(conversion.value)}</strong>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="card">
              <h2>Lost Reasons</h2>
              {lossReasons.length === 0 ? (
                <p className="muted">No loss reasons recorded in this range.</p>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Reason</th>
                      <th>Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lossReasons.map((reason) => (
                      <tr key={reason.reason}>
                        <td>{reason.reason}</td>
                        <td>{reason.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
