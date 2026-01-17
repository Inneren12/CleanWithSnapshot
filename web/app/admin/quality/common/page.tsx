"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

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

type CommonIssueWorker = {
  worker_id: number;
  worker_name: string | null;
  issue_count: number;
};

type CommonIssueTagEntry = {
  tag_key: string;
  label: string;
  issue_count: number;
  worker_count: number;
  workers: CommonIssueWorker[];
};

type CommonIssueTagsResponse = {
  from_date: string;
  to_date: string;
  as_of: string;
  tags: CommonIssueTagEntry[];
};

const formatDateInput = (value: Date) => value.toISOString().slice(0, 10);

export default function CommonIssueTagsPage() {
  const today = useMemo(() => new Date(), []);
  const defaultToDate = useMemo(() => formatDateInput(today), [today]);
  const defaultFromDate = useMemo(() => {
    const date = new Date(today);
    date.setDate(date.getDate() - 30);
    return formatDateInput(date);
  }, [today]);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [fromDate, setFromDate] = useState(defaultFromDate);
  const [toDate, setToDate] = useState(defaultToDate);
  const [data, setData] = useState<CommonIssueTagsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

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

  const loadCommonIssues = useCallback(async () => {
    if (!username || !password || !hasViewPermission) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (fromDate) params.set("from", fromDate);
    if (toDate) params.set("to", toDate);
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/quality/issues/common${params.toString() ? `?${params.toString()}` : ""}`,
        {
          headers: authHeaders,
          cache: "no-store",
        }
      );
      if (response.ok) {
        const payload = (await response.json()) as CommonIssueTagsResponse;
        setData(payload);
      } else {
        setError("Failed to load common issue tags.");
      }
    } catch (err) {
      console.error("Failed to load common issues", err);
      setError("Network error");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, fromDate, hasViewPermission, password, toDate, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (username && password) {
      void loadProfile();
      void loadFeatureConfig();
      void loadUiPrefs();
    }
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (hasViewPermission) {
      void loadCommonIssues();
    }
  }, [hasViewPermission, loadCommonIssues]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Saved credentials locally.");
    setTimeout(() => setStatusMessage(null), 2000);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadCommonIssues();
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
        <AdminNav links={navLinks} activeKey="quality" />
        <div className="admin-card">
          <h1>Common Issues</h1>
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
          <h1>Common Issues</h1>
          <p className="muted">You do not have permission to view common issue analytics.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="quality" />
      <header className="admin-section">
        <div>
          <h1>Common Issues</h1>
          <p className="muted">Top quality issue tags and the workers most impacted.</p>
        </div>
        <div className="admin-actions">
          <Link className="btn btn-ghost" href="/admin/quality/reviews">
            View reviews
          </Link>
          <Link className="btn btn-ghost" href="/admin/quality/leaderboard">
            Worker leaderboard
          </Link>
        </div>
      </header>

      <section className="admin-card">
        <h2>Credentials</h2>
        <div className="form-group">
          <label htmlFor="quality-common-username">Username</label>
          <input
            id="quality-common-username"
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="admin"
          />
        </div>
        <div className="form-group">
          <label htmlFor="quality-common-password">Password</label>
          <input
            id="quality-common-password"
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
        <h2>Filters</h2>
        <div
          className="grid"
          style={{ display: "grid", gap: "12px", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}
        >
          <div className="form-group">
            <label htmlFor="common-from">From</label>
            <input
              id="common-from"
              className="input"
              type="date"
              value={fromDate}
              onChange={(event) => setFromDate(event.target.value)}
            />
          </div>
          <div className="form-group">
            <label htmlFor="common-to">To</label>
            <input
              id="common-to"
              className="input"
              type="date"
              value={toDate}
              onChange={(event) => setToDate(event.target.value)}
            />
          </div>
        </div>
        <div className="admin-actions">
          <button className="btn" type="button" onClick={loadCommonIssues} disabled={!hasViewPermission}>
            Refresh
          </button>
        </div>
      </section>

      <section className="admin-card">
        <h2>Top tags</h2>
        <p className="muted">
          Showing tags from {data?.from_date ?? fromDate} to {data?.to_date ?? toDate}.
        </p>
        {loading && <p className="muted">Loading tag analytics...</p>}
        {error && <p className="error">{error}</p>}
        {!loading && !error && data && data.tags.length === 0 && (
          <p className="muted">No tagged issues found in this range.</p>
        )}
        {!loading && !error && data && data.tags.length > 0 && (
          <div className="grid" style={{ display: "grid", gap: "12px" }}>
            {data.tags.map((tag) => (
              <div key={tag.tag_key} className="admin-card" style={{ margin: 0 }}>
                <div className="admin-section" style={{ marginBottom: "8px" }}>
                  <div>
                    <h3 style={{ marginBottom: "4px" }}>{tag.label}</h3>
                    <p className="muted">{tag.issue_count} tagged issues</p>
                  </div>
                  <div className="pill">{tag.worker_count} workers</div>
                </div>
                {tag.workers.length === 0 ? (
                  <p className="muted">No worker assignments captured for this tag.</p>
                ) : (
                  <ul style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                    {tag.workers.map((worker) => (
                      <li
                        key={`${tag.tag_key}-${worker.worker_id}`}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          gap: "12px",
                          alignItems: "center",
                        }}
                      >
                        <div>
                          <strong>{worker.worker_name ?? `Worker #${worker.worker_id}`}</strong>
                          <div className="muted">Worker ID: {worker.worker_id}</div>
                        </div>
                        <div className="pill">{worker.issue_count} issues</div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
