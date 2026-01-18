"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  effectiveFeatureEnabled,
  isVisible,
} from "../../lib/featureVisibility";

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

type NurtureCampaignListResponse = {
  items: NurtureCampaign[];
};

type CampaignDraft = {
  key: string;
  name: string;
  enabled: boolean;
};

const EMPTY_DRAFT: CampaignDraft = {
  key: "",
  name: "",
  enabled: true,
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

function buildDraftErrors(draft: CampaignDraft) {
  const errors: string[] = [];
  if (!draft.key.trim()) errors.push("Campaign key is required.");
  if (!draft.name.trim()) errors.push("Campaign name is required.");
  return errors;
}

export default function LeadsNurtureCampaignsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [campaigns, setCampaigns] = useState<NurtureCampaign[]>([]);
  const [campaignDraft, setCampaignDraft] = useState<CampaignDraft>(EMPTY_DRAFT);
  const [draftErrors, setDraftErrors] = useState<string[]>([]);
  const [editingCampaign, setEditingCampaign] = useState<NurtureCampaign | null>(null);
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

  const loadCampaigns = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);
    const response = await fetch(`${API_BASE}/v1/admin/leads/nurture/campaigns`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as NurtureCampaignListResponse;
      setCampaigns(data.items);
    } else if (response.status === 403) {
      setError("You do not have permission to view nurture campaigns.");
    } else {
      setError("Failed to load nurture campaigns.");
    }
    setLoading(false);
  }, [authHeaders, password, username]);

  const resetDraft = useCallback(() => {
    setCampaignDraft(EMPTY_DRAFT);
    setEditingCampaign(null);
    setDraftErrors([]);
  }, []);

  const handleDraftChange = useCallback(
    (field: keyof CampaignDraft, value: string | boolean) => {
      setCampaignDraft((prev) => ({
        ...prev,
        [field]: value,
      }));
    },
    []
  );

  const handleSaveCampaign = useCallback(async () => {
    const errors = buildDraftErrors(campaignDraft);
    setDraftErrors(errors);
    if (errors.length) return;
    if (!username || !password) {
      setStatusMessage("Enter admin credentials first.");
      return;
    }
    if (!canManage) {
      setStatusMessage("You do not have permission to manage nurture campaigns.");
      return;
    }
    setStatusMessage(null);
    const endpoint = editingCampaign
      ? `${API_BASE}/v1/admin/leads/nurture/campaigns/${editingCampaign.campaign_id}`
      : `${API_BASE}/v1/admin/leads/nurture/campaigns`;
    const response = await fetch(endpoint, {
      method: editingCampaign ? "PATCH" : "POST",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        key: campaignDraft.key.trim(),
        name: campaignDraft.name.trim(),
        enabled: campaignDraft.enabled,
      }),
    });
    if (response.ok) {
      setStatusMessage(editingCampaign ? "Campaign updated." : "Campaign created.");
      resetDraft();
      void loadCampaigns();
    } else {
      setStatusMessage("Failed to save campaign.");
    }
  }, [
    authHeaders,
    campaignDraft,
    canManage,
    editingCampaign,
    loadCampaigns,
    password,
    resetDraft,
    username,
  ]);

  const handleDeleteCampaign = useCallback(
    async (campaignId: string) => {
      if (!username || !password) {
        setStatusMessage("Enter admin credentials first.");
        return;
      }
      if (!canManage) {
        setStatusMessage("You do not have permission to delete nurture campaigns.");
        return;
      }
      setStatusMessage(null);
      const response = await fetch(`${API_BASE}/v1/admin/leads/nurture/campaigns/${campaignId}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (response.ok) {
        setStatusMessage("Campaign deleted.");
        void loadCampaigns();
      } else {
        setStatusMessage("Failed to delete campaign.");
      }
    },
    [authHeaders, canManage, loadCampaigns, password, username]
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
    void loadCampaigns();
  }, [loadCampaigns, nurtureEnabled]);

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="leads-nurture" />

      <section className="admin-card">
        <div className="section-heading">
          <h1>Lead nurture campaigns</h1>
          <p className="muted">Create nurture journeys and manage step scheduling per campaign.</p>
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
          <div className="admin-actions">
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => {
                localStorage.setItem(STORAGE_USERNAME_KEY, username);
                localStorage.setItem(STORAGE_PASSWORD_KEY, password);
                setStatusMessage("Credentials saved.");
              }}
            >
              Save
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => {
                localStorage.removeItem(STORAGE_USERNAME_KEY);
                localStorage.removeItem(STORAGE_PASSWORD_KEY);
                setUsername("");
                setPassword("");
                setStatusMessage("Credentials cleared.");
              }}
            >
              Clear
            </button>
          </div>
        </div>

        {visibilityReady && !pageVisible && (
          <p className="alert alert-warning">This nurture view is hidden for your profile.</p>
        )}
        {featureConfig && !nurtureEnabled && (
          <p className="alert alert-warning">Lead nurture is disabled by feature flag.</p>
        )}
        {!canManage && (
          <p className="alert alert-warning">You need leads.manage permission to edit campaigns.</p>
        )}
        {settingsError ? <p className="alert alert-error">{settingsError}</p> : null}
        {statusMessage ? <p className="alert">{statusMessage}</p> : null}
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading">
          <h2>{editingCampaign ? "Edit campaign" : "New campaign"}</h2>
          {editingCampaign ? (
            <button className="btn btn-ghost" type="button" onClick={resetDraft}>
              Cancel edit
            </button>
          ) : null}
        </div>
        <div className="admin-actions" style={{ flexWrap: "wrap" }}>
          <label style={{ flex: 1, minWidth: 220 }}>
            <span className="label">Key</span>
            <input
              value={campaignDraft.key}
              onChange={(event) => handleDraftChange("key", event.target.value)}
              placeholder="spring_followup"
            />
          </label>
          <label style={{ flex: 2, minWidth: 240 }}>
            <span className="label">Name</span>
            <input
              value={campaignDraft.name}
              onChange={(event) => handleDraftChange("name", event.target.value)}
              placeholder="Spring follow-up"
            />
          </label>
          <label style={{ minWidth: 160 }}>
            <span className="label">Enabled</span>
            <select
              value={campaignDraft.enabled ? "enabled" : "disabled"}
              onChange={(event) => handleDraftChange("enabled", event.target.value === "enabled")}
            >
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </select>
          </label>
          <button
            className="btn btn-primary"
            type="button"
            disabled={!nurtureEnabled}
            onClick={() => void handleSaveCampaign()}
          >
            {editingCampaign ? "Save changes" : "Create campaign"}
          </button>
        </div>
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
          <h2>Campaigns</h2>
          <div className="admin-actions">
            <button className="btn btn-ghost" type="button" onClick={() => void loadCampaigns()}>
              Refresh
            </button>
          </div>
        </div>
        {loading ? <p className="muted">Loading campaigns...</p> : null}
        {error ? <p className="alert alert-error">{error}</p> : null}
        {!loading && !campaigns.length ? <p className="muted">No nurture campaigns yet.</p> : null}
        {campaigns.length ? (
          <div className="table-responsive">
            <table className="table-like">
              <thead>
                <tr>
                  <th>Campaign</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Steps</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((campaign) => (
                  <tr key={campaign.campaign_id}>
                    <td>
                      <strong>{campaign.name}</strong>
                      <div className="muted">{campaign.key}</div>
                    </td>
                    <td>{campaign.enabled ? "Enabled" : "Disabled"}</td>
                    <td>{formatDateTime(campaign.created_at)}</td>
                    <td>
                      <Link className="btn btn-ghost" href={`/admin/leads/nurture/${campaign.campaign_id}`}>
                        Edit steps
                      </Link>
                    </td>
                    <td>
                      <div className="admin-actions">
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => {
                            setEditingCampaign(campaign);
                            setCampaignDraft({
                              key: campaign.key,
                              name: campaign.name,
                              enabled: campaign.enabled,
                            });
                            setDraftErrors([]);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => void handleDeleteCampaign(campaign.campaign_id)}
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
