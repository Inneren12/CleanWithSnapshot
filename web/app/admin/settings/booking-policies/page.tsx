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

type DepositPolicy = {
  enabled: boolean;
  percent: number;
  minimum_cents?: number | null;
  due_days: number;
  notes?: string | null;
};

type CancellationPolicy = {
  window_hours: number;
  refund_percent: number;
  fee_cents: number;
  notes?: string | null;
};

type ReschedulePolicy = {
  allowed: boolean;
  notice_hours: number;
  fee_cents: number;
  max_reschedules: number;
};

type PaymentTermsPolicy = {
  due_days: number;
  accepted_methods: string[];
  notes?: string | null;
};

type SchedulingPolicy = {
  slot_duration_minutes: number;
  buffer_minutes: number;
  lead_time_hours: number;
  max_bookings_per_day?: number | null;
};

type BookingPoliciesResponse = {
  org_id: string;
  deposit: DepositPolicy;
  cancellation: CancellationPolicy;
  reschedule: ReschedulePolicy;
  payment_terms: PaymentTermsPolicy;
  scheduling: SchedulingPolicy;
};

function centsFromInput(value: string): number {
  const parsed = Number.parseFloat(value);
  if (Number.isNaN(parsed)) return 0;
  return Math.round(parsed * 100);
}

function dollarsFromCents(value: number | null | undefined): string {
  return ((value ?? 0) / 100).toFixed(2);
}

