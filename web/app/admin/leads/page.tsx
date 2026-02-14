"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../components/AdminNav";
import {
  ADMIN_STORAGE_PASSWORD_KEY,
  ADMIN_STORAGE_USERNAME_KEY,
  resolveAdminAuthHeaders,
} from "../lib/adminAuth";
import { DEFAULT_FEATURE_CONFIG, DEFAULT_UI_PREFS } from "../lib/adminDefaults";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../lib/featureVisibility";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined" ? window.location.origin : "");

const STATUS_OPTIONS = ["NEW", "CONTACTED", "QUOTED", "WON", "LOST"];

type Lead = {
  lead_id: string;
  name: string;
  email?: string | null;
  phone: string;
  status: string;
  notes?: string | null;
  loss_reason?: string | null;
  source?: string | null;
  campaign?: string | null;
  keyword?: string | null;
  landing_page?: string | null;
  created_at: string;
};

type LeadListResponse = {
  items: Lead[];
  total: number;
  page: number;
  page_size: number;
};

export default function LeadsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [leads, setLeads] = useState<LeadListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [query, setQuery] = useState<string>("");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [page, setPage] = useState(1);
  const [drafts, setDrafts] = useState<
    Record<string, { status?: string; notes?: string; loss_reason?: string }>
  >({});

  const { headers: authHeaders, hasCredentials } = useMemo(
    () => resolveAdminAuthHeaders(username, password),
    [username, password]
  );

  const permissionKeys = profile?.permissions ?? [];
  const canEditLeads =
    permissionKeys.includes("contacts.edit") || permissionKeys.includes("leads.edit");

  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];

    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "leads", label: "Leads", href: "/admin/leads", featureKey: "module.leads" },
      {
        key: "leads-nurture",
        label: "Lead Nurture",
        href: "/admin/leads/nurture",
        featureKey: "leads.nurture",
      },
      {
        key: "leads-scoring",
        label: "Lead Scoring",
        href: "/admin/leads/scoring",
        featureKey: "leads.scoring",
      },
      {
        key: "notifications",
        label: "Notifications",
        href: "/admin/notifications",
        featureKey: "module.notifications_center",
      },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
      {
        key: "availability-blocks",
        label: "Availability Blocks",
        href: "/admin/settings/availability-blocks",
        featureKey: "module.settings",
      },
      { key: "pricing", label: "Service Types & Pricing", href: "/admin/settings/pricing", featureKey: "module.settings" },
      {
        key: "policies",
        label: "Booking Policies",
        href: "/admin/settings/booking-policies",
        featureKey: "module.settings",
      },
      {
        key: "integrations",
        label: "Integrations",
        href: "/admin/settings/integrations",
        featureKey: "module.integrations",
      },
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "module.settings" },
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
    if (!hasCredentials) return;
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
  }, [authHeaders, hasCredentials]);

  const loadFeatureConfig = useCallback(async () => {
    if (!hasCredentials) return;
    setSettingsError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as FeatureConfigResponse;
        setFeatureConfig(data);
      } else {
        setFeatureConfig(DEFAULT_FEATURE_CONFIG);
        setSettingsError("Failed to load module settings. Using defaults.");
      }
    } catch (error) {
      console.error("Failed to load feature config:", error);
      setFeatureConfig(DEFAULT_FEATURE_CONFIG);
      setSettingsError("Failed to load module settings. Using defaults.");
    }
  }, [authHeaders, hasCredentials]);

  const loadUiPrefs = useCallback(async () => {
    if (!hasCredentials) return;
    setSettingsError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as UiPrefsResponse;
        setUiPrefs(data);
      } else {
        setUiPrefs(DEFAULT_UI_PREFS);
        setSettingsError("Failed to load UI preferences. Using defaults.");
      }
    } catch (error) {
      console.error("Failed to load UI preferences:", error);
      setUiPrefs(DEFAULT_UI_PREFS);
      setSettingsError("Failed to load UI preferences. Using defaults.");
    }
  }, [authHeaders, hasCredentials]);

  const loadLeads = useCallback(async () => {
    if (!hasCredentials) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (query.trim()) params.set("query", query.trim());
    if (fromDate) params.set("from", fromDate);
    if (toDate) params.set("to", toDate);
    params.set("page", String(page));

    const response = await fetch(`${API_BASE}/v1/admin/leads?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as LeadListResponse;
      setLeads(data);
    } else if (response.status === 403) {
      setError("You do not have permission to view leads.");
      setLeads(null);
    } else {
      setError("Failed to load leads.");
      setLeads(null);
    }
    setLoading(false);
  }, [authHeaders, fromDate, hasCredentials, page, query, statusFilter, toDate]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedUsername = window.localStorage.getItem(ADMIN_STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(ADMIN_STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadUiPrefs]);

  useEffect(() => {
    void loadLeads();
  }, [loadLeads]);

  useEffect(() => {
    setPage(1);
  }, [statusFilter, query, fromDate, toDate]);

  const saveCredentials = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(ADMIN_STORAGE_USERNAME_KEY, username);
      window.localStorage.setItem(ADMIN_STORAGE_PASSWORD_KEY, password);
    }
    setMessage("Saved credentials");
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  };

  const clearCredentials = () => {
    setUsername("");
    setPassword("");
    setProfile(null);
    setFeatureConfig(null);
    setUiPrefs(null);
    setLeads(null);
    setSettingsError(null);
    setMessage("Cleared credentials");
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(ADMIN_STORAGE_USERNAME_KEY);
      window.localStorage.removeItem(ADMIN_STORAGE_PASSWORD_KEY);
    }
  };

  const updateDraft = (leadId: string, field: "status" | "notes" | "loss_reason", value: string) => {
    setDrafts((prev) => ({
      ...prev,
      [leadId]: {
        status: field === "status" ? value : prev[leadId]?.status,
        notes: field === "notes" ? value : prev[leadId]?.notes,
        loss_reason: field === "loss_reason" ? value : prev[leadId]?.loss_reason,
      },
    }));
  };

  const saveLead = async (lead: Lead) => {
    if (!canEditLeads) {
      setMessage("Read-only role cannot update leads");
      return;
    }
    setMessage(null);
    const draft = drafts[lead.lead_id] ?? {};
    const payload = {
      status: draft.status ?? lead.status,
      notes: draft.notes ?? (lead.notes ?? ""),
      loss_reason: draft.loss_reason ?? (lead.loss_reason ?? ""),
    };
    const response = await fetch(`${API_BASE}/v1/admin/leads/${lead.lead_id}`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      setMessage("Lead updated");
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[lead.lead_id];
        return next;
      });
      void loadLeads();
    } else {
      setMessage("Failed to update lead");
    }
  };

  const totalPages = leads ? Math.max(1, Math.ceil(leads.total / leads.page_size)) : 1;

  return (
    <div className="page" data-testid="leads-page">
      <AdminNav links={navLinks} activeKey="leads" />
      <section className="admin-card admin-section">
        <div className="section-heading">
          <h1>Leads</h1>
          <p className="muted">Track pipeline status and update follow-ups.</p>
        </div>
        <div className="admin-actions">
          <label style={{ flex: 1 }}>
            <span className="label">Username</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label style={{ flex: 1 }}>
            <span className="label">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <div className="admin-actions">
            <button className="btn btn-primary" type="button" onClick={saveCredentials}>
              Save
            </button>
            <button className="btn btn-ghost" type="button" onClick={clearCredentials}>
              Clear
            </button>
          </div>
        </div>
        {message ? <p className="alert">{message}</p> : null}
        {settingsError ? <p className="alert alert-error">{settingsError}</p> : null}
      </section>

      <section className="admin-card admin-section" data-testid="leads-pipeline-section">
        <div className="section-heading">
          <h2>Pipeline</h2>
          <p className="muted">Filter by stage, search, and update lead notes.</p>
        </div>
        <div className="admin-actions" style={{ flexWrap: "wrap" }} data-testid="leads-pipeline">
          <div className="admin-actions">
            <button
              type="button"
              className={`btn ${statusFilter ? "btn-ghost" : "btn-primary"}`}
              onClick={() => setStatusFilter("")}
              data-testid="pipeline-stage-all"
            >
              All
            </button>
            {STATUS_OPTIONS.map((status) => (
              <button
                key={status}
                type="button"
                className={`btn ${statusFilter === status ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setStatusFilter(status)}
                data-testid={`pipeline-stage-${status.toLowerCase()}`}
              >
                {status}
              </button>
            ))}
          </div>
          <label style={{ minWidth: 220 }}>
            <span className="label">Search</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Name, email, phone" />
          </label>
          <label>
            <span className="label">From</span>
            <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
          </label>
          <label>
            <span className="label">To</span>
            <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
          </label>
          <button className="btn btn-ghost" type="button" onClick={() => void loadLeads()}>
            Refresh
          </button>
        </div>
        <div data-testid="leads-list">
          {loading ? <p className="muted">Loading leads...</p> : null}
          {error ? <p className="alert alert-error">{error}</p> : null}
          {!loading && leads?.items.length === 0 ? (
            <p className="muted" data-testid="leads-empty-state">
              No leads found.
            </p>
          ) : null}
          {leads?.items.length ? (
            <div className="table-responsive">
              <table className="table-like" data-testid="leads-table">
                <thead>
                  <tr>
                    <th>Lead</th>
                    <th>Source</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Notes</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.items.map((lead) => {
                    const draft = drafts[lead.lead_id] ?? {};
                    const statusValue = draft.status ?? lead.status;
                    const notesValue = draft.notes ?? (lead.notes ?? "");
                    const lossReasonValue = draft.loss_reason ?? (lead.loss_reason ?? "");
                    const showLossReason = statusValue === "LOST";
                    return (
                      <tr key={lead.lead_id}>
                        <td>
                          <strong>{lead.name}</strong>
                          <div className="muted">
                            {lead.email ?? "no email"} · {lead.phone}
                          </div>
                        </td>
                        <td>
                          <div>{lead.source ?? "—"}</div>
                          <div className="muted">
                            {lead.campaign ?? ""}
                            {lead.keyword ? ` · ${lead.keyword}` : ""}
                          </div>
                          <div className="muted">{lead.landing_page ?? ""}</div>
                        </td>
                        <td>
                          <select
                            value={statusValue}
                            disabled={!canEditLeads}
                            onChange={(event) => updateDraft(lead.lead_id, "status", event.target.value)}
                          >
                            {STATUS_OPTIONS.map((status) => (
                              <option key={status} value={status}>
                                {status}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>{new Date(lead.created_at).toLocaleDateString("en-CA")}</td>
                        <td>
                          <input
                            value={notesValue}
                            onChange={(event) => updateDraft(lead.lead_id, "notes", event.target.value)}
                            placeholder="Add notes"
                          />
                          {showLossReason ? (
                            <input
                              value={lossReasonValue}
                              onChange={(event) =>
                                updateDraft(lead.lead_id, "loss_reason", event.target.value)
                              }
                              placeholder="Loss reason"
                              style={{ marginTop: 8 }}
                            />
                          ) : null}
                        </td>
                        <td>
                          <button
                            className="btn btn-ghost"
                            type="button"
                            disabled={!canEditLeads}
                            onClick={() => void saveLead(lead)}
                          >
                            Save
                          </button>
                          <a className="btn btn-ghost" href={`/admin/leads/${lead.lead_id}`}>
                            View
                          </a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
        {leads ? (
          <div className="admin-actions" style={{ justifyContent: "space-between" }}>
            <span className="muted">
              Page {leads.page} of {totalPages} · {leads.total} leads
            </span>
            <div className="admin-actions">
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                disabled={leads.page <= 1}
              >
                Previous
              </button>
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                disabled={leads.page >= totalPages}
              >
                Next
              </button>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
