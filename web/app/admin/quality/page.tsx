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

type ServiceQualityBreakdownEntry = {
  service_label: string;
  average_rating: number | null;
  review_count: number;
  complaint_count: number;
};

type ServiceQualityBreakdownResponse = {
  from_date: string;
  to_date: string;
  as_of: string;
  services: ServiceQualityBreakdownEntry[];
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatRating(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

export default function QualityOverviewPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [breakdown, setBreakdown] = useState<ServiceQualityBreakdownResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

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
  const photoEvidenceVisible = visibilityReady
    ? isVisible("quality.photo_evidence", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      {
        key: "notifications",
        label: "Notifications",
        href: "/admin/notifications",
        featureKey: "module.notifications_center",
      },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      { key: "quality-reviews", label: "Reviews", href: "/admin/quality/reviews", featureKey: "module.quality" },
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

  const loadBreakdown = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (fromDate) params.set("from", fromDate);
      if (toDate) params.set("to", toDate);
      const response = await fetch(`${API_BASE}/v1/admin/quality/services/breakdown?${params}`, {
        headers: authHeaders,
      });
      if (!response.ok) {
        throw new Error(`Failed to load breakdown (${response.status})`);
      }
      const data = (await response.json()) as ServiceQualityBreakdownResponse;
      setBreakdown(data);
    } catch (err) {
      console.error("Failed to load breakdown", err);
      setError("Unable to load quality breakdown.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, fromDate, password, toDate, username]);

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    loadProfile();
    loadFeatureConfig();
    loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (!username || !password) return;
    if (hasViewPermission) {
      loadBreakdown();
    }
  }, [hasViewPermission, loadBreakdown, password, username]);

  const services = breakdown?.services ?? [];
  const chartServices = services.slice(0, 6);
  const maxReviews = Math.max(...chartServices.map((entry) => entry.review_count), 1);

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <div className="card">
          <div className="card-body">Quality module is disabled for your account.</div>
        </div>
      </div>
    );
  }

  if (!hasViewPermission) {
    return (
      <div className="admin-page">
        <div className="card">
          <div className="card-body">You do not have permission to view quality analytics.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="quality-overview" />
      <div className="card">
        <div className="card-header">
          <div>
            <h1>Quality Overview</h1>
            <p className="muted">Service-type quality breakdown with review trends and complaint volume.</p>
          </div>
          <div className="hero-actions">
            <Link className="btn btn-ghost" href="/admin/quality/reviews">
              Reviews timeline
            </Link>
            <Link className="btn btn-ghost" href="/admin/quality/nps">
              NPS segments
            </Link>
            <Link className="btn btn-ghost" href="/admin/quality/leaderboard">
              Worker leaderboard
            </Link>
            <Link className="btn btn-ghost" href="/admin/quality/common">
              Common issues
            </Link>
            {photoEvidenceVisible ? (
              <Link className="btn btn-ghost" href="/admin/quality/photos">
                Photo evidence
              </Link>
            ) : null}
          </div>
        </div>
        <div className="card-body">
          <div className="filter-row">
            <label className="input-label">
              From
              <input
                className="input"
                type="date"
                value={fromDate}
                onChange={(event) => setFromDate(event.target.value)}
              />
            </label>
            <label className="input-label">
              To
              <input
                className="input"
                type="date"
                value={toDate}
                onChange={(event) => setToDate(event.target.value)}
              />
            </label>
            <button className="btn btn-primary" type="button" onClick={loadBreakdown} disabled={loading}>
              {loading ? "Loading…" : "Apply range"}
            </button>
          </div>
          {error ? <div className="error">{error}</div> : null}
          {breakdown ? (
            <div className="stack">
              <div className="muted">
                Range: {formatDate(breakdown.from_date)} → {formatDate(breakdown.to_date)}
              </div>
              <div className="card admin-card revenue-chart">
                <strong>Top service review volume</strong>
                <div className="revenue-chart-bars">
                  {chartServices.map((service) => {
                    const heightPct = Math.max(6, (service.review_count / maxReviews) * 100);
                    return (
                      <div key={service.service_label} className="revenue-chart-bar">
                        <div className="revenue-bar" style={{ height: `${heightPct}%` }} />
                        <div className="revenue-bar-label">{service.service_label}</div>
                        <div className="revenue-bar-value">{service.review_count} reviews</div>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="card admin-card">
                <strong>Service quality breakdown</strong>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Service</th>
                      <th>Avg rating</th>
                      <th>Reviews</th>
                      <th>Complaints</th>
                    </tr>
                  </thead>
                  <tbody>
                    {services.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="muted">
                          No quality data for this range.
                        </td>
                      </tr>
                    ) : (
                      services.map((service) => (
                        <tr key={service.service_label}>
                          <td>{service.service_label}</td>
                          <td>{formatRating(service.average_rating)}</td>
                          <td>{service.review_count}</td>
                          <td>{service.complaint_count}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className="muted">{loading ? "Loading breakdown..." : "Choose a range to load data."}</p>
          )}
        </div>
      </div>
    </div>
  );
}
