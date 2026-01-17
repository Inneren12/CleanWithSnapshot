"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import AdminNav from "../../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../../../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type QualityIssue = {
  id: string;
  booking_id: string | null;
  worker_id: number | null;
  client_id: string | null;
  rating: number | null;
  summary: string | null;
  details: string | null;
  status: string;
  severity: string;
  created_at: string;
  first_response_at: string | null;
  resolved_at: string | null;
  resolution_type: string | null;
  resolution_value: string | null;
  assignee_user_id: string | null;
};

type RelatedBooking = {
  booking_id: string;
  status: string;
  starts_at: string | null;
  team_id: number | null;
  assigned_worker_id: number | null;
};

type RelatedWorker = {
  worker_id: number;
  name: string;
  phone: string | null;
  email: string | null;
  team_id: number | null;
};

type RelatedClient = {
  client_id: string;
  name: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  is_blocked: boolean | null;
};

type ResponseLog = {
  response_id: string;
  response_type: string;
  message: string;
  created_by: string | null;
  created_at: string;
};

type IssueTag = {
  tag_key: string;
  label: string;
};

type QualityIssueDetail = {
  issue: QualityIssue;
  booking: RelatedBooking | null;
  worker: RelatedWorker | null;
  client: RelatedClient | null;
  responses: ResponseLog[];
  tags: IssueTag[];
  tag_catalog: IssueTag[];
};

const RESOLUTION_OPTIONS = [
  { value: "discount", label: "Discount" },
  { value: "redo", label: "Redo" },
  { value: "apology", label: "Apology" },
];

