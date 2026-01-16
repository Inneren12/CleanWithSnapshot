"use client";

import Link from "next/link";
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

type TeamLeadSummary = {
  worker_id: number;
  name: string;
  role?: string | null;
  rating_avg?: number | null;
};

type TeamListItem = {
  team_id: number;
  name: string;
  created_at: string;
  lead?: TeamLeadSummary | null;
  worker_count: number;
  monthly_bookings: number;
  monthly_revenue_cents: number;
  rating_avg?: number | null;
  rating_count: number;
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

export default function TeamsListPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [teams, setTeams] = useState<TeamListItem[]>([]);
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
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
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

  const loadTeams = useCallback(async () => {
    if (!username || !password) return;
    setErrorMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/teams`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as TeamListItem[];
      setTeams(data);
    } else {
      setErrorMessage("Unable to load teams.");
    }
  }, [authHeaders, password, username]);

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
    void loadTeams();
  }, [loadFeatureConfig, loadProfile, loadTeams, loadUiPrefs]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Saved credentials locally.");
    setTimeout(() => setStatusMessage(null), 2000);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadTeams();
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
          <h1>Teams</h1>
          <p className="muted">You do not have access to view the Teams module.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="teams" />
      <header>
        <h1>Teams</h1>
        <p className="muted">Lead assignments, headcount, and monthly performance at a glance.</p>
      </header>

      <section className="admin-card">
        <h2>Credentials</h2>
        <div className="form-group">
          <label htmlFor="teams-username">Username</label>
          <input
            id="teams-username"
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="admin"
          />
        </div>
        <div className="form-group">
          <label htmlFor="teams-password">Password</label>
          <input
            id="teams-password"
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
          <button className="btn btn-secondary" type="button" onClick={() => void loadTeams()}>
            Refresh teams
          </button>
        </div>
        {statusMessage ? <p className="muted">{statusMessage}</p> : null}
      </section>

      {errorMessage ? (
        <div className="admin-card">
          <p className="muted">{errorMessage}</p>
        </div>
      ) : null}

      <section className="admin-grid">
        {teams.map((team) => (
          <article key={team.team_id} className="admin-card">
            <div className="admin-section">
              <div>
                <h3>{team.name}</h3>
                <p className="muted">
                  Lead: {team.lead ? `${team.lead.name}${team.lead.role ? ` • ${team.lead.role}` : ""}` : "Unassigned"}
                </p>
              </div>
              <div className="admin-section">
                <div className="muted">Workers: {team.worker_count}</div>
                <div className="muted">Monthly bookings: {team.monthly_bookings}</div>
                <div className="muted">Monthly revenue: {formatCurrency(team.monthly_revenue_cents)}</div>
                <div className="muted">Rating: {formatRating(team.rating_avg, team.rating_count)}</div>
              </div>
              <div className="admin-actions">
                <Link className="btn btn-secondary" href={`/admin/teams/${team.team_id}`}>
                  View team
                </Link>
              </div>
            </div>
          </article>
        ))}
      </section>

      {teams.length === 0 && !errorMessage ? (
        <div className="admin-card">
          <p className="muted">No teams found for this organization.</p>
        </div>
      ) : null}
    </div>
  );
}
