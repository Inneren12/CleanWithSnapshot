"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
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

type QualitySummaryReview = {
  feedback_id: number;
  booking_id: string;
  rating: number;
  comment: string | null;
  created_at: string;
  client_id?: string | null;
  client_name?: string | null;
};

type WorkerQualitySummaryResponse = {
  worker_id: number;
  average_rating: number | null;
  review_count: number;
  complaint_count: number;
  last_review: QualitySummaryReview | null;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatRating(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

export default function WorkerDetailPage() {
  const params = useParams();
  const workerIdParam = params?.id;
  const workerId = Number(Array.isArray(workerIdParam) ? workerIdParam[0] : workerIdParam);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [summary, setSummary] = useState<WorkerQualitySummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      {
        key: "notifications",
        label: "Notifications",
        href: "/admin/notifications",
        featureKey: "module.notifications_center",
      },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      { key: "quality", label: "Quality", href: "/admin/quality", featureKey: "module.quality" },
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
    ];
    return candidates
      .filter((entry) => isVisible(entry.featureKey, permissionKeys, featureOverrides, hiddenKeys))
      .map(({ featureKey, ...link }) => link);
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

  const loadSummary = useCallback(async () => {
    if (!username || !password) return;
    if (!Number.isFinite(workerId)) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/quality/workers/${workerId}/summary`, {
        headers: authHeaders,
      });
      if (!response.ok) {
        throw new Error(`Failed to load summary (${response.status})`);
      }
      const data = (await response.json()) as WorkerQualitySummaryResponse;
      setSummary(data);
    } catch (err) {
      console.error("Failed to load worker summary", err);
      setError("Unable to load worker quality summary.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, password, username, workerId]);

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
      loadSummary();
    }
  }, [hasViewPermission, loadSummary, password, username]);

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
      <AdminNav links={navLinks} activeKey="workers" />
      <div className="card">
        <div className="card-header">
          <div>
            <h1>Worker {Number.isFinite(workerId) ? `#${workerId}` : ""}</h1>
            <p className="muted">Quality snapshot for the selected worker.</p>
          </div>
          <Link className="btn btn-secondary" href="/admin/quality/leaderboard">
            View leaderboard
          </Link>
        </div>
        <div className="card-body">
          {error ? <div className="error">{error}</div> : null}
          {summary ? (
            <div className="card admin-card">
              <div className="card-header">
                <div>
                  <strong>Quality summary</strong>
                  <div className="muted">Recent reviews and complaints tied to this worker.</div>
                </div>
                <Link className="btn btn-ghost" href={`/admin/quality/reviews?worker_id=${workerId}`}>
                  Open quality
                </Link>
              </div>
              <div className="card-body">
                <div className="pill-row">
                  <span className="pill">Avg rating: {formatRating(summary.average_rating)}</span>
                  <span className="pill">Reviews: {summary.review_count}</span>
                  <span className="pill">Complaints: {summary.complaint_count}</span>
                </div>
                <div>
                  <div className="muted">Last review</div>
                  {summary.last_review ? (
                    <div>
                      <div>
                        {summary.last_review.rating}★ · {formatDateTime(summary.last_review.created_at)}
                      </div>
                      <div className="muted">
                        {summary.last_review.client_name ?? summary.last_review.client_id ?? "Client"}{" "}
                        {summary.last_review.comment ? `— ${summary.last_review.comment}` : ""}
                      </div>
                    </div>
                  ) : (
                    <div className="muted">No reviews yet.</div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <p className="muted">{loading ? "Loading summary..." : "No summary data yet."}</p>
          )}
        </div>
      </div>
    </div>
  );
}
