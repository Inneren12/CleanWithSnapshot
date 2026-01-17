"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../../lib/featureVisibility";
import { DEFAULT_ORG_TIMEZONE, type BusinessHourWindow, type OrgSettingsResponse } from "../../lib/orgSettings";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const TIMEZONE_OPTIONS = [{ value: "America/Edmonton", label: "America/Edmonton (MST/MDT)" }];
const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "ru", label: "Russian" },
];
const CURRENCY_OPTIONS = [
  { value: "CAD", label: "CAD" },
  { value: "USD", label: "USD" },
];
const BUSINESS_DAYS: { key: string; label: string }[] = [
  { key: "monday", label: "Monday" },
  { key: "tuesday", label: "Tuesday" },
  { key: "wednesday", label: "Wednesday" },
  { key: "thursday", label: "Thursday" },
  { key: "friday", label: "Friday" },
  { key: "saturday", label: "Saturday" },
  { key: "sunday", label: "Sunday" },
];
const DEFAULT_BUSINESS_HOURS: Record<string, BusinessHourWindow> = {
  monday: { enabled: true, start: "08:00", end: "18:00" },
  tuesday: { enabled: true, start: "08:00", end: "18:00" },
  wednesday: { enabled: true, start: "08:00", end: "18:00" },
  thursday: { enabled: true, start: "08:00", end: "18:00" },
  friday: { enabled: true, start: "08:00", end: "18:00" },
  saturday: { enabled: true, start: "09:00", end: "17:00" },
  sunday: { enabled: false, start: "", end: "" },
};
const DEFAULT_HOLIDAYS = [
  "new_years_day",
  "family_day",
  "good_friday",
  "victoria_day",
  "canada_day",
  "labour_day",
  "thanksgiving",
  "remembrance_day",
  "christmas_day",
  "boxing_day",
];
const HOLIDAY_OPTIONS = [
  { id: "new_years_day", label: "New Year's Day" },
  { id: "family_day", label: "Family Day" },
  { id: "good_friday", label: "Good Friday" },
  { id: "victoria_day", label: "Victoria Day" },
  { id: "canada_day", label: "Canada Day" },
  { id: "labour_day", label: "Labour Day" },
  { id: "thanksgiving", label: "Thanksgiving" },
  { id: "remembrance_day", label: "Remembrance Day" },
  { id: "christmas_day", label: "Christmas Day" },
  { id: "boxing_day", label: "Boxing Day" },
];

function normalizeBusinessHours(hours?: Record<string, BusinessHourWindow>) {
  const normalized: Record<string, BusinessHourWindow> = { ...DEFAULT_BUSINESS_HOURS };
  if (!hours) return normalized;
  for (const day of BUSINESS_DAYS) {
    const entry = hours[day.key];
    if (!entry) continue;
    normalized[day.key] = {
      enabled: Boolean(entry.enabled),
      start: entry.start ?? "",
      end: entry.end ?? "",
    };
  }
  return normalized;
}

function normalizeSettings(settings: OrgSettingsResponse): OrgSettingsResponse {
  return {
    ...settings,
    timezone: settings.timezone || DEFAULT_ORG_TIMEZONE,
    currency: settings.currency ?? "CAD",
    language: settings.language ?? "en",
    business_hours: normalizeBusinessHours(settings.business_hours),
    holidays: settings.holidays?.length ? settings.holidays : DEFAULT_HOLIDAYS,
    branding: settings.branding ?? {},
  };
}

