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

const BLOCK_TYPES = ["vacation", "sick", "training", "holiday"] as const;
const SCOPE_TYPES = ["org", "team", "worker"] as const;

type AvailabilityBlock = {
  id: number;
  scope_type: "worker" | "team" | "org";
  scope_id: number | null;
  block_type: "vacation" | "sick" | "training" | "holiday";
  starts_at: string;
  ends_at: string;
  reason: string | null;
  created_by: string | null;
  created_at: string;
};

function formatDateTimeInput(date: Date) {
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const hour = `${date.getHours()}`.padStart(2, "0");
  const minute = `${date.getMinutes()}`.padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function parseDateTimeLocal(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

function formatBlockType(value: AvailabilityBlock["block_type"]) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatScopeLabel(block: AvailabilityBlock) {
  if (block.scope_type === "org") return "All workers";
  const label = block.scope_type === "team" ? "Team" : "Worker";
  return `${label} #${block.scope_id ?? "—"}`;
}

export default function AvailabilityBlocksPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [blocks, setBlocks] = useState<AvailabilityBlock[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formScopeType, setFormScopeType] = useState<AvailabilityBlock["scope_type"]>("org");
  const [formScopeId, setFormScopeId] = useState("");
  const [formBlockType, setFormBlockType] = useState<AvailabilityBlock["block_type"]>("vacation");
  const [formStartsAt, setFormStartsAt] = useState("");
  const [formEndsAt, setFormEndsAt] = useState("");
  const [formReason, setFormReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [filterFrom, setFilterFrom] = useState("");
  const [filterTo, setFilterTo] = useState("");

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [password, username]);

  const isAuthenticated = Boolean(username && password);
  const permissionKeys = profile?.permissions ?? [];
  const canManage =
    permissionKeys.includes("settings.manage") || permissionKeys.includes("schedule.blocking.manage");

  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const pageVisible = visibilityReady
    ? isVisible("module.settings", permissionKeys, featureOverrides, hiddenKeys)
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
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
      {
        key: "availability-blocks",
        label: "Availability Blocks",
        href: "/admin/settings/availability-blocks",
        featureKey: "module.settings",
      },
      {
        key: "pricing",
        label: "Service Types & Pricing",
        href: "/admin/settings/pricing",
        featureKey: "module.settings",
      },
      {
        key: "policies",
        label: "Booking Policies",
        href: "/admin/settings/booking-policies",
        featureKey: "module.settings",
      },
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

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    Promise.all([
      fetch(`${API_BASE}/v1/admin/profile`, { headers: authHeaders }),
      fetch(`${API_BASE}/v1/admin/features`, { headers: authHeaders }),
      fetch(`${API_BASE}/v1/admin/ui-prefs`, { headers: authHeaders }),
    ])
      .then(async ([profileRes, featuresRes, prefsRes]) => {
        if (!profileRes.ok) throw new Error("Failed to load profile");
        if (!featuresRes.ok) throw new Error("Failed to load feature flags");
        if (!prefsRes.ok) throw new Error("Failed to load UI prefs");
        const [profilePayload, featuresPayload, prefsPayload] = await Promise.all([
          profileRes.json(),
          featuresRes.json(),
          prefsRes.json(),
        ]);
        setProfile(profilePayload as AdminProfile);
        setFeatureConfig(featuresPayload as FeatureConfigResponse);
        setUiPrefs(prefsPayload as UiPrefsResponse);
      })
      .catch((fetchError) => {
        setError(fetchError instanceof Error ? fetchError.message : "Failed to load profile");
      });
  }, [authHeaders, isAuthenticated]);

  const resetForm = useCallback(() => {
    setEditingId(null);
    setFormScopeType("org");
    setFormScopeId("");
    setFormBlockType("vacation");
    setFormStartsAt("");
    setFormEndsAt("");
    setFormReason("");
    setFormError(null);
  }, []);

  const loadBlocks = useCallback(() => {
    if (!isAuthenticated) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (filterFrom) {
      const parsed = parseDateTimeLocal(filterFrom);
      if (parsed) params.set("from", parsed.toISOString());
    }
    if (filterTo) {
      const parsed = parseDateTimeLocal(filterTo);
      if (parsed) params.set("to", parsed.toISOString());
    }
    fetch(`${API_BASE}/v1/admin/availability-blocks?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load availability blocks");
        }
        return response.json();
      })
      .then((payload: AvailabilityBlock[]) => {
        setBlocks(Array.isArray(payload) ? payload : []);
      })
      .catch((fetchError) => {
        setError(fetchError instanceof Error ? fetchError.message : "Failed to load availability blocks");
      })
      .finally(() => setLoading(false));
  }, [authHeaders, filterFrom, filterTo, isAuthenticated]);

  useEffect(() => {
    loadBlocks();
  }, [loadBlocks]);

  const handleSubmit = useCallback(async () => {
    if (!canManage) return;
    setFormError(null);
    const startsAt = parseDateTimeLocal(formStartsAt);
    const endsAt = parseDateTimeLocal(formEndsAt);
    if (!startsAt || !endsAt) {
      setFormError("Provide a valid start and end time.");
      return;
    }
    if (formScopeType !== "org" && !formScopeId) {
      setFormError("Provide a worker/team ID for this scope.");
      return;
    }
    const payload = {
      scope_type: formScopeType,
      scope_id: formScopeType === "org" ? null : Number(formScopeId),
      block_type: formBlockType,
      starts_at: startsAt.toISOString(),
      ends_at: endsAt.toISOString(),
      reason: formReason.trim() ? formReason.trim() : null,
    };
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/availability-blocks${editingId ? `/${editingId}` : ""}`,
        {
          method: editingId ? "PATCH" : "POST",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        }
      );
      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || "Failed to save availability block");
      }
      resetForm();
      loadBlocks();
    } catch (fetchError) {
      setFormError(
        fetchError instanceof Error ? fetchError.message : "Failed to save availability block"
      );
    }
  }, [
    authHeaders,
    canManage,
    editingId,
    formBlockType,
    formEndsAt,
    formReason,
    formScopeId,
    formScopeType,
    formStartsAt,
    loadBlocks,
    resetForm,
  ]);

  const handleEdit = useCallback((block: AvailabilityBlock) => {
    setEditingId(block.id);
    setFormScopeType(block.scope_type);
    setFormScopeId(block.scope_id ? String(block.scope_id) : "");
    setFormBlockType(block.block_type);
    setFormStartsAt(formatDateTimeInput(new Date(block.starts_at)));
    setFormEndsAt(formatDateTimeInput(new Date(block.ends_at)));
    setFormReason(block.reason ?? "");
    setFormError(null);
  }, []);

  const handleDelete = useCallback(
    async (blockId: number) => {
      if (!canManage) return;
      try {
        const response = await fetch(`${API_BASE}/v1/admin/availability-blocks/${blockId}`, {
          method: "DELETE",
          headers: authHeaders,
        });
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to delete availability block");
        }
        loadBlocks();
      } catch (fetchError) {
        setError(fetchError instanceof Error ? fetchError.message : "Failed to delete availability block");
      }
    },
    [authHeaders, canManage, loadBlocks]
  );

  if (visibilityReady && !pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="availability-blocks" />
        <div className="admin-card">
          <h1>Availability Blocks</h1>
          <p className="muted">Settings access is disabled for your role.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="availability-blocks" />
      <div className="admin-card">
        <header className="admin-card-header">
          <div>
            <h1>Availability blocks</h1>
            <p className="muted">Block scheduling for vacations, sick leave, training, and holidays.</p>
          </div>
        </header>

        <section className="settings-form">
          <div className="settings-subsection">
            <h2>Admin access</h2>
            <div className="schedule-auth">
              <div className="schedule-auth-fields">
                <label>
                  Username
                  <input
                    type="text"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="admin"
                  />
                </label>
                <label>
                  Password
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="••••••"
                  />
                </label>
              </div>
              <div className="schedule-auth-actions">
                <button
                  className="btn"
                  type="button"
                  onClick={() => {
                    if (!username || !password) return;
                    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
                    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
                  }}
                >
                  Save credentials
                </button>
                <button
                  className="btn secondary"
                  type="button"
                  onClick={() => {
                    setUsername("");
                    setPassword("");
                    setProfile(null);
                    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
                    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
                  }}
                >
                  Clear
                </button>
              </div>
            </div>
          </div>

          <div className="settings-subsection">
            <h2>Filters</h2>
            <div className="settings-meta">
              <label>
                From
                <input
                  type="datetime-local"
                  value={filterFrom}
                  onChange={(event) => setFilterFrom(event.target.value)}
                />
              </label>
              <label>
                To
                <input
                  type="datetime-local"
                  value={filterTo}
                  onChange={(event) => setFilterTo(event.target.value)}
                />
              </label>
              <button className="btn" type="button" onClick={loadBlocks}>
                Refresh
              </button>
            </div>
          </div>

          <div className="settings-subsection">
            <h2>{editingId ? "Edit block" : "Create block"}</h2>
            {!canManage ? (
              <p className="muted">You do not have permission to manage availability blocks.</p>
            ) : null}
            <div className="settings-grid">
              <label>
                Scope
                <select
                  value={formScopeType}
                  onChange={(event) => {
                    const next = event.target.value as AvailabilityBlock["scope_type"];
                    setFormScopeType(next);
                    if (next === "org") setFormScopeId("");
                  }}
                >
                  {SCOPE_TYPES.map((scope) => (
                    <option key={scope} value={scope}>
                      {scope === "org" ? "All workers" : scope}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Scope ID
                <input
                  type="number"
                  value={formScopeId}
                  onChange={(event) => setFormScopeId(event.target.value)}
                  disabled={formScopeType === "org"}
                  placeholder={formScopeType === "org" ? "—" : "Enter ID"}
                />
              </label>
              <label>
                Block type
                <select
                  value={formBlockType}
                  onChange={(event) => setFormBlockType(event.target.value as AvailabilityBlock["block_type"])}
                >
                  {BLOCK_TYPES.map((block) => (
                    <option key={block} value={block}>
                      {formatBlockType(block)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Starts at
                <input
                  type="datetime-local"
                  value={formStartsAt}
                  onChange={(event) => setFormStartsAt(event.target.value)}
                />
              </label>
              <label>
                Ends at
                <input
                  type="datetime-local"
                  value={formEndsAt}
                  onChange={(event) => setFormEndsAt(event.target.value)}
                />
              </label>
              <label>
                Reason
                <input
                  type="text"
                  value={formReason}
                  onChange={(event) => setFormReason(event.target.value)}
                  placeholder="Optional"
                />
              </label>
            </div>
            {formError ? <p className="muted">{formError}</p> : null}
            <div className="settings-actions">
              <button className="btn" type="button" disabled={!canManage} onClick={handleSubmit}>
                {editingId ? "Save changes" : "Create block"}
              </button>
              {editingId ? (
                <button className="btn secondary" type="button" onClick={resetForm}>
                  Cancel
                </button>
              ) : null}
            </div>
          </div>
        </section>

        <section className="settings-grid">
          {loading ? <p className="muted">Loading blocks…</p> : null}
          {error ? <p className="muted">{error}</p> : null}
          {blocks.map((block) => (
            <article className="settings-card" key={block.id}>
              <div className="settings-card-header">
                <div>
                  <h3>{formatBlockType(block.block_type)}</h3>
                  <p className="muted">{formatScopeLabel(block)}</p>
                </div>
                <div className="settings-actions">
                  <button className="btn secondary" type="button" onClick={() => handleEdit(block)}>
                    Edit
                  </button>
                  <button className="btn danger" type="button" onClick={() => handleDelete(block.id)}>
                    Delete
                  </button>
                </div>
              </div>
              <div className="settings-card-body">
                <div className="settings-meta">
                  <div>
                    <strong>Starts</strong>
                    <div>{new Date(block.starts_at).toLocaleString()}</div>
                  </div>
                  <div>
                    <strong>Ends</strong>
                    <div>{new Date(block.ends_at).toLocaleString()}</div>
                  </div>
                  <div>
                    <strong>Reason</strong>
                    <div>{block.reason || "—"}</div>
                  </div>
                  <div>
                    <strong>Created by</strong>
                    <div>{block.created_by || "—"}</div>
                  </div>
                </div>
              </div>
            </article>
          ))}
        </section>
      </div>
    </div>
  );
}
