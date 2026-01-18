"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../components/AdminNav";
import { type AdminProfile, type FeatureConfigResponse, type UiPrefsResponse, isVisible } from "../../lib/featureVisibility";

type StripeCapabilities = {
  card?: boolean | null;
  apple_pay?: boolean | null;
  google_pay?: boolean | null;
};

type StripeIntegrationStatus = {
  connected: boolean;
  account?: string | null;
  webhook_configured: boolean;
  last_webhook_at?: string | null;
  capabilities: StripeCapabilities;
  health: string;
};

type TwilioIntegrationStatus = {
  connected: boolean;
  account?: string | null;
  sms_from?: string | null;
  call_from?: string | null;
  usage_summary?: string | null;
  health: string;
};

type EmailIntegrationStatus = {
  connected: boolean;
  mode: string;
  sender?: string | null;
  deliverability?: string | null;
  health: string;
};

type IntegrationsStatusResponse = {
  stripe: StripeIntegrationStatus;
  twilio: TwilioIntegrationStatus;
  email: EmailIntegrationStatus;
};

type GcalIntegrationStatus = {
  connected: boolean;
  calendar_id?: string | null;
  oauth_configured: boolean;
  last_sync_at?: string | null;
  last_error?: string | null;
};

type GcalConnectStartResponse = {
  authorization_url: string;
};

type QboIntegrationStatus = {
  connected: boolean;
  realm_id?: string | null;
  oauth_configured: boolean;
  last_sync_at?: string | null;
  last_error?: string | null;
};

type QboConnectStartResponse = {
  authorization_url: string;
};

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

function statusBadge(status: string, tone: "confirmed" | "pending" | "cancelled") {
  return <span className={`status-badge ${tone}`}>{status}</span>;
}

function formatMaybeDate(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "—";
  return parsed.toLocaleString();
}

function capabilityLabel(value?: boolean | null) {
  if (value === true) return "Enabled";
  if (value === false) return "Disabled";
  return "Unknown";
}