export default function OrganizationSettingsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [formState, setFormState] = useState<OrgSettingsResponse | null>(null);
  const [originalState, setOriginalState] = useState<OrgSettingsResponse | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

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
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
      {
        key: "availability-blocks",
        label: "Availability Blocks",
        href: "/admin/settings/availability-blocks",
        featureKey: "module.settings",
      },
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

  const loadOrgSettings = useCallback(async () => {
    if (!username || !password) return;
    setStatusMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/settings/org`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = normalizeSettings((await response.json()) as OrgSettingsResponse);
      setFormState(data);
      setOriginalState(data);
    } else {
      setFormState(null);
      setOriginalState(null);
      setStatusMessage("Failed to load org settings");
    }
  }, [authHeaders, password, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadOrgSettings();
  }, [loadFeatureConfig, loadOrgSettings, loadProfile, loadUiPrefs]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadOrgSettings();
    setStatusMessage("Saved credentials");
  };

  const handleClearCredentials = () => {
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setProfile(null);
    setFeatureConfig(null);
    setUiPrefs(null);
    setSettingsError(null);
    setFormState(null);
    setOriginalState(null);
    setStatusMessage("Cleared credentials");
  };

  const updateBusinessHour = (day: string, updates: Partial<BusinessHourWindow>) => {
    setFormState((prev) => {
      if (!prev) return prev;
      const current = prev.business_hours?.[day] ?? DEFAULT_BUSINESS_HOURS[day];
      return {
        ...prev,
        business_hours: {
          ...prev.business_hours,
          [day]: {
            ...current,
            ...updates,
          },
        },
      };
    });
  };

  const toggleHoliday = (id: string) => {
    setFormState((prev) => {
      if (!prev) return prev;
      const current = new Set(prev.holidays ?? []);
      if (current.has(id)) {
        current.delete(id);
      } else {
        current.add(id);
      }
      return {
        ...prev,
        holidays: Array.from(current),
      };
    });
  };

  const handleCancel = () => {
    setFormState(originalState);
    setStatusMessage("Reverted changes");
    setFormError(null);
  };

  const handleSave = async () => {
    if (!formState || !isOwner) return;
    setFormError(null);
    setStatusMessage(null);
    if (!formState.timezone) {
      setFormError("Timezone is required");
      return;
    }
    if (!formState.currency) {
      setFormError("Currency is required");
      return;
    }
    if (!formState.language) {
      setFormError("Language is required");
      return;
    }
    for (const day of BUSINESS_DAYS) {
      const entry = formState.business_hours?.[day.key];
      if (entry?.enabled && (!entry.start || !entry.end)) {
        setFormError(`Business hours for ${day.label} need a start and end time`);
        return;
      }
    }

    const response = await fetch(`${API_BASE}/v1/admin/settings/org`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({
        timezone: formState.timezone,
        currency: formState.currency,
        language: formState.language,
        business_hours: formState.business_hours,
        holidays: formState.holidays,
        legal_name: formState.legal_name ?? "",
        legal_bn: formState.legal_bn ?? "",
        legal_gst_hst: formState.legal_gst_hst ?? "",
        legal_address: formState.legal_address ?? "",
        legal_phone: formState.legal_phone ?? "",
        legal_email: formState.legal_email ?? "",
        legal_website: formState.legal_website ?? "",
        branding: formState.branding ?? {},
      }),
    });

    if (response.ok) {
      const data = normalizeSettings((await response.json()) as OrgSettingsResponse);
      setFormState(data);
      setOriginalState(data);
      setStatusMessage("Organization settings updated");
    } else {
      setStatusMessage("Failed to update organization settings");
    }
  };

  if (visibilityReady && !pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="org-settings" />
        <div className="admin-card admin-section">
          <h1>Organization Settings</h1>
          <p className="alert alert-warning">Disabled by org settings.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="org-settings" />
      <div className="admin-section">
        <h1>Organization Settings</h1>
        <p className="muted">
          Manage core details like timezone, hours, and holidays. Branding fields are stored but not
          required for MVP.
        </p>
      </div>

      {settingsError ? <p className="alert alert-warning">{settingsError}</p> : null}
      {statusMessage ? <p className="alert alert-info">{statusMessage}</p> : null}
      {formError ? <p className="alert alert-warning">{formError}</p> : null}

      {!profile ? (
        <div className="admin-card">
          <div className="admin-section">
            <h2>Credentials</h2>
            <div className="admin-actions">
              <label>
                Username
                <input value={username} onChange={(event) => setUsername(event.target.value)} />
              </label>
              <label>
                Password
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>
              <button className="primary" onClick={handleSaveCredentials}>
                Save credentials
              </button>
              <button className="ghost" onClick={handleClearCredentials}>
                Clear
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {profile ? (
        <div className="admin-card">
          <div className="admin-section">
            <h2>Access</h2>
            <p>
              Signed in as <strong>{profile.username}</strong> ({profile.role}).
              {!isOwner ? " Only owners can edit settings." : ""}
            </p>
          </div>
        </div>
      ) : null}

      {formState ? (
        <div className="admin-card">
          <div className="admin-section">
            <h2>Core</h2>
            <div className="form-grid">
              <label>
                <span>Timezone</span>
                <select
                  value={formState.timezone}
                  onChange={(event) =>
                    setFormState((prev) => (prev ? { ...prev, timezone: event.target.value } : prev))
                  }
                  disabled={!isOwner}
                >
                  {TIMEZONE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Language</span>
                <select
                  value={formState.language}
                  onChange={(event) =>
                    setFormState((prev) =>
                      prev ? { ...prev, language: event.target.value as OrgSettingsResponse["language"] } : prev
                    )
                  }
                  disabled={!isOwner}
                >
                  {LANGUAGE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Currency</span>
                <select
                  value={formState.currency}
                  onChange={(event) =>
                    setFormState((prev) =>
                      prev ? { ...prev, currency: event.target.value as OrgSettingsResponse["currency"] } : prev
                    )
                  }
                  disabled={!isOwner}
                >
                  {CURRENCY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="admin-section">
            <h2>Company legal</h2>
            <div className="form-grid">
              <label>
                <span>Legal name</span>
                <input
                  value={formState.legal_name ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => (prev ? { ...prev, legal_name: event.target.value } : prev))
                  }
                  disabled={!isOwner}
                />
              </label>
              <label>
                <span>Business number (BN)</span>
                <input
                  value={formState.legal_bn ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => (prev ? { ...prev, legal_bn: event.target.value } : prev))
                  }
                  disabled={!isOwner}
                />
              </label>
              <label>
                <span>GST/HST</span>
                <input
                  value={formState.legal_gst_hst ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => (prev ? { ...prev, legal_gst_hst: event.target.value } : prev))
                  }
                  disabled={!isOwner}
                />
              </label>
              <label className="full">
                <span>Address</span>
                <input
                  value={formState.legal_address ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => (prev ? { ...prev, legal_address: event.target.value } : prev))
                  }
                  disabled={!isOwner}
                />
              </label>
            </div>
          </div>

          <div className="admin-section">
            <h2>Contact</h2>
            <div className="form-grid">
              <label>
                <span>Phone</span>
                <input
                  value={formState.legal_phone ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => (prev ? { ...prev, legal_phone: event.target.value } : prev))
                  }
                  disabled={!isOwner}
                />
              </label>
              <label>
                <span>Email</span>
                <input
                  type="email"
                  value={formState.legal_email ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => (prev ? { ...prev, legal_email: event.target.value } : prev))
                  }
                  disabled={!isOwner}
                />
              </label>
              <label>
                <span>Website</span>
                <input
                  value={formState.legal_website ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => (prev ? { ...prev, legal_website: event.target.value } : prev))
                  }
                  disabled={!isOwner}
                />
              </label>
            </div>
          </div>

          <div className="admin-section">
            <h2>Business hours</h2>
            <div className="settings-tree">
              {BUSINESS_DAYS.map((day) => {
                const entry = formState.business_hours?.[day.key] ?? DEFAULT_BUSINESS_HOURS[day.key];
                return (
                  <div key={day.key} className="settings-row">
                    <div className="settings-info">
                      <strong>{day.label}</strong>
                      <span className="muted">
                        {entry.enabled ? `${entry.start || "—"}–${entry.end || "—"}` : "Closed"}
                      </span>
                    </div>
                    <div className="settings-toggles">
                      <label className="settings-toggle">
                        <span className="muted">Open</span>
                        <input
                          type="checkbox"
                          checked={entry.enabled}
                          onChange={(event) =>
                            updateBusinessHour(day.key, {
                              enabled: event.target.checked,
                              start: event.target.checked ? entry.start || "08:00" : "",
                              end: event.target.checked ? entry.end || "18:00" : "",
                            })
                          }
                          disabled={!isOwner}
                        />
                      </label>
                      <label className="settings-toggle">
                        <span className="muted">Start</span>
                        <input
                          type="time"
                          value={entry.start}
                          onChange={(event) => updateBusinessHour(day.key, { start: event.target.value })}
                          disabled={!isOwner || !entry.enabled}
                        />
                      </label>
                      <label className="settings-toggle">
                        <span className="muted">End</span>
                        <input
                          type="time"
                          value={entry.end}
                          onChange={(event) => updateBusinessHour(day.key, { end: event.target.value })}
                          disabled={!isOwner || !entry.enabled}
                        />
                      </label>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="admin-section">
            <h2>Statutory holidays (Alberta)</h2>
            <div className="settings-tree">
              {HOLIDAY_OPTIONS.map((holiday) => (
                <div key={holiday.id} className="settings-row">
                  <div className="settings-info">
                    <strong>{holiday.label}</strong>
                  </div>
                  <div className="settings-toggles">
                    <label className="settings-toggle">
                      <span className="muted">Observed</span>
                      <input
                        type="checkbox"
                        checked={formState.holidays?.includes(holiday.id)}
                        onChange={() => toggleHoliday(holiday.id)}
                        disabled={!isOwner}
                      />
                    </label>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="admin-section">
            <div className="admin-actions">
              <button className="primary" onClick={handleSave} disabled={!isOwner}>
                Save settings
              </button>
              <button className="ghost" onClick={handleCancel} disabled={!isOwner}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="admin-card admin-section">
          <p className="muted">Load credentials to view organization settings.</p>
        </div>
      )}
    </div>
  );
}
