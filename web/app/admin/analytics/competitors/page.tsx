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

type Competitor = {
  competitor_id: string;
  name: string;
  platform?: string | null;
  profile_url?: string | null;
  created_at: string;
};

type CompetitorMetric = {
  metric_id: string;
  competitor_id: string;
  as_of_date: string;
  rating: number | null;
  review_count: number | null;
  avg_response_hours: number | null;
  created_at: string;
};

type CompetitorBenchmarkEntry = {
  competitor_id: string;
  name: string;
  platform?: string | null;
  profile_url?: string | null;
  sample_count: number;
  avg_rating: number | null;
  max_review_count: number | null;
  avg_response_hours: number | null;
  latest_metric_date: string | null;
};

type CompetitorBenchmarkResponse = {
  range_start: string;
  range_end: string;
  items: CompetitorBenchmarkEntry[];
};

function defaultFromDate() {
  const date = new Date();
  date.setDate(date.getDate() - 30);
  return date.toISOString().slice(0, 10);
}

function todayDate() {
  return new Date().toISOString().slice(0, 10);
}

function parseNumber(value: string) {
  if (!value) return null;
  const parsed = Number.parseFloat(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function parseInteger(value: string) {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? null : parsed;
}

export default function CompetitorBenchmarkingPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [selectedCompetitorId, setSelectedCompetitorId] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<CompetitorMetric[]>([]);
  const [benchmark, setBenchmark] = useState<CompetitorBenchmarkResponse | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const [newCompetitorName, setNewCompetitorName] = useState("");
  const [newCompetitorPlatform, setNewCompetitorPlatform] = useState("");
  const [newCompetitorUrl, setNewCompetitorUrl] = useState("");

  const [metricDate, setMetricDate] = useState(todayDate());
  const [metricRating, setMetricRating] = useState("");
  const [metricReviewCount, setMetricReviewCount] = useState("");
  const [metricResponseHours, setMetricResponseHours] = useState("");

  const [benchmarkFrom, setBenchmarkFrom] = useState(defaultFromDate());
  const [benchmarkTo, setBenchmarkTo] = useState(todayDate());

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
    ? isVisible("analytics.competitors", permissionKeys, featureOverrides, hiddenKeys)
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

  const loadCompetitors = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/analytics/competitors`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as Competitor[];
      setCompetitors(data);
      if (!selectedCompetitorId && data.length > 0) {
        setSelectedCompetitorId(data[0].competitor_id);
      }
    } else {
      setSettingsError("Failed to load competitors");
    }
  }, [authHeaders, password, selectedCompetitorId, username]);

  const loadMetrics = useCallback(async () => {
    if (!username || !password || !selectedCompetitorId) return;
    const response = await fetch(
      `${API_BASE}/v1/admin/analytics/competitors/${selectedCompetitorId}/metrics`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as CompetitorMetric[];
      setMetrics(data);
    } else {
      setMetrics([]);
    }
  }, [authHeaders, password, selectedCompetitorId, username]);

  const loadBenchmark = useCallback(async () => {
    if (!username || !password) return;
    const params = new URLSearchParams();
    if (benchmarkFrom) params.set("from", benchmarkFrom);
    if (benchmarkTo) params.set("to", benchmarkTo);
    const response = await fetch(
      `${API_BASE}/v1/admin/analytics/competitors/benchmark?${params.toString()}`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as CompetitorBenchmarkResponse;
      setBenchmark(data);
    } else {
      setBenchmark(null);
    }
  }, [authHeaders, benchmarkFrom, benchmarkTo, password, username]);

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
    if (!username || !password || !pageVisible) return;
    void loadCompetitors();
    void loadBenchmark();
  }, [loadBenchmark, loadCompetitors, pageVisible, password, username]);

  useEffect(() => {
    if (!pageVisible) return;
    void loadMetrics();
  }, [loadMetrics, pageVisible, selectedCompetitorId]);

  const handleAddCompetitor = async () => {
    if (!newCompetitorName.trim()) return;
    setStatusMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/analytics/competitors`, {
      method: "POST",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: newCompetitorName.trim(),
        platform: newCompetitorPlatform.trim() || null,
        profile_url: newCompetitorUrl.trim() || null,
      }),
    });
    if (response.ok) {
      setNewCompetitorName("");
      setNewCompetitorPlatform("");
      setNewCompetitorUrl("");
      setStatusMessage("Competitor added.");
      await loadCompetitors();
    } else {
      setSettingsError("Unable to add competitor");
    }
  };

  const handleDeleteCompetitor = async (competitorId: string) => {
    if (!window.confirm("Remove this competitor and all stored metrics?")) return;
    const response = await fetch(`${API_BASE}/v1/admin/analytics/competitors/${competitorId}`, {
      method: "DELETE",
      headers: authHeaders,
    });
    if (response.ok) {
      setStatusMessage("Competitor removed.");
      if (competitorId === selectedCompetitorId) {
        setSelectedCompetitorId(null);
        setMetrics([]);
      }
      await loadCompetitors();
      await loadBenchmark();
    } else {
      setSettingsError("Unable to remove competitor");
    }
  };

  const handleAddMetric = async () => {
    if (!selectedCompetitorId) return;
    const response = await fetch(
      `${API_BASE}/v1/admin/analytics/competitors/${selectedCompetitorId}/metrics`,
      {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          as_of_date: metricDate,
          rating: parseNumber(metricRating),
          review_count: parseInteger(metricReviewCount),
          avg_response_hours: parseNumber(metricResponseHours),
        }),
      }
    );
    if (response.ok) {
      setMetricRating("");
      setMetricReviewCount("");
      setMetricResponseHours("");
      setStatusMessage("Metric saved.");
      await loadMetrics();
      await loadBenchmark();
    } else {
      setSettingsError("Unable to save metric");
    }
  };

  return (
    <div className="admin-page">
      {navLinks.length > 0 ? <AdminNav links={navLinks} activeKey="analytics-competitors" /> : null}
      <div className="admin-content">
        <div className="page-header">
          <h1>Competitor benchmarking</h1>
          <p className="muted">
            Capture competitor snapshots manually and compare ratings, review volume, and response
            times.
          </p>
        </div>

        {!pageVisible ? (
          <p className="alert alert-warning">
            Competitor benchmarking is hidden for your profile. Enable analytics.competitors in
            Modules &amp; Visibility.
          </p>
        ) : null}

        {settingsError ? <p className="alert alert-error">{settingsError}</p> : null}
        {statusMessage ? <p className="alert alert-success">{statusMessage}</p> : null}

        <section className="card">
          <div className="card-body">
            <h2>Competitors</h2>
            <div className="form-grid">
              <div>
                <label htmlFor="competitor-name">Name</label>
                <input
                  id="competitor-name"
                  value={newCompetitorName}
                  onChange={(event) => setNewCompetitorName(event.target.value)}
                  placeholder="Sparkle Clean Co."
                />
              </div>
              <div>
                <label htmlFor="competitor-platform">Platform</label>
                <input
                  id="competitor-platform"
                  value={newCompetitorPlatform}
                  onChange={(event) => setNewCompetitorPlatform(event.target.value)}
                  placeholder="Google, Yelp, Thumbtack"
                />
              </div>
              <div>
                <label htmlFor="competitor-url">Profile URL</label>
                <input
                  id="competitor-url"
                  value={newCompetitorUrl}
                  onChange={(event) => setNewCompetitorUrl(event.target.value)}
                  placeholder="https://..."
                />
              </div>
              <div className="form-actions">
                <button type="button" className="btn btn-primary" onClick={handleAddCompetitor}>
                  Add competitor
                </button>
              </div>
            </div>

            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Platform</th>
                    <th>Profile</th>
                    <th>Created</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {competitors.length ? (
                    competitors.map((competitor) => (
                      <tr key={competitor.competitor_id}>
                        <td>
                          <button
                            type="button"
                            className={
                              competitor.competitor_id === selectedCompetitorId
                                ? "btn btn-primary"
                                : "btn btn-secondary"
                            }
                            onClick={() => setSelectedCompetitorId(competitor.competitor_id)}
                          >
                            {competitor.name}
                          </button>
                        </td>
                        <td>{competitor.platform || "—"}</td>
                        <td>
                          {competitor.profile_url ? (
                            <a href={competitor.profile_url} target="_blank" rel="noreferrer">
                              View profile
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>{new Date(competitor.created_at).toLocaleDateString()}</td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-secondary"
                            onClick={() => handleDeleteCompetitor(competitor.competitor_id)}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5}>No competitors yet. Add one above.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card-body">
            <h2>Metrics entry</h2>
            <p className="muted">Select a competitor and log a snapshot.</p>
            <div className="form-grid">
              <div>
                <label htmlFor="metric-competitor">Competitor</label>
                <select
                  id="metric-competitor"
                  value={selectedCompetitorId ?? ""}
                  onChange={(event) => setSelectedCompetitorId(event.target.value)}
                >
                  <option value="" disabled>
                    Select competitor
                  </option>
                  {competitors.map((competitor) => (
                    <option key={competitor.competitor_id} value={competitor.competitor_id}>
                      {competitor.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="metric-date">As of date</label>
                <input
                  id="metric-date"
                  type="date"
                  value={metricDate}
                  onChange={(event) => setMetricDate(event.target.value)}
                />
              </div>
              <div>
                <label htmlFor="metric-rating">Rating</label>
                <input
                  id="metric-rating"
                  value={metricRating}
                  onChange={(event) => setMetricRating(event.target.value)}
                  placeholder="4.8"
                />
              </div>
              <div>
                <label htmlFor="metric-reviews">Review count</label>
                <input
                  id="metric-reviews"
                  value={metricReviewCount}
                  onChange={(event) => setMetricReviewCount(event.target.value)}
                  placeholder="120"
                />
              </div>
              <div>
                <label htmlFor="metric-response">Avg response (hrs)</label>
                <input
                  id="metric-response"
                  value={metricResponseHours}
                  onChange={(event) => setMetricResponseHours(event.target.value)}
                  placeholder="2.5"
                />
              </div>
              <div className="form-actions">
                <button type="button" className="btn btn-primary" onClick={handleAddMetric}>
                  Save metrics
                </button>
              </div>
            </div>

            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Rating</th>
                    <th>Reviews</th>
                    <th>Avg response (hrs)</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.length ? (
                    metrics.map((metric) => (
                      <tr key={metric.metric_id}>
                        <td>{metric.as_of_date}</td>
                        <td>{metric.rating ?? "—"}</td>
                        <td>{metric.review_count ?? "—"}</td>
                        <td>{metric.avg_response_hours ?? "—"}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4}>No metrics recorded for this competitor.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="card">
          <div className="card-body">
            <h2>Benchmark view</h2>
            <div className="form-grid">
              <div>
                <label htmlFor="benchmark-from">From</label>
                <input
                  id="benchmark-from"
                  type="date"
                  value={benchmarkFrom}
                  onChange={(event) => setBenchmarkFrom(event.target.value)}
                />
              </div>
              <div>
                <label htmlFor="benchmark-to">To</label>
                <input
                  id="benchmark-to"
                  type="date"
                  value={benchmarkTo}
                  onChange={(event) => setBenchmarkTo(event.target.value)}
                />
              </div>
              <div className="form-actions">
                <button type="button" className="btn btn-secondary" onClick={loadBenchmark}>
                  Refresh benchmark
                </button>
              </div>
            </div>

            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Competitor</th>
                    <th>Platform</th>
                    <th>Avg rating</th>
                    <th>Max reviews</th>
                    <th>Avg response (hrs)</th>
                    <th>Samples</th>
                    <th>Latest snapshot</th>
                  </tr>
                </thead>
                <tbody>
                  {benchmark?.items?.length ? (
                    benchmark.items.map((entry) => (
                      <tr key={entry.competitor_id}>
                        <td>{entry.name}</td>
                        <td>{entry.platform || "—"}</td>
                        <td>{entry.avg_rating ?? "—"}</td>
                        <td>{entry.max_review_count ?? "—"}</td>
                        <td>{entry.avg_response_hours ?? "—"}</td>
                        <td>{entry.sample_count}</td>
                        <td>{entry.latest_metric_date ?? "—"}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={7}>No benchmark data in this range.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
