"use client";

import Link from "next/link";
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

type TeamComparisonRow = {
  team_id: number;
  name: string;
  bookings_count: number;
  completed_count: number;
  cancelled_count: number;
  completion_rate: number;
  total_revenue_cents: number;
  average_booking_cents: number;
  rating_avg?: number | null;
  rating_count: number;
};

type TeamComparisonResponse = {
  range_start: string;
  range_end: string;
  teams: TeamComparisonRow[];
};

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function formatRating(ratingAvg: number | null | undefined, ratingCount: number) {
  if (!ratingAvg || ratingCount <= 0) return "No ratings yet";
  return `${ratingAvg.toFixed(1)} (${ratingCount} reviews)`;
}

function formatDateInput(date: Date) {
  return date.toISOString().slice(0, 10);
}

function toDateParam(value: string, endOfDay: boolean) {
  if (!value) return "";
  return `${value}T${endOfDay ? "23:59:59" : "00:00:00"}Z`;
}

function readableDate(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" });
}

export default function TeamsComparisonPage() {
  const today = useMemo(() => new Date(), []);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [fromDate, setFromDate] = useState(formatDateInput(new Date(today.getTime() - 30 * 86400000)));
  const [toDate, setToDate] = useState(formatDateInput(today));
  const [comparison, setComparison] = useState<TeamComparisonResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
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
    ? isVisible("module.teams", permissionKeys, featureOverrides, hiddenKeys)
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
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "api.settings" },
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
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    }
  }, [authHeaders, password, username]);

  const loadComparison = useCallback(async () => {
    if (!username || !password) return;
    setIsLoading(true);
    setErrorMessage(null);
    const params = new URLSearchParams();
    if (fromDate) {
      params.set("from", toDateParam(fromDate, false));
    }
    if (toDate) {
      params.set("to", toDateParam(toDate, true));
    }
    const response = await fetch(`${API_BASE}/v1/admin/teams/compare?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as TeamComparisonResponse;
      setComparison(data);
    } else {
      setErrorMessage("Unable to load team comparison data.");
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
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadComparison();
  }, [loadFeatureConfig, loadProfile, loadComparison, loadUiPrefs]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Saved credentials locally.");
    setTimeout(() => setStatusMessage(null), 2000);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadComparison();
  };

  const handleClearCredentials = () => {
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setStatusMessage("Cleared saved credentials.");
    setTimeout(() => setStatusMessage(null), 2000);
  };

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="teams" />
        <div className="admin-card">
          <h1>Team Comparison</h1>
          <p className="muted">You do not have access to view the Teams module.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="teams" />
      <header className="admin-section">
        <div>
          <h1>Team Comparison</h1>
          <p className="muted">Compare bookings, revenue, ratings, and completion performance by team.</p>
        </div>
        <div className="admin-actions">
          <Link className="btn btn-ghost" href="/admin/teams">
            Back to teams
          </Link>
        </div>
      </header>

      <section className="admin-card">
        <h2>Credentials</h2>
        <div className="form-group">
          <label htmlFor="compare-username">Username</label>
          <input
            id="compare-username"
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="admin"
          />
        </div>
        <div className="form-group">
          <label htmlFor="compare-password">Password</label>
          <input
            id="compare-password"
            className="input"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="••••••••"
          />
        </div>
        <div className="admin-actions">
          <button className="btn btn-primary" type="button" onClick={handleSaveCredentials}>
            Save credentials
          </button>
          <button className="btn btn-ghost" type="button" onClick={handleClearCredentials}>
            Clear saved
          </button>
          <button className="btn btn-secondary" type="button" onClick={() => void loadComparison()}>
            Refresh comparison
          </button>
        </div>
        {statusMessage ? <p className="muted">{statusMessage}</p> : null}
      </section>

      <section className="admin-card">
        <div className="kpi-controls">
          <div className="kpi-date-range">
            <label>
              <span className="label">From</span>
              <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
            </label>
            <label>
              <span className="label">To</span>
              <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
            </label>
          </div>
          <div className="admin-actions" style={{ marginLeft: "auto" }}>
            <button className="btn btn-primary" type="button" onClick={() => void loadComparison()}>
              Apply range
            </button>
          </div>
        </div>
        {comparison ? (
          <p className="muted">
            Range: {readableDate(comparison.range_start)} – {readableDate(comparison.range_end)}
          </p>
        ) : null}
        {errorMessage ? <p className="alert alert-warning">{errorMessage}</p> : null}
        {isLoading ? <p className="muted">Loading comparison data…</p> : null}
        {comparison && comparison.teams.length > 0 ? (
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Team</th>
                  <th>Bookings</th>
                  <th>Revenue</th>
                  <th>Rating</th>
                  <th>Completion %</th>
                  <th>Cancels</th>
                  <th>Avg $/Booking</th>
                </tr>
              </thead>
              <tbody>
                {comparison.teams.map((team) => (
                  <tr key={team.team_id}>
                    <td>{team.name}</td>
                    <td>{team.bookings_count.toLocaleString()}</td>
                    <td>{formatCurrency(team.total_revenue_cents)}</td>
                    <td>{formatRating(team.rating_avg, team.rating_count)}</td>
                    <td>{(team.completion_rate * 100).toFixed(1)}%</td>
                    <td>{team.cancelled_count.toLocaleString()}</td>
                    <td>{formatCurrency(team.average_booking_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {comparison && comparison.teams.length === 0 && !isLoading ? (
          <p className="muted">No teams found for this date range.</p>
        ) : null}
      </section>
    </div>
  );
}
