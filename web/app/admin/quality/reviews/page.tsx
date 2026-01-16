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

type QualityReviewTemplate = {
  key: string;
  label: string;
  body: string;
};

type QualityReviewItem = {
  feedback_id: number;
  booking_id: string;
  booking_starts_at: string | null;
  worker_id: number | null;
  worker_name: string | null;
  client_id: string;
  client_name: string | null;
  client_email: string | null;
  rating: number;
  comment: string | null;
  created_at: string;
  has_issue: boolean;
};

type QualityReviewListResponse = {
  items: QualityReviewItem[];
  total: number;
  page: number;
  page_size: number;
  templates: QualityReviewTemplate[];
};

const STAR_OPTIONS = [
  { value: "", label: "All stars" },
  { value: "5", label: "5 stars" },
  { value: "4", label: "4 stars" },
  { value: "3", label: "3 stars" },
  { value: "2", label: "2 stars" },
  { value: "1", label: "1 star" },
];

const ISSUE_OPTIONS = [
  { value: "", label: "All reviews" },
  { value: "true", label: "Has issue" },
  { value: "false", label: "No issue" },
];

function formatDateTime(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function QualityReviewsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [reviews, setReviews] = useState<QualityReviewItem[]>([]);
  const [templates, setTemplates] = useState<QualityReviewTemplate[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [stars, setStars] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [workerId, setWorkerId] = useState("");
  const [clientId, setClientId] = useState("");
  const [hasIssue, setHasIssue] = useState("");

  const [activeReview, setActiveReview] = useState<QualityReviewItem | null>(null);
  const [replyTemplateKey, setReplyTemplateKey] = useState("");
  const [replyMessage, setReplyMessage] = useState("");
  const [replyStatus, setReplyStatus] = useState<string | null>(null);
  const [replyError, setReplyError] = useState<string | null>(null);
  const [replyLoading, setReplyLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

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
  const hasManagePermission = permissionKeys.includes("quality.manage");

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

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

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

  const loadReviews = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (stars) params.set("stars", stars);
    if (fromDate) params.set("from", fromDate);
    if (toDate) params.set("to", toDate);
    if (workerId) params.set("worker_id", workerId);
    if (clientId) params.set("client_id", clientId);
    if (hasIssue) params.set("has_issue", hasIssue);
    params.set("page", String(page));

    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/quality/reviews${params.toString() ? `?${params.toString()}` : ""}`,
        {
          headers: authHeaders,
          cache: "no-store",
        }
      );
      if (response.ok) {
        const data = (await response.json()) as QualityReviewListResponse;
        setReviews(data.items);
        setTotal(data.total);
        setPageSize(data.page_size);
        setTemplates(data.templates);
      } else {
        setError("Unable to load reviews.");
      }
    } catch (err) {
      console.error("Failed to load reviews", err);
      setError("Network error");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, clientId, fromDate, hasIssue, page, password, stars, toDate, username, workerId]);

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
      void loadReviews();
    }
  }, [hasViewPermission, loadReviews]);

  useEffect(() => {
    setPage(1);
  }, [stars, fromDate, toDate, workerId, clientId, hasIssue]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Saved credentials locally.");
    setTimeout(() => setStatusMessage(null), 2000);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadReviews();
  };

  const handleClearCredentials = () => {
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setStatusMessage("Cleared saved credentials.");
    setTimeout(() => setStatusMessage(null), 2000);
  };

  const openReplyModal = (review: QualityReviewItem) => {
    setActiveReview(review);
    setReplyTemplateKey("");
    setReplyMessage("");
    setReplyError(null);
    setReplyStatus(null);
  };

  const closeReplyModal = () => {
    setActiveReview(null);
    setReplyTemplateKey("");
    setReplyMessage("");
    setReplyError(null);
    setReplyStatus(null);
  };

  const handleTemplateChange = (value: string) => {
    setReplyTemplateKey(value);
    const template = templates.find((item) => item.key === value);
    if (template) {
      setReplyMessage(template.body);
    }
  };

  const submitReply = async () => {
    if (!activeReview) return;
    setReplyLoading(true);
    setReplyError(null);
    setReplyStatus(null);
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/quality/reviews/${activeReview.feedback_id}/reply`,
        {
          method: "POST",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            template_key: replyTemplateKey || null,
            message: replyMessage,
          }),
        }
      );
      if (response.ok) {
        setReplyStatus("Reply logged.");
        setReplyMessage("");
        setReplyTemplateKey("");
        void loadReviews();
      } else if (response.status === 403) {
        setReplyError("You do not have permission to reply.");
      } else {
        setReplyError("Unable to log reply.");
      }
    } catch (err) {
      console.error("Failed to reply to review", err);
      setReplyError("Network error");
    } finally {
      setReplyLoading(false);
    }
  };

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="quality" />
        <div className="admin-card">
          <h1>Reviews</h1>
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
          <h1>Reviews</h1>
          <p className="muted">You do not have permission to view reviews.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="quality" />
      <header className="admin-section">
        <div>
          <h1>Reviews</h1>
          <p className="muted">Timeline of client feedback with follow-up tools.</p>
        </div>
      </header>

      <section className="admin-card">
        <h2>Credentials</h2>
        <div className="form-group">
          <label htmlFor="quality-reviews-username">Username</label>
          <input
            id="quality-reviews-username"
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="admin"
          />
        </div>
        <div className="form-group">
          <label htmlFor="quality-reviews-password">Password</label>
          <input
            id="quality-reviews-password"
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
        <div className="grid" style={{ display: "grid", gap: "12px", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
          <div className="form-group">
            <label htmlFor="reviews-stars">Stars</label>
            <select
              id="reviews-stars"
              className="input"
              value={stars}
              onChange={(event) => setStars(event.target.value)}
            >
              {STAR_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="reviews-from">From</label>
            <input
              id="reviews-from"
              className="input"
              type="date"
              value={fromDate}
              onChange={(event) => setFromDate(event.target.value)}
            />
          </div>
          <div className="form-group">
            <label htmlFor="reviews-to">To</label>
            <input
              id="reviews-to"
              className="input"
              type="date"
              value={toDate}
              onChange={(event) => setToDate(event.target.value)}
            />
          </div>
          <div className="form-group">
            <label htmlFor="reviews-worker">Worker ID</label>
            <input
              id="reviews-worker"
              className="input"
              value={workerId}
              onChange={(event) => setWorkerId(event.target.value)}
              placeholder="e.g. 12"
            />
          </div>
          <div className="form-group">
            <label htmlFor="reviews-client">Client ID</label>
            <input
              id="reviews-client"
              className="input"
              value={clientId}
              onChange={(event) => setClientId(event.target.value)}
              placeholder="client uuid"
            />
          </div>
          <div className="form-group">
            <label htmlFor="reviews-issue">Issue flag</label>
            <select
              id="reviews-issue"
              className="input"
              value={hasIssue}
              onChange={(event) => setHasIssue(event.target.value)}
            >
              {ISSUE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <section className="admin-card">
        <header className="admin-section" style={{ marginBottom: "16px" }}>
          <div>
            <h2>Reviews timeline</h2>
            <p className="muted">
              {loading ? "Loading reviews…" : `${total} reviews`}
            </p>
          </div>
          <div className="admin-actions">
            <button
              className="btn btn-ghost"
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((prev) => Math.max(1, prev - 1))}
            >
              Previous
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
            >
              Next
            </button>
            <span className="muted">
              Page {page} of {totalPages}
            </span>
          </div>
        </header>

        {error ? <p className="error">{error}</p> : null}

        {reviews.length === 0 && !loading ? (
          <p className="muted">No reviews found for the selected filters.</p>
        ) : (
          <div style={{ display: "grid", gap: "12px" }}>
            {reviews.map((review) => (
              <div key={review.feedback_id} className="card">
                <div className="card-body" style={{ display: "grid", gap: "8px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "12px" }}>
                    <div>
                      <strong>{review.client_name ?? "Unknown client"}</strong>
                      <div className="muted small">
                        {review.client_email ?? review.client_id}
                      </div>
                    </div>
                    <div className="muted small" style={{ textAlign: "right" }}>
                      {formatDateTime(review.created_at)}
                    </div>
                  </div>
                  <div className="muted small">
                    Booking {review.booking_id} · {review.booking_starts_at ? formatDateTime(review.booking_starts_at) : "No date"}
                  </div>
                  <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "center" }}>
                    <span className="pill">{review.rating}★</span>
                    <span className="muted small">
                      Worker: {review.worker_name ?? review.worker_id ?? "Unassigned"}
                    </span>
                    {review.has_issue ? (
                      <span className="pill pill-warning">Issue logged</span>
                    ) : (
                      <span className="pill pill-success">No issue</span>
                    )}
                  </div>
                  <p style={{ margin: 0 }}>{review.comment ?? "No comment provided."}</p>
                  <div className="admin-actions" style={{ justifyContent: "flex-end" }}>
                    <button
                      className="btn btn-ghost"
                      type="button"
                      disabled={!hasManagePermission}
                      onClick={() => openReplyModal(review)}
                    >
                      Reply
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {activeReview ? (
        <div className="schedule-modal" role="dialog" aria-modal="true">
          <div className="schedule-modal-backdrop" onClick={closeReplyModal} />
          <div className="schedule-modal-panel" style={{ maxWidth: "560px" }}>
            <header className="schedule-modal-header">
              <div>
                <h3>Reply to review</h3>
                <p className="muted small">
                  {activeReview.client_name ?? "Client"} · {activeReview.rating}★
                </p>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeReplyModal}>
                Close
              </button>
            </header>
            <div className="schedule-modal-body">
              <div className="form-group">
                <label htmlFor="review-template">Template</label>
                <select
                  id="review-template"
                  className="input"
                  value={replyTemplateKey}
                  onChange={(event) => handleTemplateChange(event.target.value)}
                >
                  <option value="">Custom message</option>
                  {templates.map((template) => (
                    <option key={template.key} value={template.key}>
                      {template.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label htmlFor="review-message">Message</label>
                <textarea
                  id="review-message"
                  className="input"
                  rows={4}
                  value={replyMessage}
                  onChange={(event) => setReplyMessage(event.target.value)}
                  placeholder="Write a response…"
                />
              </div>
              {replyError ? <p className="error">{replyError}</p> : null}
              {replyStatus ? <p className="muted">{replyStatus}</p> : null}
            </div>
            <footer className="schedule-modal-footer">
              <button className="btn btn-ghost" type="button" onClick={closeReplyModal}>
                Cancel
              </button>
              <button
                className="btn"
                type="button"
                disabled={replyLoading || !hasManagePermission}
                onClick={submitReply}
              >
                {replyLoading ? "Sending…" : "Log reply"}
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </div>
  );
}
