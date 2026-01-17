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

type ReferralTrigger = "booking_confirmed" | "deposit_paid" | "booking_or_payment";

type ReferralSettings = {
  enabled: boolean;
  referrer_credit_cents: number;
  referee_credit_cents: number;
  credit_trigger: ReferralTrigger;
};

type ReferralSettingsResponse = {
  org_id: string;
  settings: ReferralSettings;
};

type ReferralCreditSummary = {
  credit_id: string;
  recipient_role: "referrer" | "referee";
  credit_cents?: number | null;
  trigger_event?: string | null;
  created_at: string;
};

type ReferralResponse = {
  referral_id: string;
  org_id: string;
  referrer_lead_id: string;
  referrer_name?: string | null;
  referred_lead_id: string;
  referred_name?: string | null;
  referral_code: string;
  status: "pending" | "booked" | "paid";
  booking_id?: string | null;
  payment_id?: string | null;
  created_at: string;
  booked_at?: string | null;
  paid_at?: string | null;
  credits: ReferralCreditSummary[];
};

type ReferralLeaderboardEntry = {
  referrer_lead_id: string;
  referrer_name?: string | null;
  referral_code: string;
  credits_awarded: number;
  credit_cents: number;
  referrals_count: number;
};

type ReferralLeaderboardResponse = {
  entries: ReferralLeaderboardEntry[];
};

type ReferralDraft = {
  referred_lead_id: string;
  referrer_code: string;
};

const defaultReferralDraft: ReferralDraft = {
  referred_lead_id: "",
  referrer_code: "",
};