export default function BookingPoliciesPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [policies, setPolicies] = useState<BookingPoliciesResponse | null>(null);
  const [draft, setDraft] = useState<BookingPoliciesResponse | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

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
    ? isVisible("pricing.booking_policies", permissionKeys, featureOverrides, hiddenKeys)
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
      {
        key: "availability-blocks",
        label: "Availability Blocks",
        href: "/admin/settings/availability-blocks",
        featureKey: "module.settings",
      },
      { key: "pricing", label: "Service Types & Pricing", href: "/admin/settings/pricing", featureKey: "pricing.service_types" },
      { key: "policies", label: "Booking Policies", href: "/admin/settings/booking-policies", featureKey: "pricing.booking_policies" },
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
    const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
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

  const loadPolicies = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/booking-policies`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as BookingPoliciesResponse;
      setDraft(data);
    } else {
      setSettingsError("Failed to load booking policies");
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
    void loadPolicies();
  }, [loadFeatureConfig, loadPolicies, loadProfile, loadUiPrefs]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadPolicies();
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
    setDraft(null);
    setSettingsError(null);
    setStatusMessage("Cleared credentials");
  };

  const updateDraft = (updates: Partial<BookingPoliciesResponse>) => {
    setDraft((current) => (current ? { ...current, ...updates } : current));
  };

  const validateDraft = () => {
    if (!draft) return null;
    if (draft.deposit.percent < 0 || draft.deposit.percent > 1) return "Deposit percent must be between 0 and 1.";
    if (draft.cancellation.refund_percent < 0 || draft.cancellation.refund_percent > 1) {
      return "Refund percent must be between 0 and 1.";
    }
    if (draft.scheduling.slot_duration_minutes < 5) return "Slot duration must be at least 5 minutes.";
    return null;
  };

  const savePolicies = async () => {
    if (!isOwner || !draft) return;
    const error = validateDraft();
    if (error) {
      setStatusMessage(error);
      return;
    }
    const payload = {
      deposit: draft.deposit,
      cancellation: draft.cancellation,
      reschedule: draft.reschedule,
      payment_terms: draft.payment_terms,
      scheduling: draft.scheduling,
    };
    const response = await fetch(`${API_BASE}/v1/admin/booking-policies`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      const data = (await response.json()) as BookingPoliciesResponse;
      setPolicies(data);
      setDraft(data);
      setStatusMessage("Booking policies updated");
    } else {
      setStatusMessage("Failed to update booking policies");
    }
  };

  if (visibilityReady && !pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="policies" />
        <div className="admin-card admin-section">
          <h1>Booking Policies</h1>
          <p className="alert alert-warning">Disabled by org settings.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="policies" />
      <div className="admin-section">
        <h1>Booking Policies</h1>
        <p className="muted">Define deposit, cancellation, reschedule, and scheduling rules.</p>
      </div>

      {settingsError ? <p className="alert alert-warning">{settingsError}</p> : null}
      {statusMessage ? <p className="alert alert-info">{statusMessage}</p> : null}

      <div className="admin-card admin-section">
        <h2>Credentials</h2>
        <div className="admin-actions">
          <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button className="btn btn-primary" type="button" onClick={handleSaveCredentials}>
            Save
          </button>
          <button className="btn btn-ghost" type="button" onClick={handleClearCredentials}>
            Clear
          </button>
        </div>
        {!isOwner && profile ? (
          <p className="alert alert-warning">Read-only role: only Owners can edit policy settings.</p>
        ) : null}
      </div>

      <div className="admin-card admin-section">
        <div className="section-heading">
          <h2>Policy settings</h2>
          <p className="muted">These rules are stored for future pricing and scheduling workflows.</p>
        </div>

        {draft ? (
          <div className="settings-form">
            <div className="policy-grid">
              <div className="policy-card">
                <h3>Deposit policy</h3>
                <label>
                  <span>Enabled</span>
                  <select
                    value={draft.deposit.enabled ? "enabled" : "disabled"}
                    onChange={(event) =>
                      updateDraft({ deposit: { ...draft.deposit, enabled: event.target.value === "enabled" } })
                    }
                    disabled={!isOwner}
                  >
                    <option value="enabled">Enabled</option>
                    <option value="disabled">Disabled</option>
                  </select>
                </label>
                <label>
                  <span>Percent</span>
                  <input
                    type="number"
                    step="0.01"
                    value={(draft.deposit.percent * 100).toFixed(2)}
                    onChange={(event) =>
                      updateDraft({
                        deposit: { ...draft.deposit, percent: Number(event.target.value || 0) / 100 },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Minimum (CAD)</span>
                  <input
                    type="number"
                    step="0.01"
                    value={dollarsFromCents(draft.deposit.minimum_cents)}
                    onChange={(event) =>
                      updateDraft({
                        deposit: {
                          ...draft.deposit,
                          minimum_cents: centsFromInput(event.target.value),
                        },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Due days</span>
                  <input
                    type="number"
                    min={0}
                    value={draft.deposit.due_days}
                    onChange={(event) =>
                      updateDraft({
                        deposit: { ...draft.deposit, due_days: Number(event.target.value || 0) },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
              </div>

              <div className="policy-card">
                <h3>Cancellation policy</h3>
                <label>
                  <span>Refund window (hours)</span>
                  <input
                    type="number"
                    min={0}
                    value={draft.cancellation.window_hours}
                    onChange={(event) =>
                      updateDraft({
                        cancellation: { ...draft.cancellation, window_hours: Number(event.target.value || 0) },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Refund percent</span>
                  <input
                    type="number"
                    step="0.01"
                    value={(draft.cancellation.refund_percent * 100).toFixed(2)}
                    onChange={(event) =>
                      updateDraft({
                        cancellation: {
                          ...draft.cancellation,
                          refund_percent: Number(event.target.value || 0) / 100,
                        },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Fee (CAD)</span>
                  <input
                    type="number"
                    step="0.01"
                    value={dollarsFromCents(draft.cancellation.fee_cents)}
                    onChange={(event) =>
                      updateDraft({
                        cancellation: { ...draft.cancellation, fee_cents: centsFromInput(event.target.value) },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Notes</span>
                  <input
                    value={draft.cancellation.notes ?? ""}
                    onChange={(event) =>
                      updateDraft({ cancellation: { ...draft.cancellation, notes: event.target.value } })
                    }
                    disabled={!isOwner}
                  />
                </label>
              </div>

              <div className="policy-card">
                <h3>Reschedule policy</h3>
                <label>
                  <span>Allowed</span>
                  <select
                    value={draft.reschedule.allowed ? "allowed" : "blocked"}
                    onChange={(event) =>
                      updateDraft({
                        reschedule: { ...draft.reschedule, allowed: event.target.value === "allowed" },
                      })
                    }
                    disabled={!isOwner}
                  >
                    <option value="allowed">Allowed</option>
                    <option value="blocked">Blocked</option>
                  </select>
                </label>
                <label>
                  <span>Notice (hours)</span>
                  <input
                    type="number"
                    min={0}
                    value={draft.reschedule.notice_hours}
                    onChange={(event) =>
                      updateDraft({
                        reschedule: { ...draft.reschedule, notice_hours: Number(event.target.value || 0) },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Fee (CAD)</span>
                  <input
                    type="number"
                    step="0.01"
                    value={dollarsFromCents(draft.reschedule.fee_cents)}
                    onChange={(event) =>
                      updateDraft({
                        reschedule: { ...draft.reschedule, fee_cents: centsFromInput(event.target.value) },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Max reschedules</span>
                  <input
                    type="number"
                    min={0}
                    value={draft.reschedule.max_reschedules}
                    onChange={(event) =>
                      updateDraft({
                        reschedule: { ...draft.reschedule, max_reschedules: Number(event.target.value || 0) },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
              </div>

              <div className="policy-card">
                <h3>Payment terms</h3>
                <label>
                  <span>Due days</span>
                  <input
                    type="number"
                    min={0}
                    value={draft.payment_terms.due_days}
                    onChange={(event) =>
                      updateDraft({
                        payment_terms: {
                          ...draft.payment_terms,
                          due_days: Number(event.target.value || 0),
                        },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Accepted methods (comma separated)</span>
                  <input
                    value={draft.payment_terms.accepted_methods.join(", ")}
                    onChange={(event) =>
                      updateDraft({
                        payment_terms: {
                          ...draft.payment_terms,
                          accepted_methods: event.target.value
                            .split(",")
                            .map((value) => value.trim())
                            .filter(Boolean),
                        },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Notes</span>
                  <input
                    value={draft.payment_terms.notes ?? ""}
                    onChange={(event) =>
                      updateDraft({
                        payment_terms: { ...draft.payment_terms, notes: event.target.value },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
              </div>

              <div className="policy-card">
                <h3>Scheduling</h3>
                <label>
                  <span>Slot duration (minutes)</span>
                  <input
                    type="number"
                    min={5}
                    value={draft.scheduling.slot_duration_minutes}
                    onChange={(event) =>
                      updateDraft({
                        scheduling: {
                          ...draft.scheduling,
                          slot_duration_minutes: Number(event.target.value || 0),
                        },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Buffer (minutes)</span>
                  <input
                    type="number"
                    min={0}
                    value={draft.scheduling.buffer_minutes}
                    onChange={(event) =>
                      updateDraft({
                        scheduling: { ...draft.scheduling, buffer_minutes: Number(event.target.value || 0) },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Lead time (hours)</span>
                  <input
                    type="number"
                    min={0}
                    value={draft.scheduling.lead_time_hours}
                    onChange={(event) =>
                      updateDraft({
                        scheduling: { ...draft.scheduling, lead_time_hours: Number(event.target.value || 0) },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
                <label>
                  <span>Max bookings per day</span>
                  <input
                    type="number"
                    min={0}
                    value={draft.scheduling.max_bookings_per_day ?? 0}
                    onChange={(event) =>
                      updateDraft({
                        scheduling: {
                          ...draft.scheduling,
                          max_bookings_per_day: Number(event.target.value || 0),
                        },
                      })
                    }
                    disabled={!isOwner}
                  />
                </label>
              </div>
            </div>

            <div className="settings-actions">
              <button className="btn btn-primary" type="button" onClick={() => void savePolicies()} disabled={!isOwner}>
                Save booking policies
              </button>
              {!isOwner ? <span className="muted">Only Owners can save changes.</span> : null}
            </div>
          </div>
        ) : (
          <p className="muted">Load credentials to view booking policies.</p>
        )}
      </div>
    </div>
  );
}
