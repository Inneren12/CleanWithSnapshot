"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

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

type EmailSegment = {
  segment_id: string;
  name: string;
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

function toDateTimeInput(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function fromDateTimeInput(value: string) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

export default function EmailCampaignDetailPage() {
  const params = useParams();
  const router = useRouter();
  const campaignId = params?.campaignId as string | undefined;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [segments, setSegments] = useState<EmailSegment[]>([]);
  const [campaign, setCampaign] = useState<EmailCampaign | null>(null);
  const [campaignDraft, setCampaignDraft] = useState<CampaignDraft | null>(null);
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
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
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

  const loadCampaign = useCallback(async () => {
    if (!username || !password || !campaignId) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/marketing/email-campaigns/${campaignId}`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as EmailCampaign;
      setCampaign(data);
      setCampaignDraft({
        name: data.name,
        subject: data.subject,
        content: data.content,
        status: data.status,
        scheduled_for: toDateTimeInput(data.scheduled_for),
        segment_id: data.segment_id ?? "",
      });
    } else {
      setSettingsError("Failed to load campaign.");
    }
  }, [authHeaders, campaignId, password, username]);

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
    void loadCampaign();
  }, [loadCampaign, loadSegments, password, username]);

  const handleDraftChange = (field: keyof CampaignDraft, value: string) => {
    setCampaignDraft((prev) => (prev ? { ...prev, [field]: value } : prev));
  };

  const updateCampaign = async () => {
    if (!campaignDraft) return;
    setStatusMessage(null);
    if (!campaignDraft.name.trim() || !campaignDraft.subject.trim() || !campaignDraft.content.trim()) {
      setStatusMessage("Name, subject, and content are required.");
      return;
    }
    if (campaignDraft.status === "SCHEDULED" && !campaignDraft.scheduled_for) {
      setStatusMessage("Scheduled campaigns require a send time.");
      return;
    }
    const response = await fetch(`${API_BASE}/v1/admin/marketing/email-campaigns/${campaignId}`,
      {
        method: "PATCH",
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
      }
    );
    if (response.ok) {
      setStatusMessage("Campaign updated.");
      await loadCampaign();
    } else {
      setStatusMessage("Failed to update campaign.");
    }
  };

  const deleteCampaign = async () => {
    if (!campaignId) return;
    setStatusMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/marketing/email-campaigns/${campaignId}`,
      {
        method: "DELETE",
        headers: authHeaders,
      }
    );
    if (response.ok) {
      setStatusMessage("Campaign deleted.");
      router.push("/admin/marketing/email-campaigns");
    } else {
      setStatusMessage("Failed to delete campaign.");
    }
  };

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="marketing-campaigns" />

      <div className="admin-card">
        <h1>Campaign Detail</h1>
        <p className="muted">Edit manual campaign details and scheduling.</p>

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

        {!canManage && <p className="error">You need settings.manage permission to edit campaigns.</p>}

        {settingsError && <p className="error">{settingsError}</p>}
        {statusMessage && <p className="success">{statusMessage}</p>}

        {campaignDraft ? (
          <div className="card">
            <div className="grid">
              <div>
                <label className="form-label">Name</label>
                <input
                  className="form-input"
                  value={campaignDraft.name}
                  onChange={(event) => handleDraftChange("name", event.target.value)}
                />
              </div>
              <div>
                <label className="form-label">Subject</label>
                <input
                  className="form-input"
                  value={campaignDraft.subject}
                  onChange={(event) => handleDraftChange("subject", event.target.value)}
                />
              </div>
            </div>
            <div>
              <label className="form-label">Content</label>
              <textarea
                className="form-input"
                rows={5}
                value={campaignDraft.content}
                onChange={(event) => handleDraftChange("content", event.target.value)}
              />
            </div>
            <div className="grid">
              <div>
                <label className="form-label">Status</label>
                <select
                  className="form-input"
                  value={campaignDraft.status}
                  onChange={(event) => handleDraftChange("status", event.target.value)}
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
                  onChange={(event) => handleDraftChange("scheduled_for", event.target.value)}
                />
              </div>
              <div>
                <label className="form-label">Segment</label>
                <select
                  className="form-input"
                  value={campaignDraft.segment_id}
                  onChange={(event) => handleDraftChange("segment_id", event.target.value)}
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
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button className="button" onClick={() => void updateCampaign()}>
                Save changes
              </button>
              <button className="button danger" onClick={() => void deleteCampaign()}>
                Delete campaign
              </button>
            </div>
          </div>
        ) : (
          <p>Loading campaign...</p>
        )}
      </div>
    </div>
  );
}