function formatMoney(value: number) {
  return `$${(value / 100).toFixed(2)}`;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export default function ReferralDashboardPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [referralSettings, setReferralSettings] = useState<ReferralSettings | null>(null);
  const [referralDraft, setReferralDraft] = useState<ReferralDraft>(defaultReferralDraft);
  const [referrals, setReferrals] = useState<ReferralResponse[]>([]);
  const [leaderboard, setLeaderboard] = useState<ReferralLeaderboardEntry[]>([]);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

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
    ? isVisible("marketing.referrals", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const canManage = permissionKeys.includes("settings.manage");
  const isOwner = profile?.role === "owner";

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "notifications", label: "Notifications", href: "/admin/notifications", featureKey: "module.notifications_center" },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "marketing.promo_codes", label: "Promo Codes", href: "/admin/marketing/promo-codes", featureKey: "marketing.promo_codes" },
      { key: "marketing.referrals", label: "Referrals", href: "/admin/marketing/referrals", featureKey: "marketing.referrals" },
      { key: "pricing", label: "Service Types & Pricing", href: "/admin/settings/pricing", featureKey: "pricing.service_types" },
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

  const loadReferrals = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/marketing/referrals`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as ReferralResponse[];
      setReferrals(data);
    } else {
      setSettingsError("Failed to load referrals");
    }
  }, [authHeaders, password, username]);

  const loadLeaderboard = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/marketing/referrals/leaderboard`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as ReferralLeaderboardResponse;
      setLeaderboard(data.entries ?? []);
    } else {
      setSettingsError("Failed to load leaderboard");
    }
  }, [authHeaders, password, username]);

  const loadReferralSettings = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/marketing/referrals/config`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as ReferralSettingsResponse;
      setReferralSettings(data.settings);
    } else {
      setReferralSettings(null);
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
    loadProfile();
    loadFeatureConfig();
    loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (!username || !password) return;
    loadReferrals();
    loadLeaderboard();
    loadReferralSettings();
  }, [loadLeaderboard, loadReferralSettings, loadReferrals, password, username]);

  const handleReferralSettingChange = (field: keyof ReferralSettings, value: string | boolean) => {
    if (!referralSettings) return;
    if (field === "credit_trigger") {
      setReferralSettings({ ...referralSettings, credit_trigger: value as ReferralTrigger });
      return;
    }
    if (field === "enabled") {
      setReferralSettings({ ...referralSettings, enabled: value as boolean });
      return;
    }
    setReferralSettings({
      ...referralSettings,
      [field]: Number(value),
    });
  };

  const handleSaveSettings = async () => {
    if (!referralSettings || !canManage || !isOwner) return;
    setStatusMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/marketing/referrals/config`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
      },
      body: JSON.stringify(referralSettings),
    });
    if (response.ok) {
      const data = (await response.json()) as ReferralSettingsResponse;
      setReferralSettings(data.settings);
      setStatusMessage("Referral settings saved.");
    } else {
      setStatusMessage("Failed to update referral settings.");
    }
  };

  const handleCreateReferral = async () => {
    if (!canManage) return;
    setStatusMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/marketing/referrals`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
      },
      body: JSON.stringify({
        referred_lead_id: referralDraft.referred_lead_id.trim(),
        referrer_code: referralDraft.referrer_code.trim(),
      }),
    });
    if (response.ok) {
      setStatusMessage("Referral linked.");
      setReferralDraft(defaultReferralDraft);
      await Promise.all([loadReferrals(), loadLeaderboard()]);
    } else {
      const detail = await response.json().catch(() => ({}));
      setStatusMessage(detail.detail || "Failed to create referral.");
    }
  };

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="marketing.referrals" />
        <section className="admin-card admin-section">
          <h1>Referral Program</h1>
          <p>You do not have access to this module.</p>
        </section>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="marketing.referrals" />

      <section className="admin-card admin-section">
        <h1>Referral Program</h1>
        <p>Track referred leads, reward credits, and monitor top referrers.</p>
      </section>

      <section className="admin-card admin-section">
        <h2>Access</h2>
        <div className="form-grid">
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
      </section>

      <section className="admin-card admin-section">
        <h2>Program Settings</h2>
        {!referralSettings && <p>Settings are only visible to owners with settings access.</p>}
        {referralSettings && (
          <div className="form-grid">
            <label>
              Program enabled
              <select
                value={referralSettings.enabled ? "true" : "false"}
                onChange={(event) =>
                  handleReferralSettingChange("enabled", event.target.value === "true")
                }
                disabled={!canManage || !isOwner}
              >
                <option value="true">Enabled</option>
                <option value="false">Disabled</option>
              </select>
            </label>
            <label>
              Referrer credit
              <input
                type="number"
                min={0}
                value={referralSettings.referrer_credit_cents}
                onChange={(event) =>
                  handleReferralSettingChange("referrer_credit_cents", event.target.value)
                }
                disabled={!canManage || !isOwner}
              />
            </label>
            <label>
              Referee credit
              <input
                type="number"
                min={0}
                value={referralSettings.referee_credit_cents}
                onChange={(event) =>
                  handleReferralSettingChange("referee_credit_cents", event.target.value)
                }
                disabled={!canManage || !isOwner}
              />
            </label>
            <label>
              Credit trigger
              <select
                value={referralSettings.credit_trigger}
                onChange={(event) =>
                  handleReferralSettingChange("credit_trigger", event.target.value as ReferralTrigger)
                }
                disabled={!canManage || !isOwner}
              >
                <option value="booking_confirmed">Booking confirmed</option>
                <option value="deposit_paid">Deposit paid</option>
                <option value="booking_or_payment">Booking or payment</option>
              </select>
            </label>
          </div>
        )}
        {referralSettings && (
          <button className="admin-button" onClick={handleSaveSettings} disabled={!canManage || !isOwner}>
            Save settings
          </button>
        )}
      </section>

      <section className="admin-card admin-section">
        <h2>Link a referral</h2>
        <p>Manually associate a referred lead with an existing referral code.</p>
        <div className="form-grid">
          <label>
            Referred lead ID
            <input
              type="text"
              value={referralDraft.referred_lead_id}
              onChange={(event) =>
                setReferralDraft((prev) => ({ ...prev, referred_lead_id: event.target.value }))
              }
              placeholder="Lead ID"
            />
          </label>
          <label>
            Referrer code
            <input
              type="text"
              value={referralDraft.referrer_code}
              onChange={(event) =>
                setReferralDraft((prev) => ({ ...prev, referrer_code: event.target.value.toUpperCase() }))
              }
              placeholder="REFCODE"
            />
          </label>
        </div>
        <button className="admin-button" onClick={handleCreateReferral} disabled={!canManage}>
          Create referral
        </button>
      </section>

      <section className="admin-card admin-section">
        <h2>Top Referrers</h2>
        <table className="admin-table">
          <thead>
            <tr>
              <th>Referrer</th>
              <th>Code</th>
              <th>Credits</th>
              <th>Total value</th>
              <th>Referrals</th>
            </tr>
          </thead>
          <tbody>
            {leaderboard.length === 0 && (
              <tr>
                <td colSpan={5}>No referrals recorded yet.</td>
              </tr>
            )}
            {leaderboard.map((entry) => (
              <tr key={entry.referrer_lead_id}>
                <td>{entry.referrer_name ?? "Unknown"}</td>
                <td>{entry.referral_code}</td>
                <td>{entry.credits_awarded}</td>
                <td>{formatMoney(entry.credit_cents)}</td>
                <td>{entry.referrals_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="admin-card admin-section">
        <h2>Referral Activity</h2>
        <table className="admin-table">
          <thead>
            <tr>
              <th>Referrer</th>
              <th>Referred lead</th>
              <th>Status</th>
              <th>Booking</th>
              <th>Payment</th>
              <th>Credits</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {referrals.length === 0 && (
              <tr>
                <td colSpan={7}>No referrals recorded yet.</td>
              </tr>
            )}
            {referrals.map((referral) => (
              <tr key={referral.referral_id}>
                <td>
                  {referral.referrer_name ?? "Unknown"}
                  <div className="muted">{referral.referral_code}</div>
                </td>
                <td>
                  {referral.referred_name ?? referral.referred_lead_id}
                  <div className="muted">{referral.referred_lead_id}</div>
                </td>
                <td>{referral.status}</td>
                <td>{referral.booking_id ?? "—"}</td>
                <td>{referral.payment_id ?? "—"}</td>
                <td>
                  {referral.credits.length > 0
                    ? referral.credits.map((credit) => (
                        <div key={credit.credit_id}>
                          {credit.recipient_role}: {credit.credit_cents ? formatMoney(credit.credit_cents) : "—"}
                        </div>
                      ))
                    : "—"}
                </td>
                <td>{formatDate(referral.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {statusMessage && (
        <section className="admin-card admin-section">
          <p>{statusMessage}</p>
        </section>
      )}
      {settingsError && (
        <section className="admin-card admin-section">
          <p>{settingsError}</p>
        </section>
      )}
    </div>
  );
}
