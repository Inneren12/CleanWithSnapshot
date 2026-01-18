"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

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

type QualityPhotoEvidenceItem = {
  photo_id: string;
  booking_id: string;
  kind: "BEFORE" | "AFTER";
  storage_key: string;
  mime: string;
  bytes: number;
  consent: boolean;
  uploaded_by: string;
  created_at: string;
  worker_id: number | null;
  has_issue: boolean;
};

type QualityPhotoEvidenceListResponse = {
  items: QualityPhotoEvidenceItem[];
  total: number;
};

type PhotoGroup = {
  bookingId: string;
  workerId: number | null;
  hasIssue: boolean;
  latestAt: string;
  before: QualityPhotoEvidenceItem[];
  after: QualityPhotoEvidenceItem[];
};

type LightboxState = {
  photo: QualityPhotoEvidenceItem;
  label: string;
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

export default function QualityPhotosClient() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [photoData, setPhotoData] = useState<QualityPhotoEvidenceListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState(() => searchParams.get("from") ?? "");
  const [toDate, setToDate] = useState(() => searchParams.get("to") ?? "");
  const [workerId, setWorkerId] = useState(() => searchParams.get("worker_id") ?? "");
  const [hasIssue, setHasIssue] = useState(() => searchParams.get("has_issue") ?? "all");
  const [bookingFilter, setBookingFilter] = useState(() => searchParams.get("booking_id") ?? "");
  const [lightbox, setLightbox] = useState<LightboxState | null>(null);
  const [signedUrl, setSignedUrl] = useState<string | null>(null);
  const [lightboxLoading, setLightboxLoading] = useState(false);
  const [lightboxError, setLightboxError] = useState<string | null>(null);

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
  const photoEvidenceVisible = visibilityReady
    ? isVisible("quality.photo_evidence", permissionKeys, featureOverrides, hiddenKeys)
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

  const updateUrl = useCallback(() => {
    const params = new URLSearchParams();
    if (fromDate) params.set("from", fromDate);
    if (toDate) params.set("to", toDate);
    if (workerId) params.set("worker_id", workerId);
    if (hasIssue !== "all") params.set("has_issue", hasIssue);
    if (bookingFilter) params.set("booking_id", bookingFilter);
    const queryString = params.toString();
    router.push(queryString ? `/admin/quality/photos?${queryString}` : "/admin/quality/photos");
  }, [bookingFilter, fromDate, hasIssue, router, toDate, workerId]);

  const loadPhotos = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (fromDate) params.set("from", fromDate);
      if (toDate) params.set("to", toDate);
      if (workerId) params.set("worker_id", workerId);
      if (hasIssue !== "all") params.set("has_issue", hasIssue);
      const response = await fetch(`${API_BASE}/v1/admin/quality/photos?${params}`, {
        headers: authHeaders,
      });
      if (!response.ok) {
        throw new Error(`Failed to load photos (${response.status})`);
      }
      const data = (await response.json()) as QualityPhotoEvidenceListResponse;
      setPhotoData(data);
    } catch (err) {
      console.error("Failed to load photos", err);
      setError("Unable to load photo evidence.");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, fromDate, hasIssue, password, toDate, username, workerId]);

  const openLightbox = useCallback(
    async (photo: QualityPhotoEvidenceItem, label: string) => {
      setLightbox({ photo, label });
      setSignedUrl(null);
      setLightboxError(null);
      setLightboxLoading(true);
      try {
        const response = await fetch(`${API_BASE}/v1/admin/photos/${photo.photo_id}/signed_url`, {
          headers: authHeaders,
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(`Failed to load signed URL (${response.status})`);
        }
        const data = (await response.json()) as { url: string };
        setSignedUrl(data.url);
      } catch (err) {
        console.error("Failed to load signed URL", err);
        setLightboxError("Unable to load signed photo URL.");
      } finally {
        setLightboxLoading(false);
      }
    },
    [authHeaders]
  );

  const closeLightbox = useCallback(() => {
    setLightbox(null);
    setSignedUrl(null);
    setLightboxError(null);
    setLightboxLoading(false);
  }, []);

  const clearFilters = useCallback(() => {
    setFromDate("");
    setToDate("");
    setWorkerId("");
    setHasIssue("all");
    setBookingFilter("");
    router.push("/admin/quality/photos");
  }, [router]);

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
    if (!username || !password || !hasViewPermission || !photoEvidenceVisible) return;
    loadPhotos();
  }, [hasViewPermission, loadPhotos, password, photoEvidenceVisible, username]);

  const items = photoData?.items ?? [];
  const filteredItems = useMemo(() => {
    if (!bookingFilter) return items;
    return items.filter((item) => item.booking_id === bookingFilter);
  }, [bookingFilter, items]);

  const grouped = useMemo<PhotoGroup[]>(() => {
    const map = new Map<string, PhotoGroup>();
    const sortedItems = [...filteredItems].sort((a, b) => b.created_at.localeCompare(a.created_at));
    for (const item of sortedItems) {
      const existing = map.get(item.booking_id);
      const hasIssueFlag = existing?.hasIssue ?? false;
      const group: PhotoGroup = existing ?? {
        bookingId: item.booking_id,
        workerId: item.worker_id,
        hasIssue: item.has_issue,
        latestAt: item.created_at,
        before: [],
        after: [],
      };
      group.hasIssue = hasIssueFlag || item.has_issue;
      if (item.created_at > group.latestAt) {
        group.latestAt = item.created_at;
      }
      if (group.workerId === null) {
        group.workerId = item.worker_id;
      }
      if (item.kind === "BEFORE") {
        group.before.push(item);
      } else {
        group.after.push(item);
      }
      map.set(item.booking_id, group);
    }
    return Array.from(map.values()).sort((a, b) => b.latestAt.localeCompare(a.latestAt));
  }, [filteredItems]);

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
          <div className="card-body">You do not have permission to view quality photos.</div>
        </div>
      </div>
    );
  }

  if (!photoEvidenceVisible) {
    return (
      <div className="admin-page">
        <div className="card">
          <div className="card-body">Photo evidence gallery is disabled for your account.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="quality" />
      <div className="card">
        <div className="card-header">
          <div>
            <h1>Photo Evidence Gallery</h1>
            <p className="muted">Review before/after evidence by booking. Signed URLs are fetched on demand.</p>
          </div>
          <div className="hero-actions">
            <Link className="btn btn-ghost" href="/admin/quality/reviews">
              Reviews timeline
            </Link>
            <Link className="btn btn-ghost" href="/admin/quality/issues">
              Issue triage
            </Link>
            <Link className="btn btn-ghost" href="/admin/quality">
              Quality overview
            </Link>
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
            <label className="input-label">
              Worker ID
              <input
                className="input"
                type="number"
                value={workerId}
                onChange={(event) => setWorkerId(event.target.value)}
                placeholder="e.g. 102"
              />
            </label>
            <label className="input-label">
              Has issue
              <select className="input" value={hasIssue} onChange={(event) => setHasIssue(event.target.value)}>
                <option value="all">All</option>
                <option value="true">Has issue</option>
                <option value="false">No issue</option>
              </select>
            </label>
            <label className="input-label">
              Booking ID
              <input
                className="input"
                type="text"
                value={bookingFilter}
                onChange={(event) => setBookingFilter(event.target.value)}
                placeholder="Optional"
              />
            </label>
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => {
                updateUrl();
                loadPhotos();
              }}
              disabled={loading}
            >
              {loading ? "Loading…" : "Apply filters"}
            </button>
            <button className="btn btn-ghost" type="button" onClick={clearFilters} disabled={loading}>
              Clear
            </button>
          </div>
          {error ? <div className="error">{error}</div> : null}
          <div className="stack">
            <div className="muted">
              Showing {filteredItems.length} photos across {grouped.length} bookings.
              {bookingFilter ? ` Filtered to booking ${bookingFilter}.` : ""}
            </div>
            {loading && !photoData ? <p className="muted">Loading photo evidence…</p> : null}
            {!loading && grouped.length === 0 ? (
              <p className="muted">No photo evidence matches the selected filters.</p>
            ) : null}
            <div className="admin-grid">
              {grouped.map((group) => (
                <div key={group.bookingId} className="card admin-card">
                  <div className="card-header">
                    <div>
                      <strong>Booking {group.bookingId}</strong>
                      <div className="muted">Latest upload: {formatDateTime(group.latestAt)}</div>
                    </div>
                    {group.hasIssue ? <span className="pill pill-warning">Has issue</span> : null}
                  </div>
                  <div className="card-body">
                    <div className="stack">
                      <div className="muted">Worker ID: {group.workerId ?? "—"}</div>
                      <div className="grid-3">
                        <div className="card">
                          <div className="card-body">
                            <strong>Before</strong>
                            <div className="stack">
                              {group.before.length === 0 ? (
                                <span className="muted">No before photos</span>
                              ) : (
                                group.before.map((photo) => (
                                  <button
                                    key={photo.photo_id}
                                    type="button"
                                    className="btn btn-ghost"
                                    onClick={() => openLightbox(photo, "Before")}
                                  >
                                    View before ({formatDateTime(photo.created_at)})
                                  </button>
                                ))
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="card">
                          <div className="card-body">
                            <strong>After</strong>
                            <div className="stack">
                              {group.after.length === 0 ? (
                                <span className="muted">No after photos</span>
                              ) : (
                                group.after.map((photo) => (
                                  <button
                                    key={photo.photo_id}
                                    type="button"
                                    className="btn btn-ghost"
                                    onClick={() => openLightbox(photo, "After")}
                                  >
                                    View after ({formatDateTime(photo.created_at)})
                                  </button>
                                ))
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {lightbox ? (
        <div className="schedule-modal">
          <div className="schedule-modal-backdrop" onClick={closeLightbox} />
          <div className="schedule-modal-panel" role="dialog" aria-modal="true">
            <div className="schedule-modal-header">
              <div>
                <strong>{lightbox.label} photo</strong>
                <div className="muted">
                  Booking {lightbox.photo.booking_id} · Uploaded {formatDateTime(lightbox.photo.created_at)}
                </div>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeLightbox}>
                Close
              </button>
            </div>
            <div className="schedule-modal-body">
              {lightboxLoading ? <p className="muted">Loading signed URL…</p> : null}
              {lightboxError ? <p className="error">{lightboxError}</p> : null}
              {signedUrl ? (
                <img
                  src={signedUrl}
                  alt={`${lightbox.label} photo for booking ${lightbox.photo.booking_id}`}
                  style={{ width: "100%", borderRadius: "12px", border: "1px solid var(--border)" }}
                />
              ) : null}
              <div className="muted">
                Photo ID: {lightbox.photo.photo_id} · Uploaded by {lightbox.photo.uploaded_by}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
