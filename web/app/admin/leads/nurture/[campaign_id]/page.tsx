"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  effectiveFeatureEnabled,
  isVisible,
} from "../../../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type NurtureCampaign = {
  campaign_id: string;
  key: string;
  name: string;
  enabled: boolean;
  created_at: string;
};

type NurtureStep = {
  step_id: string;
  campaign_id: string;
  step_index: number;
  delay_hours: number;
  channel: string;
  template_key?: string | null;
  payload_json?: Record<string, unknown> | null;
  active: boolean;
};

type NurtureStepListResponse = {
  items: NurtureStep[];
};

type StepDraft = {
  step_index: string;
  delay_hours: string;
  channel: string;
  template_key: string;
  payload_json: string;
  active: boolean;
};

const EMPTY_STEP: StepDraft = {
  step_index: "",
  delay_hours: "",
  channel: "email",
  template_key: "",
  payload_json: "",
  active: true,
};

function formatDateTime(value: string) {
  return new Date(value).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatPayload(payload?: Record<string, unknown> | null) {
  if (!payload) return "—";
  return JSON.stringify(payload, null, 2);
}

function parsePayload(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return JSON.parse(trimmed) as Record<string, unknown>;
}

function validateStepDraft(draft: StepDraft) {
  const errors: string[] = [];
  if (draft.step_index.trim() === "") errors.push("Step index is required.");
  if (draft.delay_hours.trim() === "") errors.push("Delay hours is required.");
  if (!draft.channel) errors.push("Channel is required.");
  if (draft.step_index.trim() !== "" && Number.isNaN(Number(draft.step_index))) {
    errors.push("Step index must be a number.");
  }
  if (draft.delay_hours.trim() !== "" && Number.isNaN(Number(draft.delay_hours))) {
    errors.push("Delay hours must be a number.");
  }
  if (draft.payload_json.trim()) {
    try {
      parsePayload(draft.payload_json);
    } catch {
      errors.push("Payload JSON must be valid JSON.");
    }
  }
  return errors;
}

export default function LeadNurtureCampaignDetailPage() {
  const params = useParams();
  const campaignId = params.campaign_id as string;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [campaign, setCampaign] = useState<NurtureCampaign | null>(null);
  const [steps, setSteps] = useState<NurtureStep[]>([]);
  const [stepDraft, setStepDraft] = useState<StepDraft>(EMPTY_STEP);
  const [editingStep, setEditingStep] = useState<NurtureStep | null>(null);
  const [draftErrors, setDraftErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
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

  const pageVisible = visibilityReady
    ? isVisible("leads.nurture", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const nurtureEnabled = featureConfig
    ? effectiveFeatureEnabled(featureOverrides, "module.leads") &&
      effectiveFeatureEnabled(featureOverrides, "leads.nurture")
    : true;

  const canManage = permissionKeys.includes("contacts.edit") || permissionKeys.includes("leads.manage");

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
      {
        key: "pricing",
        label: "Service Types & Pricing",
        href: "/admin/settings/pricing",
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
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    } else {
      setFeatureConfig(null);
      setSettingsError("Failed to load module settings.");
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    } else {
      setUiPrefs(null);
      setSettingsError("Failed to load UI preferences.");
    }
  }, [authHeaders, password, username]);

  const loadCampaign = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/nurture/campaigns/${campaignId}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as NurtureCampaign;
      setCampaign(data);
    } else if (response.status === 404) {
      setError("Campaign not found.");
    } else if (response.status === 403) {
      setError("You do not have permission to view this campaign.");
    } else {
      setError("Failed to load campaign.");
    }
    setLoading(false);
  }, [authHeaders, campaignId, password, username]);

  const loadSteps = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    const response = await fetch(
      `${API_BASE}/v1/admin/leads/nurture/campaigns/${campaignId}/steps`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as NurtureStepListResponse;
      setSteps(data.items);
    } else if (response.status === 403) {
      setError("You do not have permission to view steps.");
    } else {
      setError("Failed to load steps.");
    }
    setLoading(false);
  }, [authHeaders, campaignId, password, username]);

  const resetStepDraft = useCallback(() => {
    setStepDraft(EMPTY_STEP);
    setEditingStep(null);
    setDraftErrors([]);
  }, []);

  const handleStepDraftChange = useCallback((field: keyof StepDraft, value: string | boolean) => {
    setStepDraft((prev) => ({
      ...prev,
      [field]: value,
    }));
  }, []);

  const handleSaveStep = useCallback(async () => {
    const errors = validateStepDraft(stepDraft);
    setDraftErrors(errors);
    if (errors.length) return;
    if (!username || !password) {
      setStatusMessage("Enter admin credentials first.");
      return;
    }
    if (!canManage) {
      setStatusMessage("You do not have permission to manage steps.");
      return;
    }
    setStatusMessage(null);
    const payloadJson =
      stepDraft.payload_json.trim() === "" ? null : parsePayload(stepDraft.payload_json);
    const endpoint = editingStep
      ? `${API_BASE}/v1/admin/leads/nurture/campaigns/${campaignId}/steps/${editingStep.step_id}`
      : `${API_BASE}/v1/admin/leads/nurture/campaigns/${campaignId}/steps`;
    const response = await fetch(endpoint, {
      method: editingStep ? "PATCH" : "POST",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        step_index: Number(stepDraft.step_index),
        delay_hours: Number(stepDraft.delay_hours),
        channel: stepDraft.channel,
        template_key: stepDraft.template_key.trim() || null,
        payload_json: payloadJson,
        active: stepDraft.active,
      }),
    });
    if (response.ok) {
      setStatusMessage(editingStep ? "Step updated." : "Step added.");
      resetStepDraft();
      void loadSteps();
    } else {
      setStatusMessage("Failed to save step.");
    }
  }, [
    authHeaders,
    campaignId,
    canManage,
    editingStep,
    loadSteps,
    password,
    resetStepDraft,
    stepDraft,
    username,
  ]);

  const handleDeleteStep = useCallback(
    async (stepId: string) => {
      if (!username || !password) {
        setStatusMessage("Enter admin credentials first.");
        return;
      }
      if (!canManage) {
        setStatusMessage("You do not have permission to delete steps.");
        return;
      }
      setStatusMessage(null);
      const response = await fetch(
        `${API_BASE}/v1/admin/leads/nurture/campaigns/${campaignId}/steps/${stepId}`,
        {
          method: "DELETE",
          headers: authHeaders,
        }
      );
      if (response.ok) {
        setStatusMessage("Step deleted.");
        void loadSteps();
      } else {
        setStatusMessage("Failed to delete step.");
      }
    },
    [authHeaders, campaignId, canManage, loadSteps, password, username]
  );

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs]);

  useEffect(() => {
    if (!nurtureEnabled) return;
    void loadCampaign();
    void loadSteps();
  }, [loadCampaign, loadSteps, nurtureEnabled]);

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="leads-nurture" />

      <section className="admin-card">
        <div className="section-heading">
          <div>
            <h1>{campaign?.name ?? "Campaign detail"}</h1>
            <p className="muted">
              <Link href="/admin/leads/nurture">Back to campaigns</Link>
            </p>
          </div>
          {campaign ? (
            <div>
              <div className="muted">Key: {campaign.key}</div>
              <div className="muted">Created: {formatDateTime(campaign.created_at)}</div>
            </div>
          ) : null}
        </div>
        <div className="admin-actions" style={{ flexWrap: "wrap" }}>
          <label style={{ flex: 1, minWidth: 220 }}>
            <span className="label">Admin username</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label style={{ flex: 1, minWidth: 220 }}>
            <span className="label">Admin password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
        </div>

        {visibilityReady && !pageVisible && (
          <p className="alert alert-warning">This nurture view is hidden for your profile.</p>
        )}
        {featureConfig && !nurtureEnabled && (
          <p className="alert alert-warning">Lead nurture is disabled by feature flag.</p>
        )}
        {!canManage && (
          <p className="alert alert-warning">You need leads.manage permission to edit steps.</p>
        )}
        {settingsError ? <p className="alert alert-error">{settingsError}</p> : null}
        {statusMessage ? <p className="alert">{statusMessage}</p> : null}
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading">
          <h2>{editingStep ? "Edit step" : "Add step"}</h2>
          {editingStep ? (
            <button className="btn btn-ghost" type="button" onClick={resetStepDraft}>
              Cancel edit
            </button>
          ) : null}
        </div>
        <div className="admin-actions" style={{ flexWrap: "wrap" }}>
          <label style={{ minWidth: 160 }}>
            <span className="label">Index</span>
            <input
              value={stepDraft.step_index}
              onChange={(event) => handleStepDraftChange("step_index", event.target.value)}
              placeholder="0"
            />
          </label>
          <label style={{ minWidth: 160 }}>
            <span className="label">Delay (hours)</span>
            <input
              value={stepDraft.delay_hours}
              onChange={(event) => handleStepDraftChange("delay_hours", event.target.value)}
              placeholder="24"
            />
          </label>
          <label style={{ minWidth: 160 }}>
            <span className="label">Channel</span>
            <select
              value={stepDraft.channel}
              onChange={(event) => handleStepDraftChange("channel", event.target.value)}
            >
              <option value="email">Email</option>
              <option value="sms">SMS</option>
              <option value="log_only">Log only</option>
            </select>
          </label>
          <label style={{ flex: 1, minWidth: 200 }}>
            <span className="label">Template key</span>
            <input
              value={stepDraft.template_key}
              onChange={(event) => handleStepDraftChange("template_key", event.target.value)}
              placeholder="lead_followup_01"
            />
          </label>
          <label style={{ minWidth: 160 }}>
            <span className="label">Active</span>
            <select
              value={stepDraft.active ? "active" : "inactive"}
              onChange={(event) => handleStepDraftChange("active", event.target.value === "active")}
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </label>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!nurtureEnabled}
            onClick={() => void handleSaveStep()}
          >
            {editingStep ? "Save step" : "Add step"}
          </button>
        </div>
        <label style={{ display: "block", marginTop: 12 }}>
          <span className="label">Payload JSON</span>
          <textarea
            rows={4}
            value={stepDraft.payload_json}
            onChange={(event) => handleStepDraftChange("payload_json", event.target.value)}
            placeholder='{"subject": "Welcome"}'
          />
        </label>
        {draftErrors.length ? (
          <ul className="alert alert-error" style={{ marginTop: 12 }}>
            {draftErrors.map((entry) => (
              <li key={entry}>{entry}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading">
          <h2>Steps</h2>
          <button className="btn btn-ghost" type="button" onClick={() => void loadSteps()}>
            Refresh
          </button>
        </div>
        {loading ? <p className="muted">Loading steps...</p> : null}
        {error ? <p className="alert alert-error">{error}</p> : null}
        {!loading && !steps.length ? <p className="muted">No steps configured yet.</p> : null}
        {steps.length ? (
          <div className="table-responsive">
            <table className="table-like">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Delay</th>
                  <th>Channel</th>
                  <th>Template</th>
                  <th>Payload</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((step) => (
                  <tr key={step.step_id}>
                    <td>{step.step_index}</td>
                    <td>{step.delay_hours}h</td>
                    <td>{step.channel}</td>
                    <td>{step.template_key ?? "—"}</td>
                    <td>
                      <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{formatPayload(step.payload_json)}</pre>
                    </td>
                    <td>{step.active ? "Active" : "Inactive"}</td>
                    <td>
                      <div className="admin-actions">
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => {
                            setEditingStep(step);
                            setStepDraft({
                              step_index: String(step.step_index),
                              delay_hours: String(step.delay_hours),
                              channel: step.channel,
                              template_key: step.template_key ?? "",
                              payload_json: step.payload_json ? JSON.stringify(step.payload_json, null, 2) : "",
                              active: step.active,
                            });
                            setDraftErrors([]);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => void handleDeleteStep(step.step_id)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