export default function IntegrationsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [integrations, setIntegrations] = useState<IntegrationsStatusResponse | null>(null);
  const [gcalStatus, setGcalStatus] = useState<GcalIntegrationStatus | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [gcalError, setGcalError] = useState<string | null>(null);
  const [qboStatus, setQboStatus] = useState<QboIntegrationStatus | null>(null);
  const [qboError, setQboError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [gcalLoading, setGcalLoading] = useState(false);
  const [qboLoading, setQboLoading] = useState(false);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const isOwner = profile?.role === "owner";
  const permissionKeys = profile?.permissions ?? [];
  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const pageVisible = visibilityReady
    ? isVisible("module.integrations", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const gcalVisible = visibilityReady
    ? isVisible("integrations.google_calendar", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const qboVisible = visibilityReady
    ? isVisible("integrations.accounting.quickbooks", permissionKeys, featureOverrides, hiddenKeys)
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
        key: "integrations",
        label: "Integrations",
        href: "/admin/settings/integrations",
        featureKey: "module.integrations",
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
      setSettingsError("Failed to load module settings");
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
      setSettingsError("Failed to load UI preferences");
    }
  }, [authHeaders, password, username]);

  const loadIntegrations = useCallback(async () => {
    if (!username || !password || !isOwner) return;
    setSettingsError(null);
    setLoading(true);
    const response = await fetch(`${API_BASE}/v1/admin/settings/integrations`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as IntegrationsStatusResponse;
      setIntegrations(data);
    } else {
      setIntegrations(null);
      setSettingsError("Failed to load integrations status");
    }
    setLoading(false);
  }, [authHeaders, isOwner, password, username]);

  const loadGcalStatus = useCallback(async () => {
    if (!username || !password) return;
    setGcalError(null);
    setGcalLoading(true);
    const response = await fetch(`${API_BASE}/v1/admin/integrations/google/status`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as GcalIntegrationStatus;
      setGcalStatus(data);
    } else if (response.status === 403) {
      setGcalStatus(null);
      setGcalError("Google Calendar integration is disabled.");
    } else {
      setGcalStatus(null);
      setGcalError("Failed to load Google Calendar status.");
    }
    setGcalLoading(false);
  }, [authHeaders, password, username]);

  const loadQboStatus = useCallback(async () => {
    if (!username || !password) return;
    setQboError(null);
    setQboLoading(true);
    const response = await fetch(`${API_BASE}/v1/admin/integrations/accounting/quickbooks/status`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as QboIntegrationStatus;
      setQboStatus(data);
    } else if (response.status === 403) {
      setQboStatus(null);
      setQboError("QuickBooks integration is disabled.");
    } else {
      setQboStatus(null);
      setQboError("Failed to load QuickBooks status.");
    }
    setQboLoading(false);
  }, [authHeaders, password, username]);

  const startGcalConnect = useCallback(async () => {
    if (!username || !password) return;
    setGcalError(null);
    setGcalLoading(true);
    const response = await fetch(`${API_BASE}/v1/admin/integrations/google/connect/start`, {
      method: "POST",
      headers: authHeaders,
    });
    if (!response.ok) {
      setGcalError("Failed to start Google Calendar connection.");
      setGcalLoading(false);
      return;
    }
    const data = (await response.json()) as GcalConnectStartResponse;
    setGcalLoading(false);
    window.location.href = data.authorization_url;
  }, [authHeaders, password, username]);

  const disconnectGcal = useCallback(async () => {
    if (!username || !password) return;
    setGcalError(null);
    setGcalLoading(true);
    const response = await fetch(`${API_BASE}/v1/admin/integrations/google/disconnect`, {
      method: "POST",
      headers: authHeaders,
    });
    if (!response.ok) {
      setGcalError("Failed to disconnect Google Calendar.");
      setGcalLoading(false);
      return;
    }
    await loadGcalStatus();
    setGcalLoading(false);
  }, [authHeaders, loadGcalStatus, password, username]);

  const startQboConnect = useCallback(async () => {
    if (!username || !password) return;
    setQboError(null);
    setQboLoading(true);
    const response = await fetch(`${API_BASE}/v1/admin/integrations/accounting/quickbooks/connect/start`, {
      method: "POST",
      headers: authHeaders,
    });
    if (!response.ok) {
      setQboError("Failed to start QuickBooks connection.");
      setQboLoading(false);
      return;
    }
    const data = (await response.json()) as QboConnectStartResponse;
    setQboLoading(false);
    window.location.href = data.authorization_url;
  }, [authHeaders, password, username]);

  const disconnectQbo = useCallback(async () => {
    if (!username || !password) return;
    setQboError(null);
    setQboLoading(true);
    const response = await fetch(`${API_BASE}/v1/admin/integrations/accounting/quickbooks/disconnect`, {
      method: "POST",
      headers: authHeaders,
    });
    if (!response.ok) {
      setQboError("Failed to disconnect QuickBooks.");
      setQboLoading(false);
      return;
    }
    await loadQboStatus();
    setQboLoading(false);
  }, [authHeaders, loadQboStatus, password, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
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
    if (!isOwner) return;
    void loadIntegrations();
  }, [isOwner, loadIntegrations]);

  useEffect(() => {
    if (!gcalVisible) return;
    void loadGcalStatus();
  }, [gcalVisible, loadGcalStatus]);

  useEffect(() => {
    if (!qboVisible) return;
    void loadQboStatus();
  }, [loadQboStatus, qboVisible]);

  useEffect(() => {
    if (!username || !password) return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code) return;
    const realmId = params.get("realmId");
    if (realmId) {
      if (!isOwner) {
        setQboError("Only Owners can complete QuickBooks connections.");
        return;
      }
      const finalizeConnect = async () => {
        setQboLoading(true);
        const response = await fetch(`${API_BASE}/v1/admin/integrations/accounting/quickbooks/connect/callback`, {
          method: "POST",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ code, realm_id: realmId, state }),
        });
        if (!response.ok) {
          setQboError("Failed to finish QuickBooks connection.");
        } else {
          await loadQboStatus();
        }
        setQboLoading(false);
        const cleanUrl = window.location.pathname;
        window.history.replaceState({}, "", cleanUrl);
      };
      void finalizeConnect();
      return;
    }
    if (!isOwner) {
      setGcalError("Only Owners can complete Google Calendar connections.");
      return;
    }
    const finalizeConnect = async () => {
      setGcalLoading(true);
      const response = await fetch(`${API_BASE}/v1/admin/integrations/google/connect/callback`, {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ code, state }),
      });
      if (!response.ok) {
        setGcalError("Failed to finish Google Calendar connection.");
      } else {
        await loadGcalStatus();
      }
      setGcalLoading(false);
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
    };
    void finalizeConnect();
  }, [authHeaders, isOwner, loadGcalStatus, loadQboStatus, password, username]);

  const stripe = integrations?.stripe;
  const twilio = integrations?.twilio;
  const email = integrations?.email;
  const gcal = gcalStatus;
  const qbo = qboStatus;

  const stripeBadge = stripe
    ? stripe.connected
      ? statusBadge("Connected", "confirmed")
      : statusBadge("Not connected", "cancelled")
    : statusBadge("Unknown", "pending");
  const twilioBadge = twilio
    ? twilio.connected
      ? statusBadge("Connected", "confirmed")
      : statusBadge("Not connected", "cancelled")
    : statusBadge("Unknown", "pending");
  const emailBadge = email
    ? email.connected
      ? statusBadge("Connected", "confirmed")
      : statusBadge("Not connected", "cancelled")
    : statusBadge("Unknown", "pending");
  const gcalBadge = gcal
    ? gcal.connected
      ? statusBadge("Connected", "confirmed")
      : statusBadge("Not connected", "cancelled")
    : statusBadge("Unknown", "pending");
  const qboBadge = qbo
    ? qbo.connected
      ? statusBadge("Connected", "confirmed")
      : statusBadge("Not connected", "cancelled")
    : statusBadge("Unknown", "pending");

  return (
    <div className="admin-page">
      {navLinks.length > 0 ? <AdminNav links={navLinks} activeKey="integrations" /> : null}
      <div className="admin-section">
        <div className="admin-section-header">
          <div>
            <p className="muted">Settings</p>
            <h1>Integrations</h1>
          </div>
        </div>

        {!pageVisible ? (
          <p className="alert alert-warning">Integrations are disabled for this organization.</p>
        ) : !username || !password ? (
          <p className="muted">Load admin credentials to view integration status.</p>
        ) : (
          <>
            {!gcalVisible && !qboVisible ? (
              <p className="alert alert-warning">Integrations are disabled for this organization.</p>
            ) : (
              <>
                {gcalError ? <p className="alert alert-warning">{gcalError}</p> : null}
                {qboError ? <p className="alert alert-warning">{qboError}</p> : null}
                {gcalLoading ? <p className="muted">Loading Google Calendar status…</p> : null}
                {qboLoading ? <p className="muted">Loading QuickBooks status…</p> : null}
                <div className="settings-grid">
                  {gcalVisible ? (
                    <div className="settings-card">
                      <div className="settings-card-header">
                        <div>
                          <strong>Google Calendar</strong>
                          <div className="muted small">Connect a Google account for calendar sync</div>
                        </div>
                        {gcalBadge}
                      </div>
                      <div className="settings-card-body">
                        <div className="settings-meta">
                          <div>
                            <div className="muted small">Status</div>
                            <strong>{gcal?.connected ? "Connected" : "Not connected"}</strong>
                          </div>
                          <div>
                            <div className="muted small">OAuth configured</div>
                            <strong>{gcal?.oauth_configured ? "Yes" : "No"}</strong>
                          </div>
                        </div>
                        <div className="settings-meta">
                          <div>
                            <div className="muted small">Calendar</div>
                            <select className="input" disabled>
                              <option>{gcal?.calendar_id ?? "Select calendar (coming soon)"}</option>
                            </select>
                          </div>
                        </div>
                        <div className="settings-meta">
                          <div>
                            <div className="muted small">Last sync</div>
                            <strong>{formatMaybeDate(gcal?.last_sync_at)}</strong>
                          </div>
                          <div>
                            <div className="muted small">Last error</div>
                            <strong>{gcal?.last_error ?? "—"}</strong>
                          </div>
                        </div>
                        <div className="settings-actions">
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={startGcalConnect}
                            disabled={!isOwner || gcalLoading || !gcal?.oauth_configured}
                            title={!isOwner ? "Owner access required" : undefined}
                          >
                            Connect
                          </button>
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={disconnectGcal}
                            disabled={!isOwner || gcalLoading || !gcal?.connected}
                            title={!isOwner ? "Owner access required" : undefined}
                          >
                            Disconnect
                          </button>
                        </div>
                        <div className="muted small">
                          Required: <code>GOOGLE_OAUTH_CLIENT_ID</code>, <code>GOOGLE_OAUTH_CLIENT_SECRET</code>,{" "}
                          <code>GOOGLE_OAUTH_REDIRECT_URI</code>
                        </div>
                      </div>
                    </div>
                  ) : null}
                  {qboVisible ? (
                    <div className="settings-card">
                      <div className="settings-card-header">
                        <div>
                          <strong>QuickBooks</strong>
                          <div className="muted small">Connect QuickBooks Online for accounting sync</div>
                        </div>
                        {qboBadge}
                      </div>
                      <div className="settings-card-body">
                        <div className="settings-meta">
                          <div>
                            <div className="muted small">Status</div>
                            <strong>{qbo?.connected ? "Connected" : "Not connected"}</strong>
                          </div>
                          <div>
                            <div className="muted small">OAuth configured</div>
                            <strong>{qbo?.oauth_configured ? "Yes" : "No"}</strong>
                          </div>
                        </div>
                        <div className="settings-meta">
                          <div>
                            <div className="muted small">Realm ID</div>
                            <strong>{qbo?.realm_id ?? "—"}</strong>
                          </div>
                        </div>
                        <div className="settings-meta">
                          <div>
                            <div className="muted small">Last sync</div>
                            <strong>{formatMaybeDate(qbo?.last_sync_at)}</strong>
                          </div>
                          <div>
                            <div className="muted small">Last error</div>
                            <strong>{qbo?.last_error ?? "—"}</strong>
                          </div>
                        </div>
                        <div className="settings-actions">
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={startQboConnect}
                            disabled={!isOwner || qboLoading || !qbo?.oauth_configured}
                            title={!isOwner ? "Owner access required" : undefined}
                          >
                            Connect
                          </button>
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={disconnectQbo}
                            disabled={!isOwner || qboLoading || !qbo?.connected}
                            title={!isOwner ? "Owner access required" : undefined}
                          >
                            Disconnect
                          </button>
                        </div>
                        <div className="muted small">
                          Required: <code>QUICKBOOKS_OAUTH_CLIENT_ID</code>,{" "}
                          <code>QUICKBOOKS_OAUTH_CLIENT_SECRET</code>, <code>QUICKBOOKS_OAUTH_REDIRECT_URI</code>
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>
              </>
            )}

            {!isOwner ? (
              <p className="alert alert-warning">Only Owners can manage integration credentials.</p>
            ) : (
              <>
                {settingsError ? <p className="alert alert-warning">{settingsError}</p> : null}
                {loading ? <p className="muted">Loading integration status…</p> : null}
                <div className="settings-grid">
                  <div className="settings-card">
                    <div className="settings-card-header">
                      <div>
                        <strong>Stripe</strong>
                        <div className="muted small">Payments and billing portal</div>
                      </div>
                      {stripeBadge}
                    </div>
                    <div className="settings-card-body">
                      <div className="settings-meta">
                        <div>
                          <div className="muted small">Account</div>
                          <strong>{stripe?.account ?? "—"}</strong>
                        </div>
                        <div>
                          <div className="muted small">Webhook configured</div>
                          <strong>{stripe?.webhook_configured ? "Yes" : "No"}</strong>
                        </div>
                        <div>
                          <div className="muted small">Last webhook</div>
                          <strong>{formatMaybeDate(stripe?.last_webhook_at)}</strong>
                        </div>
                        <div>
                          <div className="muted small">Health</div>
                          <strong>{stripe?.health ?? "—"}</strong>
                        </div>
                      </div>
                      <div className="settings-meta">
                        <div>
                          <div className="muted small">Card</div>
                          <strong>{capabilityLabel(stripe?.capabilities.card)}</strong>
                        </div>
                        <div>
                          <div className="muted small">Apple Pay</div>
                          <strong>{capabilityLabel(stripe?.capabilities.apple_pay)}</strong>
                        </div>
                        <div>
                          <div className="muted small">Google Pay</div>
                          <strong>{capabilityLabel(stripe?.capabilities.google_pay)}</strong>
                        </div>
                      </div>
                      <div className="settings-actions">
                        <button className="btn btn-ghost" type="button" disabled title="Not implemented">
                          Configure
                        </button>
                        <button className="btn btn-ghost" type="button" disabled title="Not implemented">
                          Reconnect
                        </button>
                        <button className="btn btn-ghost" type="button" disabled title="Not implemented">
                          Disconnect
                        </button>
                      </div>
                      <div className="muted small">
                        Required: <code>STRIPE_SECRET_KEY</code>, <code>STRIPE_WEBHOOK_SECRET</code>
                      </div>
                    </div>
                  </div>

                  <div className="settings-card">
                    <div className="settings-card-header">
                      <div>
                        <strong>Twilio</strong>
                        <div className="muted small">SMS and voice messaging</div>
                      </div>
                      {twilioBadge}
                    </div>
                    <div className="settings-card-body">
                      <div className="settings-meta">
                        <div>
                          <div className="muted small">Account</div>
                          <strong>{twilio?.account ?? "—"}</strong>
                        </div>
                        <div>
                          <div className="muted small">SMS from</div>
                          <strong>{twilio?.sms_from ?? "—"}</strong>
                        </div>
                        <div>
                          <div className="muted small">Call from</div>
                          <strong>{twilio?.call_from ?? "—"}</strong>
                        </div>
                        <div>
                          <div className="muted small">Usage</div>
                          <strong>{twilio?.usage_summary ?? "—"}</strong>
                        </div>
                        <div>
                          <div className="muted small">Health</div>
                          <strong>{twilio?.health ?? "—"}</strong>
                        </div>
                      </div>
                      <div className="settings-actions">
                        <button className="btn btn-ghost" type="button" disabled title="Not implemented">
                          Configure
                        </button>
                        <button className="btn btn-ghost" type="button" disabled title="Not implemented">
                          Reconnect
                        </button>
                        <button className="btn btn-ghost" type="button" disabled title="Not implemented">
                          Disconnect
                        </button>
                      </div>
                      <div className="muted small">
                        Required: <code>TWILIO_ACCOUNT_SID</code>, <code>TWILIO_AUTH_TOKEN</code>,{" "}
                        <code>TWILIO_SMS_FROM</code>
                      </div>
                    </div>
                  </div>

                  <div className="settings-card">
                    <div className="settings-card-header">
                      <div>
                        <strong>Email</strong>
                        <div className="muted small">Outbound email provider</div>
                      </div>
                      {emailBadge}
                    </div>
                    <div className="settings-card-body">
                      <div className="settings-meta">
                        <div>
                          <div className="muted small">Mode</div>
                          <strong>{email?.mode ?? "—"}</strong>
                        </div>
                        <div>
                          <div className="muted small">Sender</div>
                          <strong>{email?.sender ?? "—"}</strong>
                        </div>
                        <div>
                          <div className="muted small">Deliverability</div>
                          <strong>{email?.deliverability ?? "—"}</strong>
                        </div>
                        <div>
                          <div className="muted small">Health</div>
                          <strong>{email?.health ?? "—"}</strong>
                        </div>
                      </div>
                      <div className="settings-actions">
                        <button className="btn btn-ghost" type="button" disabled title="Not implemented">
                          Configure
                        </button>
                        <button className="btn btn-ghost" type="button" disabled title="Not implemented">
                          Reconnect
                        </button>
                        <button className="btn btn-ghost" type="button" disabled title="Not implemented">
                          Disconnect
                        </button>
                      </div>
                      <div className="muted small">
                        Required: <code>EMAIL_MODE</code>, <code>EMAIL_FROM</code>, <code>SENDGRID_API_KEY</code> or{" "}
                        <code>SMTP_HOST</code>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
