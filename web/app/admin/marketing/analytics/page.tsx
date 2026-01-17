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

type LeadSourceAnalyticsEntry = {
  source: string;
  leads_count: number;
  bookings_count: number;
  revenue_cents: number;
  spend_cents: number;
};

type LeadSourceAnalyticsResponse = {
  period: string;
  sources: LeadSourceAnalyticsEntry[];
};

type SpendDraft = Record<string, string>;

function currencyFromCents(value: number) {
  return `$${(value / 100).toFixed(2)}`;
}

function parseCurrencyToCents(value: string) {
  const parsed = Number.parseFloat(value);
  if (Number.isNaN(parsed)) return null;
  return Math.round(parsed * 100);
}

function defaultPeriod() {
  return new Date().toISOString().slice(0, 7);
}

export default function MarketingAnalyticsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [period, setPeriod] = useState(defaultPeriod);
  const [analytics, setAnalytics] = useState<LeadSourceAnalyticsResponse | null>(null);
  const [spendDrafts, setSpendDrafts] = useState<SpendDraft>({});
  const [newSource, setNewSource] = useState("");
  const [newSpend, setNewSpend] = useState("");
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
    ? isVisible("marketing.analytics", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const canManage = permissionKeys.includes("settings.manage");

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
        key: "marketing-analytics",
        label: "Marketing Analytics",
        href: "/admin/marketing/analytics",
        featureKey: "marketing.analytics",
      },
      {
        key: "marketing-campaigns",
        label: "Email Campaigns",
        href: "/admin/marketing/email-campaigns",
        featureKey: "marketing.email_campaigns",
      },
      {
        key: "marketing-promo-codes",
        label: "Promo Codes",
        href: "/admin/marketing/promo-codes",
        featureKey: "marketing.promo_codes",
      },
      {
        key: "pricing",
        label: "Service Types & Pricing",
        href: "/admin/settings/pricing",
        featureKey: "pricing.service_types",
      },
      {
        key: "modules",
        label: "Modules & Visibility",
        href: "/admin/settings/modules",
        featureKey: "api.settings",
      },
      {
        key: "roles",
        label: "Roles & Permissions",
        href: "/admin/iam/roles",
        featureKey: "module.teams",
        requiresPermission: "users.manage",
      },
    ];
    return candidates
      .filter((entry) => !entry.requiresPermission || permissionKeys.includes(entry.requiresPermission))
      .filter((entry) => isVisible(entry.featureKey, permissionKeys, featureOverrides, hiddenKeys))
      .map(({ featureKey, requiresPermission, ...link }) => link);
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
    const response = await fetch(`${API_BASE}/v1/admin/marketing/analytics/lead-sources?period=${period}`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as LeadSourceAnalyticsResponse;
      setAnalytics(data);
      const draft: SpendDraft = {};
      data.sources.forEach((source) => {
        draft[source.source] = (source.spend_cents / 100).toFixed(2);
      });
      setSpendDrafts(draft);
    } else {
      setSettingsError("Failed to load marketing analytics");
    }
  }, [authHeaders, password, period, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (!username || !password) return;
    void loadAnalytics();
  }, [loadAnalytics, password, period, username]);

  const handleSpendChange = (source: string, value: string) => {
    setSpendDrafts((prev) => ({ ...prev, [source]: value }));
  };

  const saveSpend = async (source: string) => {
    setStatusMessage(null);
    const cents = parseCurrencyToCents(spendDrafts[source] ?? "");
    if (cents === null) {
      setStatusMessage("Enter a valid spend amount.");
      return;
    }
    const response = await fetch(`${API_BASE}/v1/admin/marketing/spend`, {
      method: "PUT",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ source, period, amount_cents: cents }),
    });
    if (response.ok) {
      setStatusMessage(`Saved spend for ${source}.`);
      await loadAnalytics();
    } else {
      setStatusMessage(`Failed to save spend for ${source}.`);
    }
  };

  const addSpendSource = async () => {
    setStatusMessage(null);
    if (!newSource.trim()) {
      setStatusMessage("Source name is required.");
      return;
    }
    const cents = parseCurrencyToCents(newSpend);
    if (cents === null) {
      setStatusMessage("Enter a valid spend amount.");
      return;
    }
    const response = await fetch(`${API_BASE}/v1/admin/marketing/spend`, {
      method: "PUT",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ source: newSource.trim(), period, amount_cents: cents }),
    });
    if (response.ok) {
      setStatusMessage("Spend row added.");
      setNewSource("");
      setNewSpend("");
      await loadAnalytics();
    } else {
      setStatusMessage("Failed to add spend row.");
    }
  };

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="marketing-analytics" />

      <div className="admin-card">
        <h1>Marketing Analytics</h1>
        <p className="muted">Track lead source performance and manually log spend per month.</p>

        <div className="grid" style={{ marginBottom: "1rem" }}>
          <div>
            <label className="form-label">Admin username</label>
            <input
              className="form-input"
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div>
            <label className="form-label">Admin password</label>
            <input
              className="form-input"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
        </div>

        {visibilityReady && !pageVisible && (
          <p className="error">This marketing analytics view is hidden for your profile.</p>
        )}

        {!canManage && <p className="error">You need settings.manage permission to edit marketing data.</p>}

        {settingsError && <p className="error">{settingsError}</p>}
        {statusMessage && <p className="success">{statusMessage}</p>}

        <div className="grid" style={{ marginBottom: "1.5rem" }}>
          <div>
            <label className="form-label">Reporting period</label>
            <input
              className="form-input"
              type="month"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
            />
          </div>
        </div>

        <div className="table-wrapper">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Leads</th>
                <th>Bookings</th>
                <th>Revenue</th>
                <th>Spend</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {analytics?.sources.length ? (
                analytics.sources.map((row) => (
                  <tr key={row.source}>
                    <td>{row.source}</td>
                    <td>{row.leads_count}</td>
                    <td>{row.bookings_count}</td>
                    <td>{currencyFromCents(row.revenue_cents)}</td>
                    <td>
                      <input
                        className="form-input"
                        style={{ minWidth: "120px" }}
                        value={spendDrafts[row.source] ?? ""}
                        onChange={(event) => handleSpendChange(row.source, event.target.value)}
                      />
                    </td>
                    <td>
                      <button className="button" onClick={() => void saveSpend(row.source)}>
                        Save
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6}>No analytics available for this month.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card" style={{ marginTop: "1.5rem" }}>
          <h2>Add manual spend</h2>
          <div className="grid">
            <div>
              <label className="form-label">Source</label>
              <input
                className="form-input"
                value={newSource}
                onChange={(event) => setNewSource(event.target.value)}
              />
            </div>
            <div>
              <label className="form-label">Spend (USD)</label>
              <input
                className="form-input"
                value={newSpend}
                onChange={(event) => setNewSpend(event.target.value)}
              />
            </div>
          </div>
          <button className="button" onClick={() => void addSpendSource()}>
            Add spend row
          </button>
        </div>
      </div>
    </div>
  );
}
