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

type NpsSegmentsSummary = {
  total_responses: number;
  promoters: number;
  passives: number;
  detractors: number;
  nps_score: number | null;
};

type NpsDetractorItem = {
  booking_id: string;
  client_id: string | null;
  score: number;
  comment: string | null;
  created_at: string;
};

type NpsSegmentsResponse = {
  range_start: string;
  range_end: string;
  segments: NpsSegmentsSummary;
  top_detractors?: NpsDetractorItem[] | null;
};

type NpsResponseItem = {
  token: string;
  booking_id: string;
  client_id: string | null;
  score: number;
  comment: string | null;
  created_at: string;
};

type NpsResponseListResponse = {
  responses: NpsResponseItem[];
};

type NpsSegmentKey = "promoter" | "passive" | "detractor";

const formatDateInput = (value: Date) => value.toISOString().slice(0, 10);

function formatTimestamp(value?: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(1);
}

export default function NpsSegmentsPage() {
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
  const [segments, setSegments] = useState<NpsSegmentsResponse | null>(null);
  const [responses, setResponses] = useState<Record<NpsSegmentKey, NpsResponseItem[]>>({
    promoter: [],
    passive: [],
    detractor: [],
  });
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
  const qualityVisible = visibilityReady
    ? isVisible("module.quality", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const npsVisible = visibilityReady
    ? isVisible("quality.nps", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const hasViewPermission = permissionKeys.includes("quality.view");

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

  const loadNpsData = useCallback(async () => {
    if (!username || !password || !hasViewPermission || !npsVisible) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (fromDate) params.set("from", fromDate);
    if (toDate) params.set("to", toDate);
    try {
      const [segmentsResponse, promotersResponse, passivesResponse, detractorsResponse] =
        await Promise.all([
          fetch(`${API_BASE}/v1/admin/nps/segments?${params}`, { headers: authHeaders, cache: "no-store" }),
          fetch(`${API_BASE}/v1/admin/nps/responses?segment=promoter&${params}`, {
            headers: authHeaders,
            cache: "no-store",
          }),
          fetch(`${API_BASE}/v1/admin/nps/responses?segment=passive&${params}`, {
            headers: authHeaders,
            cache: "no-store",
          }),
          fetch(`${API_BASE}/v1/admin/nps/responses?segment=detractor&${params}`, {
            headers: authHeaders,
            cache: "no-store",
          }),
        ]);

      if (!segmentsResponse.ok) {
        throw new Error(`Failed to load segments (${segmentsResponse.status})`);
      }
      if (!promotersResponse.ok || !passivesResponse.ok || !detractorsResponse.ok) {
        throw new Error("Failed to load response lists");
      }

      const segmentsPayload = (await segmentsResponse.json()) as NpsSegmentsResponse;
      const promotersPayload = (await promotersResponse.json()) as NpsResponseListResponse;
      const passivesPayload = (await passivesResponse.json()) as NpsResponseListResponse;
      const detractorsPayload = (await detractorsResponse.json()) as NpsResponseListResponse;
      setSegments(segmentsPayload);
      setResponses({
        promoter: promotersPayload.responses,
        passive: passivesPayload.responses,
        detractor: detractorsPayload.responses,
      });
    } catch (err) {
      console.error("Failed to load NPS data", err);
      setError("Unable to load NPS segments.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, fromDate, hasViewPermission, npsVisible, password, toDate, username]);

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
    if (username && password && hasViewPermission && npsVisible) {
      void loadNpsData();
    }
  }, [hasViewPermission, loadNpsData, npsVisible, password, username]);

  if (!qualityVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="quality" />
        <div className="admin-card">
          <h1>NPS Segments</h1>
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
          <h1>NPS Segments</h1>
          <p className="muted">You do not have permission to view NPS analytics.</p>
        </div>
      </div>
    );
  }

  if (visibilityReady && !npsVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="quality" />
        <div className="admin-card">
          <h1>NPS Segments</h1>
          <p className="muted">The NPS dashboard is disabled for your account.</p>
        </div>
      </div>
    );
  }

  const topDetractors = segments?.top_detractors ?? [];
  const segmentData = segments?.segments;

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="quality" />
      <header className="admin-section">
        <div>
          <h1>NPS Segments</h1>
          <p className="muted">Monitor promoters, passives, and detractors across your response window.</p>
        </div>
        <div className="admin-actions">
          <Link className="btn btn-ghost" href="/admin/quality">
            Quality overview
          </Link>
          <Link className="btn btn-ghost" href="/admin/quality/reviews">
            Reviews
          </Link>
          <Link className="btn btn-ghost" href="/admin/quality/leaderboard">
            Leaderboard
          </Link>
          <Link className="btn btn-ghost" href="/admin/quality/common">
            Common issues
          </Link>
        </div>
      </header>

      <section className="admin-card">
        <h2>Credentials</h2>
        <div className="form-group">
          <label htmlFor="quality-nps-username">Username</label>
          <input
            id="quality-nps-username"
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="admin"
          />
        </div>
        <div className="form-group">
          <label htmlFor="quality-nps-password">Password</label>
          <input
            id="quality-nps-password"
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
          </div>
          <div className="admin-actions" style={{ marginLeft: "auto" }}>
            <button className="btn btn-primary" type="button" onClick={() => void loadNpsData()}>
              Refresh dashboard
            </button>
          </div>
        </div>
        {error ? <p className="alert alert-warning">{error}</p> : null}
        {loading ? <p className="muted">Loading NPS segments…</p> : null}
        {segmentData ? (
          <div className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-label">Total responses</div>
              <div className="kpi-value">{segmentData.total_responses.toLocaleString()}</div>
              <div className="muted">
                {segments ? `${segments.range_start.slice(0, 10)} → ${segments.range_end.slice(0, 10)}` : ""}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">NPS score</div>
              <div className="kpi-value">{formatScore(segmentData.nps_score)}</div>
              <div className="muted">Promoters minus detractors</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Promoters</div>
              <div className="kpi-value">{segmentData.promoters.toLocaleString()}</div>
              <div className="muted">Scores 9–10</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Passives</div>
              <div className="kpi-value">{segmentData.passives.toLocaleString()}</div>
              <div className="muted">Scores 7–8</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Detractors</div>
              <div className="kpi-value">{segmentData.detractors.toLocaleString()}</div>
              <div className="muted">Scores 0–6</div>
            </div>
          </div>
        ) : null}
      </section>

      <section className="admin-card">
        <h2>Top detractors</h2>
        <p className="muted">Lowest scores in the selected range. Prioritize calls with recent feedback.</p>
        <table className="table">
          <thead>
            <tr>
              <th>Booking</th>
              <th>Client</th>
              <th>Score</th>
              <th>Comment</th>
              <th>Submitted</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {topDetractors.length === 0 ? (
              <tr>
                <td colSpan={6} className="muted">
                  No detractor responses for this range.
                </td>
              </tr>
            ) : (
              topDetractors.map((entry) => (
                <tr key={`${entry.booking_id}-${entry.created_at}`}>
                  <td>{entry.booking_id}</td>
                  <td>{entry.client_id ?? "—"}</td>
                  <td>{entry.score}</td>
                  <td>{entry.comment ?? "—"}</td>
                  <td>{formatTimestamp(entry.created_at)}</td>
                  <td>
                    {entry.client_id ? (
                      <Link className="btn btn-ghost" href={`/admin/clients/${entry.client_id}`}>
                        Call ASAP
                      </Link>
                    ) : (
                      <span className="muted">No client</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>

      <section className="admin-card">
        <h2>Promoters</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Booking</th>
              <th>Client</th>
              <th>Score</th>
              <th>Comment</th>
              <th>Submitted</th>
            </tr>
          </thead>
          <tbody>
            {responses.promoter.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  No promoter responses yet.
                </td>
              </tr>
            ) : (
              responses.promoter.map((entry) => (
                <tr key={entry.token}>
                  <td>{entry.booking_id}</td>
                  <td>{entry.client_id ?? "—"}</td>
                  <td>{entry.score}</td>
                  <td>{entry.comment ?? "—"}</td>
                  <td>{formatTimestamp(entry.created_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>

      <section className="admin-card">
        <h2>Passives</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Booking</th>
              <th>Client</th>
              <th>Score</th>
              <th>Comment</th>
              <th>Submitted</th>
            </tr>
          </thead>
          <tbody>
            {responses.passive.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  No passive responses yet.
                </td>
              </tr>
            ) : (
              responses.passive.map((entry) => (
                <tr key={entry.token}>
                  <td>{entry.booking_id}</td>
                  <td>{entry.client_id ?? "—"}</td>
                  <td>{entry.score}</td>
                  <td>{entry.comment ?? "—"}</td>
                  <td>{formatTimestamp(entry.created_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>

      <section className="admin-card">
        <h2>Detractors</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Booking</th>
              <th>Client</th>
              <th>Score</th>
              <th>Comment</th>
              <th>Submitted</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {responses.detractor.length === 0 ? (
              <tr>
                <td colSpan={6} className="muted">
                  No detractor responses yet.
                </td>
              </tr>
            ) : (
              responses.detractor.map((entry) => (
                <tr key={entry.token}>
                  <td>{entry.booking_id}</td>
                  <td>{entry.client_id ?? "—"}</td>
                  <td>{entry.score}</td>
                  <td>{entry.comment ?? "—"}</td>
                  <td>{formatTimestamp(entry.created_at)}</td>
                  <td>
                    {entry.client_id ? (
                      <Link className="btn btn-ghost" href={`/admin/clients/${entry.client_id}`}>
                        Call ASAP
                      </Link>
                    ) : (
                      <span className="muted">No client</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
