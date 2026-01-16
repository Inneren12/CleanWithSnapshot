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

type WorkerQualityTrend = {
  previous_average_rating: number | null;
  previous_review_count: number;
  previous_complaint_count: number;
  average_rating_delta: number | null;
  review_count_delta: number;
  complaint_count_delta: number;
};

type WorkerQualityEntry = {
  worker_id: number;
  worker_name: string;
  team_id: number | null;
  team_name: string | null;
  average_rating: number | null;
  review_count: number;
  complaint_count: number;
  trend: WorkerQualityTrend | null;
};

type WorkerQualityLeaderboardResponse = {
  from_date: string;
  to_date: string;
  as_of: string;
  workers: WorkerQualityEntry[];
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatRating(rating: number | null): string {
  if (rating === null || Number.isNaN(rating)) return "—";
  return rating.toFixed(2);
}

function ratingTone(rating: number | null): string {
  if (rating === null) return "pill-muted";
  if (rating >= 4.6) return "pill-success";
  if (rating >= 4.0) return "";
  return "pill-warning";
}

function complaintTone(count: number): string {
  if (count <= 0) return "pill-success";
  if (count <= 2) return "pill-warning";
  return "pill-warning";
}

function deltaTone(delta: number | null): string {
  if (delta === null) return "pill-muted";
  if (delta > 0) return "pill-success";
  if (delta < 0) return "pill-warning";
  return "pill-muted";
}

function formatDelta(value: number | null): string {
  if (value === null) return "—";
  if (value === 0) return "0";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function formatCountDelta(value: number): string {
  if (value === 0) return "0";
  return `${value > 0 ? "+" : ""}${value}`;
}

export default function QualityLeaderboardPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [leaderboard, setLeaderboard] = useState<WorkerQualityLeaderboardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [includeTrend, setIncludeTrend] = useState(true);

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
    ? isVisible("module.quality", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const hasViewPermission = permissionKeys.includes("quality.view");

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      { key: "reviews", label: "Reviews", href: "/admin/quality/reviews", featureKey: "module.quality" },
      {
        key: "org-settings",
        label: "Org Settings",
        href: "/admin/settings/org",
        featureKey: "module.settings",
      },
      {
        key: "integrations",
        label: "Integrations",
        href: "/admin/settings/integrations",
        featureKey: "module.integrations",
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
    try {
      const response = await fetch(`${API_BASE}/v1/admin/profile`, { headers: authHeaders });
      if (response.ok) {
        const data = (await response.json()) as AdminProfile;
        setProfile(data);
      }
    } catch (err) {
      console.error("Failed to load profile", err);
    }
  }, [authHeaders, password, username]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/features/config`, { headers: authHeaders });
      if (response.ok) {
        const data = (await response.json()) as FeatureConfigResponse;
        setFeatureConfig(data);
      }
    } catch (err) {
      console.error("Failed to load feature config", err);
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/ui/prefs`, { headers: authHeaders });
      if (response.ok) {
        const data = (await response.json()) as UiPrefsResponse;
        setUiPrefs(data);
      }
    } catch (err) {
      console.error("Failed to load UI prefs", err);
    }
  }, [authHeaders, password, username]);

  const loadLeaderboard = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (fromDate) params.set("from", fromDate);
      if (toDate) params.set("to", toDate);
      if (includeTrend) params.set("include_trend", "true");
      const response = await fetch(`${API_BASE}/v1/admin/quality/workers/leaderboard?${params}`, {
        headers: authHeaders,
      });
      if (!response.ok) {
        throw new Error(`Failed to load leaderboard (${response.status})`);
      }
      const data = (await response.json()) as WorkerQualityLeaderboardResponse;
      setLeaderboard(data);
    } catch (err) {
      console.error("Failed to load leaderboard", err);
      setError("Unable to load leaderboard data.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, fromDate, includeTrend, password, toDate, username]);

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs]);

  useEffect(() => {
    void loadLeaderboard();
  }, [loadLeaderboard]);

  const handleSaveCredentials = () => {
    localStorage.setItem(STORAGE_USERNAME_KEY, username);
    localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Credentials saved.");
    setTimeout(() => setStatusMessage(null), 2000);
  };

  const handleClearCredentials = () => {
    localStorage.removeItem(STORAGE_USERNAME_KEY);
    localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setStatusMessage("Credentials cleared.");
    setTimeout(() => setStatusMessage(null), 2000);
  };

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="quality" />
        <div className="admin-card">
          <h1>Worker Quality Leaderboard</h1>
          <p className="muted">You do not have access to view the Quality module.</p>
        </div>
      </div>
    );
  }

  if (visibilityReady && !hasViewPermission) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="quality" />
        <div className="admin-card">
          <h1>Worker Quality Leaderboard</h1>
          <p className="muted">You do not have permission to view quality metrics.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="quality" />
      <header className="admin-section">
        <div>
          <h1>Worker Quality Leaderboard</h1>
          <p className="muted">Average ratings, review volume, and complaint counts per worker.</p>
        </div>
        <div className="admin-actions">
          <Link className="btn btn-ghost" href="/admin/quality/reviews">
            View reviews
          </Link>
        </div>
      </header>

      <section className="admin-card">
        <h2>Credentials</h2>
        <div className="form-group">
          <label htmlFor="quality-leaderboard-username">Username</label>
          <input
            id="quality-leaderboard-username"
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="admin"
          />
        </div>
        <div className="form-group">
          <label htmlFor="quality-leaderboard-password">Password</label>
          <input
            id="quality-leaderboard-password"
            className="input"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="••••••••"
          />
        </div>
        <div className="admin-actions">
          <button className="btn" type="button" onClick={handleSaveCredentials}>
            Save credentials
          </button>
          <button className="btn btn-ghost" type="button" onClick={handleClearCredentials}>
            Clear
          </button>
          {statusMessage ? <span className="muted">{statusMessage}</span> : null}
        </div>
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
            <label className="checkbox">
              <input
                type="checkbox"
                checked={includeTrend}
                onChange={(event) => setIncludeTrend(event.target.checked)}
              />
              Include trend vs previous period
            </label>
          </div>
          <div className="admin-actions" style={{ marginLeft: "auto" }}>
            <button className="btn btn-primary" type="button" onClick={() => void loadLeaderboard()}>
              Refresh leaderboard
            </button>
          </div>
        </div>
        {leaderboard ? (
          <p className="muted">
            Range: {formatDate(leaderboard.from_date)} – {formatDate(leaderboard.to_date)} · Updated{" "}
            {formatDate(leaderboard.as_of)}
          </p>
        ) : null}
        {error ? <p className="alert alert-warning">{error}</p> : null}
        {loading ? <p className="muted">Loading leaderboard…</p> : null}
        {leaderboard && leaderboard.workers.length > 0 ? (
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Worker</th>
                  <th>Team</th>
                  <th>Avg rating</th>
                  <th>Reviews</th>
                  <th>Complaints</th>
                  {includeTrend ? <th>Trend</th> : null}
                </tr>
              </thead>
              <tbody>
                {leaderboard.workers.map((worker) => (
                  <tr key={worker.worker_id}>
                    <td>
                      <Link href={`/admin/workers/${worker.worker_id}`}>{worker.worker_name}</Link>
                    </td>
                    <td>{worker.team_name ?? "—"}</td>
                    <td>
                      <span className={`pill ${ratingTone(worker.average_rating)}`}>
                        {formatRating(worker.average_rating)}
                      </span>
                    </td>
                    <td>{worker.review_count}</td>
                    <td>
                      <span className={`pill ${complaintTone(worker.complaint_count)}`}>
                        {worker.complaint_count}
                      </span>
                    </td>
                    {includeTrend ? (
                      <td>
                        {worker.trend ? (
                          <div className="pill-row" style={{ flexWrap: "wrap" }}>
                            <span className={`pill ${deltaTone(worker.trend.average_rating_delta)}`}>
                              Rating {formatDelta(worker.trend.average_rating_delta)}
                            </span>
                            <span className={`pill ${deltaTone(worker.trend.review_count_delta)}`}>
                              Reviews {formatCountDelta(worker.trend.review_count_delta)}
                            </span>
                            <span className={`pill ${deltaTone(-worker.trend.complaint_count_delta)}`}>
                              Complaints {formatCountDelta(worker.trend.complaint_count_delta)}
                            </span>
                          </div>
                        ) : (
                          "—"
                        )}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {leaderboard && leaderboard.workers.length === 0 && !loading ? (
          <p className="muted">No workers found for this range.</p>
        ) : null}
      </section>
    </div>
  );
}