const RESPONSE_TYPE_OPTIONS = [
  { value: "response", label: "Outbound response" },
  { value: "note", label: "Internal note" },
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

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function QualityIssueDetailPage() {
  const params = useParams();
  const router = useRouter();
  const issueId = params.id as string;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [issueDetail, setIssueDetail] = useState<QualityIssueDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tagsSaving, setTagsSaving] = useState(false);
  const [tagsError, setTagsError] = useState<string | null>(null);

  const [resolutionType, setResolutionType] = useState(RESOLUTION_OPTIONS[0].value);
  const [resolutionValue, setResolutionValue] = useState("");
  const [responseType, setResponseType] = useState(RESPONSE_TYPE_OPTIONS[0].value);
  const [responseMessage, setResponseMessage] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

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
        const data: AdminProfile = await response.json();
        setProfile(data);
      }
    } catch (err) {
      console.error("Failed to load profile", err);
    }
  }, [username, password, authHeaders]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/features/config`, { headers: authHeaders });
      if (response.ok) {
        const data: FeatureConfigResponse = await response.json();
        setFeatureConfig(data);
      }
    } catch (err) {
      console.error("Failed to load feature config", err);
    }
  }, [username, password, authHeaders]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/ui/prefs`, { headers: authHeaders });
      if (response.ok) {
        const data: UiPrefsResponse = await response.json();
        setUiPrefs(data);
      }
    } catch (err) {
      console.error("Failed to load UI prefs", err);
    }
  }, [username, password, authHeaders]);

  const loadIssue = useCallback(async () => {
    if (!username || !password || !issueId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/quality/issues/${issueId}`, {
        headers: authHeaders,
      });
      if (response.ok) {
        const data: QualityIssueDetail = await response.json();
        setIssueDetail(data);
        setSelectedTags(data.tags.map((tag) => tag.tag_key));
      } else if (response.status === 404) {
        setError("Issue not found");
      } else {
        setError("Failed to load issue details");
      }
    } catch (err) {
      console.error("Failed to load issue", err);
      setError("Network error");
    } finally {
      setLoading(false);
    }
  }, [username, password, issueId, authHeaders]);

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername && storedPassword) {
      setUsername(storedUsername);
      setPassword(storedPassword);
    }
  }, []);

  useEffect(() => {
    if (username && password) {
      void loadProfile();
      void loadFeatureConfig();
      void loadUiPrefs();
    }
  }, [loadProfile, loadFeatureConfig, loadUiPrefs, username, password]);

  useEffect(() => {
    if (hasViewPermission) {
      void loadIssue();
    }
  }, [hasViewPermission, loadIssue]);

  const handleLogin = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault();
      localStorage.setItem(STORAGE_USERNAME_KEY, username);
      localStorage.setItem(STORAGE_PASSWORD_KEY, password);
      void loadProfile();
      void loadFeatureConfig();
      void loadUiPrefs();
    },
    [username, password, loadProfile, loadFeatureConfig, loadUiPrefs]
  );

  const handleStatusUpdate = useCallback(
    async (status: string) => {
      if (!hasManagePermission || !issueId) return;
      setActionMessage(null);
      setActionError(null);
      try {
        const response = await fetch(`${API_BASE}/v1/admin/quality/issues/${issueId}`, {
          method: "PATCH",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ status }),
        });
        if (response.ok) {
          setActionMessage(`Status updated to ${status}.`);
          setTimeout(() => setActionMessage(null), 3000);
          void loadIssue();
        } else {
          setActionError("Failed to update status.");
        }
      } catch (err) {
        console.error("Failed to update status", err);
        setActionError("Network error while updating status.");
      }
    },
    [authHeaders, hasManagePermission, issueId, loadIssue]
  );

  const handleResolutionSubmit = useCallback(async () => {
    if (!hasManagePermission || !issueId) return;
    if (!resolutionType) {
      setActionError("Select a resolution type.");
      return;
    }
    setActionMessage(null);
    setActionError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/quality/issues/${issueId}`, {
        method: "PATCH",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          resolution_type: resolutionType,
          resolution_value: resolutionValue || null,
        }),
      });
      if (response.ok) {
        setActionMessage("Resolution saved.");
        setTimeout(() => setActionMessage(null), 3000);
        void loadIssue();
      } else {
        setActionError("Failed to save resolution.");
      }
    } catch (err) {
      console.error("Failed to save resolution", err);
      setActionError("Network error while saving resolution.");
    }
  }, [authHeaders, hasManagePermission, issueId, loadIssue, resolutionType, resolutionValue]);

  const handleResponseSubmit = useCallback(async () => {
    if (!hasManagePermission || !issueId) return;
    if (!responseMessage.trim()) {
      setActionError("Response message cannot be empty.");
      return;
    }
    setActionMessage(null);
    setActionError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/quality/issues/${issueId}/respond`, {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          response_type: responseType,
          message: responseMessage.trim(),
        }),
      });
      if (response.ok) {
        setActionMessage("Response logged.");
        setResponseMessage("");
        setTimeout(() => setActionMessage(null), 3000);
        void loadIssue();
      } else {
        setActionError("Failed to log response.");
      }
    } catch (err) {
      console.error("Failed to log response", err);
      setActionError("Network error while logging response.");
    }
  }, [authHeaders, hasManagePermission, issueId, loadIssue, responseMessage, responseType]);

  const handleTagToggle = (tagKey: string) => {
    setSelectedTags((prev) =>
      prev.includes(tagKey) ? prev.filter((key) => key !== tagKey) : [...prev, tagKey]
    );
  };

  const handleTagSave = useCallback(async () => {
    if (!hasManagePermission || !issueId) return;
    setTagsSaving(true);
    setTagsError(null);
    setActionMessage(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/quality/issues/${issueId}/tags`, {
        method: "PATCH",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tag_keys: selectedTags }),
      });
      if (response.ok) {
        setActionMessage("Tags saved.");
        setTimeout(() => setActionMessage(null), 3000);
        void loadIssue();
      } else {
        setTagsError("Failed to save tags.");
      }
    } catch (err) {
      console.error("Failed to save tags", err);
      setTagsError("Network error while saving tags.");
    } finally {
      setTagsSaving(false);
    }
  }, [authHeaders, hasManagePermission, issueId, loadIssue, selectedTags]);

  if (!profile) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white p-8 rounded shadow-md w-full max-w-md">
          <h1 className="text-2xl font-bold mb-4">Admin Login</h1>
          <form onSubmit={handleLogin}>
            <div className="mb-4">
              <label className="block text-sm font-medium mb-1">Username</label>
              <input
                type="text"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="w-full border rounded px-3 py-2"
                required
              />
            </div>
            <div className="mb-4">
              <label className="block text-sm font-medium mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="w-full border rounded px-3 py-2"
                required
              />
            </div>
            <button type="submit" className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700">
              Login
            </button>
          </form>
        </div>
      </div>
    );
  }

  if (!pageVisible) {
    return (
      <div className="min-h-screen bg-gray-50">
        <AdminNav links={navLinks} activeKey="quality" />
        <div className="p-8">
          <p>You don&apos;t have permission to view this page.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <AdminNav links={navLinks} activeKey="quality" />

      <div className="max-w-6xl mx-auto p-8 space-y-6">
        <button
          onClick={() => router.push("/admin")}
          className="text-blue-600 hover:text-blue-800 flex items-center gap-2"
        >
          ← Back to Dashboard
        </button>

        {loading && <p className="text-gray-600">Loading issue...</p>}
        {error && <p className="text-red-600">{error}</p>}

        {actionMessage && <p className="text-green-600">{actionMessage}</p>}
        {actionError && <p className="text-red-600">{actionError}</p>}

        {issueDetail && (
          <>
            <section className="bg-white rounded shadow p-6">
              <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                <div>
                  <h1 className="text-2xl font-bold">Issue {issueDetail.issue.id}</h1>
                  <p className="text-gray-600">{issueDetail.issue.summary || "No summary provided"}</p>
                  <p className="text-sm text-gray-500 mt-1">{issueDetail.issue.details || "No details provided."}</p>
                  {issueDetail.tags.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-3">
                      {issueDetail.tags.map((tag) => (
                        <span key={tag.tag_key} className="px-2 py-1 rounded-full bg-blue-50 text-blue-700 text-xs">
                          {tag.label}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <span className="px-3 py-1 rounded-full bg-gray-100 text-gray-700 text-sm">
                    Status: {issueDetail.issue.status}
                  </span>
                  <span className="px-3 py-1 rounded-full bg-gray-100 text-gray-700 text-sm">
                    Severity: {issueDetail.issue.severity}
                  </span>
                  {issueDetail.issue.rating && (
                    <span className="px-3 py-1 rounded-full bg-gray-100 text-gray-700 text-sm">
                      Rating: {issueDetail.issue.rating}/5
                    </span>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
                <div className="border rounded p-4">
                  <h2 className="font-semibold mb-2">SLA timestamps</h2>
                  <p className="text-sm text-gray-600">Created: {formatDateTime(issueDetail.issue.created_at)}</p>
                  <p className="text-sm text-gray-600">
                    First response: {formatDateTime(issueDetail.issue.first_response_at)}
                  </p>
                  <p className="text-sm text-gray-600">Resolved: {formatDateTime(issueDetail.issue.resolved_at)}</p>
                </div>
                <div className="border rounded p-4">
                  <h2 className="font-semibold mb-2">Resolution</h2>
                  <p className="text-sm text-gray-600">
                    Type: {issueDetail.issue.resolution_type || "—"}
                  </p>
                  <p className="text-sm text-gray-600">
                    Value: {issueDetail.issue.resolution_value || "—"}
                  </p>
                </div>
                <div className="border rounded p-4">
                  <h2 className="font-semibold mb-2">Linked IDs</h2>
                  <p className="text-sm text-gray-600">Booking: {issueDetail.issue.booking_id || "—"}</p>
                  <p className="text-sm text-gray-600">Worker: {issueDetail.issue.worker_id || "—"}</p>
                  <p className="text-sm text-gray-600">Client: {issueDetail.issue.client_id || "—"}</p>
                </div>
              </div>
            </section>

            <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white rounded shadow p-4">
                <h3 className="font-semibold mb-2">Booking</h3>
                {issueDetail.booking ? (
                  <div className="text-sm text-gray-600 space-y-1">
                    <p>ID: {issueDetail.booking.booking_id}</p>
                    <p>Status: {issueDetail.booking.status}</p>
                    <p>Start: {formatDateTime(issueDetail.booking.starts_at)}</p>
                    <p>Team: {issueDetail.booking.team_id ?? "—"}</p>
                    <p>Assigned worker: {issueDetail.booking.assigned_worker_id ?? "—"}</p>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">No booking linked.</p>
                )}
              </div>
              <div className="bg-white rounded shadow p-4">
                <h3 className="font-semibold mb-2">Worker</h3>
                {issueDetail.worker ? (
                  <div className="text-sm text-gray-600 space-y-1">
                    <p>
                      {issueDetail.worker.name} (#{issueDetail.worker.worker_id})
                    </p>
                    <p>Phone: {issueDetail.worker.phone || "—"}</p>
                    <p>Email: {issueDetail.worker.email || "—"}</p>
                    <p>Team: {issueDetail.worker.team_id ?? "—"}</p>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">No worker linked.</p>
                )}
              </div>
              <div className="bg-white rounded shadow p-4">
                <h3 className="font-semibold mb-2">Client</h3>
                {issueDetail.client ? (
                  <div className="text-sm text-gray-600 space-y-1">
                    <p>{issueDetail.client.name || "Unnamed client"}</p>
                    <p>Email: {issueDetail.client.email || "—"}</p>
                    <p>Phone: {issueDetail.client.phone || "—"}</p>
                    <p>Address: {issueDetail.client.address || "—"}</p>
                    <p>Blocked: {issueDetail.client.is_blocked ? "Yes" : "No"}</p>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">No client linked.</p>
                )}
              </div>
            </section>

            <section className="bg-white rounded shadow p-6 space-y-6">
              <h2 className="text-xl font-semibold">Actions</h2>
              <div className="flex flex-wrap gap-3">
                <button
                  disabled={!hasManagePermission}
                  onClick={() => handleStatusUpdate("in_progress")}
                  className="px-4 py-2 rounded bg-blue-600 text-white disabled:opacity-50"
                >
                  Set In Progress
                </button>
                <button
                  disabled={!hasManagePermission}
                  onClick={() => handleStatusUpdate("resolved")}
                  className="px-4 py-2 rounded bg-green-600 text-white disabled:opacity-50"
                >
                  Resolve
                </button>
                <button
                  disabled={!hasManagePermission}
                  onClick={() => handleStatusUpdate("closed")}
                  className="px-4 py-2 rounded bg-gray-700 text-white disabled:opacity-50"
                >
                  Close
                </button>
              </div>

              <div className="border rounded p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="font-semibold">Issue tags</h3>
                    <p className="text-sm text-gray-500">Apply root cause tags for reporting.</p>
                  </div>
                  <button
                    disabled={!hasManagePermission || tagsSaving}
                    onClick={handleTagSave}
                    className="px-4 py-2 rounded bg-indigo-600 text-white disabled:opacity-50"
                  >
                    {tagsSaving ? "Saving..." : "Save tags"}
                  </button>
                </div>
                {tagsError && <p className="text-sm text-red-600">{tagsError}</p>}
                <div className="flex flex-wrap gap-3">
                  {issueDetail.tag_catalog.map((tag) => (
                    <label
                      key={tag.tag_key}
                      className={`flex items-center gap-2 px-3 py-2 rounded border text-sm ${
                        selectedTags.includes(tag.tag_key)
                          ? "border-blue-500 bg-blue-50 text-blue-800"
                          : "border-gray-200 text-gray-700"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedTags.includes(tag.tag_key)}
                        onChange={() => handleTagToggle(tag.tag_key)}
                        disabled={!hasManagePermission}
                      />
                      {tag.label}
                    </label>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="border rounded p-4 space-y-3">
                  <h3 className="font-semibold">Apply resolution</h3>
                  <div>
                    <label className="block text-sm font-medium mb-1">Resolution type</label>
                    <select
                      value={resolutionType}
                      onChange={(event) => setResolutionType(event.target.value)}
                      className="w-full border rounded px-3 py-2"
                    >
                      {RESOLUTION_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Resolution value (optional)</label>
                    <input
                      type="text"
                      value={resolutionValue}
                      onChange={(event) => setResolutionValue(event.target.value)}
                      className="w-full border rounded px-3 py-2"
                      placeholder="e.g. $25 credit, redo on 2026-02-01"
                    />
                  </div>
                  <button
                    disabled={!hasManagePermission}
                    onClick={handleResolutionSubmit}
                    className="px-4 py-2 rounded bg-indigo-600 text-white disabled:opacity-50"
                  >
                    Save resolution
                  </button>
                </div>

                <div className="border rounded p-4 space-y-3">
                  <h3 className="font-semibold">Log response / note</h3>
                  <div>
                    <label className="block text-sm font-medium mb-1">Entry type</label>
                    <select
                      value={responseType}
                      onChange={(event) => setResponseType(event.target.value)}
                      className="w-full border rounded px-3 py-2"
                    >
                      {RESPONSE_TYPE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Message</label>
                    <textarea
                      value={responseMessage}
                      onChange={(event) => setResponseMessage(event.target.value)}
                      className="w-full border rounded px-3 py-2 min-h-[120px]"
                      placeholder="Write the update you sent to the client or an internal note."
                    />
                  </div>
                  <button
                    disabled={!hasManagePermission}
                    onClick={handleResponseSubmit}
                    className="px-4 py-2 rounded bg-emerald-600 text-white disabled:opacity-50"
                  >
                    Log entry
                  </button>
                </div>
              </div>
            </section>

            <section className="bg-white rounded shadow p-6">
              <h2 className="text-xl font-semibold mb-4">History</h2>
              {issueDetail.responses.length === 0 ? (
                <p className="text-sm text-gray-500">No responses logged yet.</p>
              ) : (
                <div className="space-y-4">
                  {issueDetail.responses.map((entry) => (
                    <div key={entry.response_id} className="border rounded p-4">
                      <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500 mb-2">
                        <span className="uppercase tracking-wide">{entry.response_type}</span>
                        <span>{formatDate(entry.created_at)}</span>
                        <span>{entry.created_by || "Unknown admin"}</span>
                      </div>
                      <p className="text-gray-700 whitespace-pre-wrap">{entry.message}</p>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
