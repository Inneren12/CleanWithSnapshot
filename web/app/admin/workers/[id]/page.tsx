"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

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

type TrainingRequirementStatus = {
  key: string;
  title: string;
  required: boolean;
  completed_at: string | null;
  expires_at: string | null;
  next_due_at?: string | null;
  status: "ok" | "due" | "overdue";
};

type TrainingStatusResponse = {
  worker_id: number;
  requirements: TrainingRequirementStatus[];
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

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function toIsoFromLocalInput(value: string): string | undefined {
  if (!value) return undefined;
  // datetime-local inputs are interpreted as local time; convert to UTC ISO for storage.
  return new Date(value).toISOString();
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
  const [trainingStatus, setTrainingStatus] = useState<TrainingStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trainingLoading, setTrainingLoading] = useState(false);
  const [trainingError, setTrainingError] = useState<string | null>(null);
  const [trainingFormOpen, setTrainingFormOpen] = useState(false);
  const [trainingRequirementKey, setTrainingRequirementKey] = useState("");
  const [trainingCompletedAt, setTrainingCompletedAt] = useState("");
  const [trainingExpiresAt, setTrainingExpiresAt] = useState("");
  const [trainingScore, setTrainingScore] = useState("");
  const [trainingNote, setTrainingNote] = useState("");
  const [trainingSubmitting, setTrainingSubmitting] = useState(false);

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
  const trainingVisible = visibilityReady
    ? isVisible("module.training", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const hasTrainingViewPermission =
    permissionKeys.includes("training.view") || permissionKeys.includes("core.view");
  const hasTrainingManagePermission =
    permissionKeys.includes("training.manage") || permissionKeys.includes("admin.manage");

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

  const loadTrainingStatus = useCallback(async () => {
    if (!username || !password) return;
    if (!Number.isFinite(workerId)) return;
    setTrainingLoading(true);
    setTrainingError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/training/workers/${workerId}/status`, {
        headers: authHeaders,
      });
      if (!response.ok) {
        throw new Error(`Failed to load training status (${response.status})`);
      }
      const data = (await response.json()) as TrainingStatusResponse;
      setTrainingStatus(data);
    } catch (err) {
      console.error("Failed to load training status", err);
      setTrainingError("Unable to load training status.");
    } finally {
      setTrainingLoading(false);
    }
  }, [authHeaders, password, username, workerId]);

  const handleTrainingSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!trainingRequirementKey) return;
      if (!username || !password) return;
      setTrainingSubmitting(true);
      setTrainingError(null);
      try {
        const payload = {
          requirement_key: trainingRequirementKey,
          completed_at: toIsoFromLocalInput(trainingCompletedAt),
          expires_at: toIsoFromLocalInput(trainingExpiresAt),
          score: trainingScore ? Number(trainingScore) : undefined,
          note: trainingNote.trim() ? trainingNote.trim() : undefined,
        };
        const response = await fetch(`${API_BASE}/v1/admin/training/workers/${workerId}/records`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders,
          },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          throw new Error(`Failed to record completion (${response.status})`);
        }
        await loadTrainingStatus();
        setTrainingCompletedAt("");
        setTrainingExpiresAt("");
        setTrainingScore("");
        setTrainingNote("");
        setTrainingFormOpen(false);
      } catch (err) {
        console.error("Failed to record training completion", err);
        setTrainingError("Unable to record training completion.");
      } finally {
        setTrainingSubmitting(false);
      }
    },
    [
      authHeaders,
      loadTrainingStatus,
      password,
      trainingCompletedAt,
      trainingExpiresAt,
      trainingNote,
      trainingRequirementKey,
      trainingScore,
      username,
      workerId,
    ]
  );

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

  useEffect(() => {
    if (!username || !password) return;
    if (trainingVisible && hasTrainingViewPermission) {
      loadTrainingStatus();
    }
  }, [hasTrainingViewPermission, loadTrainingStatus, password, trainingVisible, username]);

  useEffect(() => {
    if (!trainingStatus?.requirements?.length) return;
    if (!trainingRequirementKey) {
      setTrainingRequirementKey(trainingStatus.requirements[0].key);
    }
  }, [trainingRequirementKey, trainingStatus]);

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
          <div className="card admin-card">
            <div className="card-header">
              <div>
                <strong>Training status</strong>
                <div className="muted">Required trainings, completions, and certificate status.</div>
              </div>
              {trainingVisible && hasTrainingManagePermission ? (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setTrainingFormOpen((prev) => !prev)}
                >
                  {trainingFormOpen ? "Close" : "Add completion record"}
                </button>
              ) : null}
            </div>
            <div className="card-body">
              {!trainingVisible ? (
                <div className="muted">Training module is disabled for your account.</div>
              ) : !hasTrainingViewPermission ? (
                <div className="muted">You do not have permission to view training status.</div>
              ) : (
                <>
                  {trainingError ? <div className="error">{trainingError}</div> : null}
                  {trainingFormOpen && hasTrainingManagePermission ? (
                    <form className="stack" onSubmit={handleTrainingSubmit}>
                      <label className="stack">
                        <span>Requirement</span>
                        <select
                          value={trainingRequirementKey}
                          onChange={(event) => setTrainingRequirementKey(event.target.value)}
                        >
                          {trainingStatus?.requirements?.map((requirement) => (
                            <option key={requirement.key} value={requirement.key}>
                              {requirement.title}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="stack">
                        <span>Completed at (Local time)</span>
                        <input
                          type="datetime-local"
                          value={trainingCompletedAt}
                          onChange={(event) => setTrainingCompletedAt(event.target.value)}
                        />
                      </label>
                      <label className="stack">
                        <span>Expires at (Local time)</span>
                        <input
                          type="datetime-local"
                          value={trainingExpiresAt}
                          onChange={(event) => setTrainingExpiresAt(event.target.value)}
                        />
                      </label>
                      <label className="stack">
                        <span>Score</span>
                        <input
                          type="number"
                          min="0"
                          max="100"
                          value={trainingScore}
                          onChange={(event) => setTrainingScore(event.target.value)}
                        />
                      </label>
                      <label className="stack">
                        <span>Note</span>
                        <textarea
                          rows={3}
                          value={trainingNote}
                          onChange={(event) => setTrainingNote(event.target.value)}
                        />
                      </label>
                      <button className="btn btn-primary" type="submit" disabled={trainingSubmitting}>
                        {trainingSubmitting ? "Saving..." : "Save completion"}
                      </button>
                    </form>
                  ) : null}
                  {trainingStatus?.requirements?.length ? (
                    <table className="table-like">
                      <thead>
                        <tr>
                          <th>Requirement</th>
                          <th>Status</th>
                          <th>Completed</th>
                          <th>Expires</th>
                          <th>Next due</th>
                          <th>Certificate</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trainingStatus.requirements.map((requirement) => (
                          <tr key={requirement.key}>
                            <td>
                              <div>
                                <div>{requirement.title}</div>
                                <div className="muted">
                                  {requirement.required ? "Required" : "Optional"} · {requirement.key}
                                </div>
                              </div>
                            </td>
                            <td>
                              <span className={`status-badge ${requirement.status}`}>
                                {requirement.status.toUpperCase()}
                              </span>
                            </td>
                            <td>{formatDateTime(requirement.completed_at)}</td>
                            <td>{formatDateTime(requirement.expires_at)}</td>
                            <td>{formatDate(requirement.next_due_at ?? requirement.expires_at)}</td>
                            <td>
                              {requirement.completed_at ? (
                                <button
                                  type="button"
                                  className="btn btn-ghost"
                                  onClick={(event) => event.preventDefault()}
                                >
                                  Download certificate
                                </button>
                              ) : (
                                <span className="muted">No certificate</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="muted">
                      {trainingLoading ? "Loading training status..." : "No training requirements configured."}
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
