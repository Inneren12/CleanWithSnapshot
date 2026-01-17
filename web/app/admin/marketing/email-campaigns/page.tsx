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

type EmailSegmentDefinition = {
  recipients: string[];
};

type EmailSegment = {
  segment_id: string;
  name: string;
  description?: string | null;
  definition: EmailSegmentDefinition;
  created_at: string;
  updated_at: string;
};

type EmailCampaign = {
  campaign_id: string;
  segment_id?: string | null;
  name: string;
  subject: string;
  content: string;
  status: string;
  scheduled_for?: string | null;
  sent_at?: string | null;
  created_at: string;
  updated_at: string;
};

type CampaignDraft = {
  name: string;
  subject: string;
  content: string;
  status: string;
  scheduled_for: string;
  segment_id: string;
};

type SegmentDraft = {
  name: string;
  description: string;
  recipients: string;
};

const defaultCampaignDraft: CampaignDraft = {
  name: "",
  subject: "",
  content: "",
  status: "DRAFT",
  scheduled_for: "",
  segment_id: "",
};

const defaultSegmentDraft: SegmentDraft = {
  name: "",
  description: "",
  recipients: "",
};

function fromDateTimeInput(value: string) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

function parseRecipients(input: string) {
  return input
    .split(/\n|,/) // newline or comma
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export default function EmailCampaignsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [segments, setSegments] = useState<EmailSegment[]>([]);
  const [campaigns, setCampaigns] = useState<EmailCampaign[]>([]);
  const [campaignDraft, setCampaignDraft] = useState<CampaignDraft>(defaultCampaignDraft);
  const [segmentDraft, setSegmentDraft] = useState<SegmentDraft>(defaultSegmentDraft);
  const [editingSegmentId, setEditingSegmentId] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

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
    ? isVisible("marketing.email_campaigns", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const canManage = permissionKeys.includes("settings.manage");

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
      {
        key: "marketing-analytics",
        label: "Marketing Analytics",
        href: "/admin/marketing/analytics",
        featureKey: "marketing.analytics",
      },
      {
        key: "marketing-campaigns",
        label: "Email Campaigns",
        href: "/admin/marketing/email-campaigns",
        featureKey: "marketing.email_campaigns",
      },
      {
        key: "marketing-promo-codes",
        label: "Promo Codes",
        href: "/admin/marketing/promo-codes",
        featureKey: "marketing.promo_codes",
      },
      {
        key: "pricing",
        label: "Service Types & Pricing",
        href: "/admin/settings/pricing",
        featureKey: "pricing.service_types",
      },
      {
        key: "modules",
        label: "Modules & Visibility",
        href: "/admin/settings/modules",
        featureKey: "api.settings",
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
    const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    } else {
      setFeatureConfig(null);
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/ui-prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    } else {
      setUiPrefs(null);
    }
  }, [authHeaders, password, username]);

  const loadSegments = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/marketing/email-segments`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as EmailSegment[];
      setSegments(data);
    }
  }, [authHeaders, password, username]);

  const loadCampaigns = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/marketing/email-campaigns`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as EmailCampaign[];
      setCampaigns(data);
    } else {
      setSettingsError("Failed to load email campaigns");
    }
  }, [authHeaders, password, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (!username || !password) return;
    void loadSegments();
    void loadCampaigns();
  }, [loadCampaigns, loadSegments, password, username]);

  const handleCampaignDraftChange = (field: keyof CampaignDraft, value: string) => {
    setCampaignDraft((prev) => ({ ...prev, [field]: value }));
  };

  const handleSegmentDraftChange = (field: keyof SegmentDraft, value: string) => {
    setSegmentDraft((prev) => ({ ...prev, [field]: value }));
  };

  const resetSegmentDraft = () => {
    setSegmentDraft(defaultSegmentDraft);
    setEditingSegmentId(null);
  };

  const saveCampaign = async () => {
    setStatusMessage(null);
    if (!campaignDraft.name.trim() || !campaignDraft.subject.trim() || !campaignDraft.content.trim()) {
      setStatusMessage("Name, subject, and content are required.");
      return;
    }
    if (campaignDraft.status === "SCHEDULED" && !campaignDraft.scheduled_for) {
      setStatusMessage("Scheduled campaigns require a send time.");
      return;
    }
    const response = await fetch(`${API_BASE}/v1/admin/marketing/email-campaigns`, {
      method: "POST",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: campaignDraft.name.trim(),
        subject: campaignDraft.subject.trim(),
        content: campaignDraft.content.trim(),
        status: campaignDraft.status,
        scheduled_for: fromDateTimeInput(campaignDraft.scheduled_for),
        segment_id: campaignDraft.segment_id || null,
      }),
    });
    if (response.ok) {
      setStatusMessage("Campaign created.");
      setCampaignDraft(defaultCampaignDraft);
      await loadCampaigns();
    } else {
      setStatusMessage("Failed to create campaign.");
    }
  };

  const saveSegment = async () => {
    setStatusMessage(null);
    if (!segmentDraft.name.trim()) {
      setStatusMessage("Segment name is required.");
      return;
    }
    const payload = {
      name: segmentDraft.name.trim(),
      description: segmentDraft.description.trim() || null,
      definition: {
        recipients: parseRecipients(segmentDraft.recipients),
      },
    };
    const url = editingSegmentId
      ? `${API_BASE}/v1/admin/marketing/email-segments/${editingSegmentId}`
      : `${API_BASE}/v1/admin/marketing/email-segments`;
    const response = await fetch(url, {
      method: editingSegmentId ? "PATCH" : "POST",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      setStatusMessage(editingSegmentId ? "Segment updated." : "Segment created.");
      resetSegmentDraft();
      await loadSegments();
    } else {
      setStatusMessage("Failed to save segment.");
    }
  };

  const deleteSegment = async (segmentId: string) => {
    setStatusMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/marketing/email-segments/${segmentId}`, {
      method: "DELETE",
      headers: authHeaders,
    });
    if (response.ok) {
      setStatusMessage("Segment deleted.");
      await loadSegments();
    } else {
      setStatusMessage("Failed to delete segment.");
    }
  };

  const startEditSegment = (segment: EmailSegment) => {
    setEditingSegmentId(segment.segment_id);
    setSegmentDraft({
      name: segment.name,
      description: segment.description ?? "",
      recipients: segment.definition.recipients.join(", "),
    });
  };

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="marketing-campaigns" />

      <div className="admin-card">
        <h1>Email Campaigns</h1>
        <p className="muted">Build manual campaigns and target custom segments.</p>

        <div className="grid" style={{ marginBottom: "1rem" }}>
          <div>
            <label className="form-label">Admin username</label>
            <input
              className="form-input"
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div>
            <label className="form-label">Admin password</label>
            <input
              className="form-input"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
        </div>

        {visibilityReady && !pageVisible && (
          <p className="error">This marketing email view is hidden for your profile.</p>
        )}

        {!canManage && <p className="error">You need settings.manage permission to edit email campaigns.</p>}

        {settingsError && <p className="error">{settingsError}</p>}
        {statusMessage && <p className="success">{statusMessage}</p>}

        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <h2>New campaign</h2>
          <div className="grid">
            <div>
              <label className="form-label">Name</label>
              <input
                className="form-input"
                value={campaignDraft.name}
                onChange={(event) => handleCampaignDraftChange("name", event.target.value)}
              />
            </div>
            <div>
              <label className="form-label">Subject</label>
              <input
                className="form-input"
                value={campaignDraft.subject}
                onChange={(event) => handleCampaignDraftChange("subject", event.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="form-label">Content</label>
            <textarea
              className="form-input"
              rows={4}
              value={campaignDraft.content}
              onChange={(event) => handleCampaignDraftChange("content", event.target.value)}
            />
          </div>
          <div className="grid">
            <div>
              <label className="form-label">Status</label>
              <select
                className="form-input"
                value={campaignDraft.status}
                onChange={(event) => handleCampaignDraftChange("status", event.target.value)}
              >
                <option value="DRAFT">Draft</option>
                <option value="SCHEDULED">Scheduled</option>
                <option value="SENT">Sent</option>
                <option value="CANCELLED">Cancelled</option>
              </select>
            </div>
            <div>
              <label className="form-label">Scheduled for</label>
              <input
                className="form-input"
                type="datetime-local"
                value={campaignDraft.scheduled_for}
                onChange={(event) => handleCampaignDraftChange("scheduled_for", event.target.value)}
              />
            </div>
            <div>
              <label className="form-label">Segment</label>
              <select
                className="form-input"
                value={campaignDraft.segment_id}
                onChange={(event) => handleCampaignDraftChange("segment_id", event.target.value)}
              >
                <option value="">No segment</option>
                {segments.map((segment) => (
                  <option key={segment.segment_id} value={segment.segment_id}>
                    {segment.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button className="button" onClick={() => void saveCampaign()}>
            Create campaign
          </button>
        </div>

        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <h2>Campaigns</h2>
          <div className="table-wrapper">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Segment</th>
                  <th>Scheduled</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.length ? (
                  campaigns.map((campaign) => (
                    <tr key={campaign.campaign_id}>
                      <td>{campaign.name}</td>
                      <td>{campaign.status}</td>
                      <td>{segments.find((seg) => seg.segment_id === campaign.segment_id)?.name ?? "—"}</td>
                      <td>{campaign.scheduled_for ? new Date(campaign.scheduled_for).toLocaleString() : "—"}</td>
                      <td>
                        <Link className="button" href={`/admin/marketing/email-campaigns/${campaign.campaign_id}`}>
                          View
                        </Link>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5}>No campaigns yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h2>Segments</h2>
          <div className="grid">
            <div>
              <label className="form-label">Name</label>
              <input
                className="form-input"
                value={segmentDraft.name}
                onChange={(event) => handleSegmentDraftChange("name", event.target.value)}
              />
            </div>
            <div>
              <label className="form-label">Description</label>
              <input
                className="form-input"
                value={segmentDraft.description}
                onChange={(event) => handleSegmentDraftChange("description", event.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="form-label">Recipients (comma or newline separated)</label>
            <textarea
              className="form-input"
              rows={3}
              value={segmentDraft.recipients}
              onChange={(event) => handleSegmentDraftChange("recipients", event.target.value)}
            />
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="button" onClick={() => void saveSegment()}>
              {editingSegmentId ? "Update segment" : "Create segment"}
            </button>
            {editingSegmentId && (
              <button className="button secondary" onClick={resetSegmentDraft}>
                Cancel edit
              </button>
            )}
          </div>

          <div className="table-wrapper" style={{ marginTop: "1rem" }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Recipients</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {segments.length ? (
                  segments.map((segment) => (
                    <tr key={segment.segment_id}>
                      <td>
                        <strong>{segment.name}</strong>
                        {segment.description ? <div className="muted">{segment.description}</div> : null}
                      </td>
                      <td>{segment.definition.recipients.length}</td>
                      <td>
                        <div style={{ display: "flex", gap: "0.5rem" }}>
                          <button className="button secondary" onClick={() => startEditSegment(segment)}>
                            Edit
                          </button>
                          <button className="button danger" onClick={() => void deleteSegment(segment.segment_id)}>
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={3}>No segments yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
