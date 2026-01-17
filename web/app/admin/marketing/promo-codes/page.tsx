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

type PromoDiscountType = "percent" | "amount" | "free_addon";

type PromoCode = {
  promo_code_id: string;
  org_id: string;
  code: string;
  name: string;
  description?: string | null;
  discount_type: PromoDiscountType;
  percent_off?: number | null;
  amount_cents?: number | null;
  free_addon_id?: number | null;
  valid_from?: string | null;
  valid_until?: string | null;
  first_time_only: boolean;
  min_order_cents?: number | null;
  one_per_customer: boolean;
  usage_limit?: number | null;
  active: boolean;
  created_at: string;
  updated_at: string;
};

type PromoCodeDraft = {
  code: string;
  name: string;
  description: string;
  discount_type: PromoDiscountType;
  percent_off: string;
  amount_cents: string;
  free_addon_id: string;
  valid_from: string;
  valid_until: string;
  first_time_only: boolean;
  min_order_cents: string;
  one_per_customer: boolean;
  usage_limit: string;
  active: boolean;
};

const defaultPromoDraft: PromoCodeDraft = {
  code: "",
  name: "",
  description: "",
  discount_type: "percent",
  percent_off: "10",
  amount_cents: "",
  free_addon_id: "",
  valid_from: "",
  valid_until: "",
  first_time_only: false,
  min_order_cents: "",
  one_per_customer: false,
  usage_limit: "",
  active: true,
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

function parseOptionalInt(value: string) {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return null;
  return parsed;
}

function formatDiscount(promo: PromoCode) {
  if (promo.discount_type === "percent") return `${promo.percent_off ?? 0}% off`;
  if (promo.discount_type === "amount") return `$${((promo.amount_cents ?? 0) / 100).toFixed(2)} off`;
  return `Free addon #${promo.free_addon_id ?? "—"}`;
}

function formatWindow(promo: PromoCode) {
  if (!promo.valid_from && !promo.valid_until) return "Always";
  const formatter = new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeStyle: "short" });
  const from = promo.valid_from ? formatter.format(new Date(promo.valid_from)) : "Now";
  const until = promo.valid_until ? formatter.format(new Date(promo.valid_until)) : "No expiry";
  return `${from} → ${until}`;
}

export default function PromoCodesPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [promoCodes, setPromoCodes] = useState<PromoCode[]>([]);
  const [promoDraft, setPromoDraft] = useState<PromoCodeDraft>(defaultPromoDraft);
  const [editingPromoId, setEditingPromoId] = useState<string | null>(null);
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
    ? isVisible("marketing.promo_codes", permissionKeys, featureOverrides, hiddenKeys)
    : true;
  const canManage = permissionKeys.includes("settings.manage");

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "notifications", label: "Notifications", href: "/admin/notifications", featureKey: "module.notifications_center" },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "marketing", label: "Promo Codes", href: "/admin/marketing/promo-codes", featureKey: "marketing.promo_codes" },
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

  const loadPromoCodes = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/marketing/promo-codes`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as PromoCode[];
      setPromoCodes(data);
    } else {
      setSettingsError("Failed to load promo codes");
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
    void loadPromoCodes();
  }, [loadFeatureConfig, loadProfile, loadPromoCodes, loadUiPrefs]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadPromoCodes();
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
    setPromoCodes([]);
    setSettingsError(null);
    setStatusMessage("Cleared credentials");
  };

  const openCreatePromo = () => {
    setEditingPromoId(null);
    setPromoDraft(defaultPromoDraft);
  };

  const openEditPromo = (promo: PromoCode) => {
    setEditingPromoId(promo.promo_code_id);
    setPromoDraft({
      code: promo.code,
      name: promo.name,
      description: promo.description ?? "",
      discount_type: promo.discount_type,
      percent_off: promo.percent_off ? String(promo.percent_off) : "",
      amount_cents: promo.amount_cents ? String(promo.amount_cents) : "",
      free_addon_id: promo.free_addon_id ? String(promo.free_addon_id) : "",
      valid_from: toDateTimeInput(promo.valid_from),
      valid_until: toDateTimeInput(promo.valid_until),
      first_time_only: promo.first_time_only,
      min_order_cents: promo.min_order_cents ? String(promo.min_order_cents) : "",
      one_per_customer: promo.one_per_customer,
      usage_limit: promo.usage_limit ? String(promo.usage_limit) : "",
      active: promo.active,
    });
  };

  const buildPayload = () => {
    const percentOff = promoDraft.discount_type === "percent" ? parseOptionalInt(promoDraft.percent_off) : null;
    const amountCents = promoDraft.discount_type === "amount" ? parseOptionalInt(promoDraft.amount_cents) : null;
    const freeAddonId = promoDraft.discount_type === "free_addon" ? parseOptionalInt(promoDraft.free_addon_id) : null;
    return {
      code: promoDraft.code,
      name: promoDraft.name,
      description: promoDraft.description || null,
      discount_type: promoDraft.discount_type,
      percent_off: percentOff,
      amount_cents: amountCents,
      free_addon_id: freeAddonId,
      valid_from: fromDateTimeInput(promoDraft.valid_from),
      valid_until: fromDateTimeInput(promoDraft.valid_until),
      first_time_only: promoDraft.first_time_only,
      min_order_cents: parseOptionalInt(promoDraft.min_order_cents),
      one_per_customer: promoDraft.one_per_customer,
      usage_limit: parseOptionalInt(promoDraft.usage_limit),
      active: promoDraft.active,
    };
  };

  const savePromoCode = async () => {
    if (!canManage) return;
    const response = await fetch(
      editingPromoId
        ? `${API_BASE}/v1/admin/marketing/promo-codes/${editingPromoId}`
        : `${API_BASE}/v1/admin/marketing/promo-codes`,
      {
        method: editingPromoId ? "PATCH" : "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload()),
      }
    );
    if (response.ok) {
      setStatusMessage(editingPromoId ? "Updated promo code" : "Created promo code");
      setEditingPromoId(null);
      setPromoDraft(defaultPromoDraft);
      void loadPromoCodes();
    } else {
      setStatusMessage("Failed to save promo code");
    }
  };

  const deletePromoCode = async (promoId: string) => {
    if (!canManage) return;
    const confirmed = window.confirm("Delete this promo code?");
    if (!confirmed) return;
    const response = await fetch(`${API_BASE}/v1/admin/marketing/promo-codes/${promoId}`, {
      method: "DELETE",
      headers: authHeaders,
    });
    if (response.ok) {
      setStatusMessage("Deleted promo code");
      void loadPromoCodes();
    } else {
      setStatusMessage("Failed to delete promo code");
    }
  };

  if (visibilityReady && !pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="marketing" />
        <div className="admin-card admin-section">
          <h1>Promo codes</h1>
          <p className="alert alert-warning">Disabled by org settings.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="marketing" />
      <div className="admin-section">
        <h1>Promo codes</h1>
        <p className="muted">Create and manage discounts, free add-ons, and redemption rules.</p>
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
        {!canManage && profile ? (
          <p className="alert alert-warning">Read-only role: settings.manage permission required.</p>
        ) : null}
      </div>

      <div className="admin-card admin-section">
        <div className="section-heading">
          <h2>Promo catalog</h2>
          <p className="muted">Use percent, fixed amount, or free add-on promotions with guardrails.</p>
        </div>

        <div className="settings-actions">
          <button className="btn btn-primary" type="button" onClick={openCreatePromo} disabled={!canManage}>
            Add promo code
          </button>
        </div>

        <div className="form-grid">
          <label>
            <span>Code</span>
            <input
              value={promoDraft.code}
              onChange={(event) => setPromoDraft((current) => ({ ...current, code: event.target.value }))}
              disabled={!canManage}
            />
          </label>
          <label>
            <span>Name</span>
            <input
              value={promoDraft.name}
              onChange={(event) => setPromoDraft((current) => ({ ...current, name: event.target.value }))}
              disabled={!canManage}
            />
          </label>
          <label>
            <span>Description</span>
            <input
              value={promoDraft.description}
              onChange={(event) => setPromoDraft((current) => ({ ...current, description: event.target.value }))}
              disabled={!canManage}
            />
          </label>
          <label>
            <span>Discount type</span>
            <select
              value={promoDraft.discount_type}
              onChange={(event) =>
                setPromoDraft((current) => ({
                  ...current,
                  discount_type: event.target.value as PromoDiscountType,
                }))
              }
              disabled={!canManage}
            >
              <option value="percent">Percent off</option>
              <option value="amount">Fixed amount</option>
              <option value="free_addon">Free add-on</option>
            </select>
          </label>
          {promoDraft.discount_type === "percent" ? (
            <label>
              <span>Percent off</span>
              <input
                type="number"
                min={1}
                max={100}
                value={promoDraft.percent_off}
                onChange={(event) => setPromoDraft((current) => ({ ...current, percent_off: event.target.value }))}
                disabled={!canManage}
              />
            </label>
          ) : null}
          {promoDraft.discount_type === "amount" ? (
            <label>
              <span>Amount off (cents)</span>
              <input
                type="number"
                min={0}
                value={promoDraft.amount_cents}
                onChange={(event) => setPromoDraft((current) => ({ ...current, amount_cents: event.target.value }))}
                disabled={!canManage}
              />
            </label>
          ) : null}
          {promoDraft.discount_type === "free_addon" ? (
            <label>
              <span>Free add-on ID</span>
              <input
                type="number"
                min={1}
                value={promoDraft.free_addon_id}
                onChange={(event) => setPromoDraft((current) => ({ ...current, free_addon_id: event.target.value }))}
                disabled={!canManage}
              />
            </label>
          ) : null}
          <label>
            <span>Valid from</span>
            <input
              type="datetime-local"
              value={promoDraft.valid_from}
              onChange={(event) => setPromoDraft((current) => ({ ...current, valid_from: event.target.value }))}
              disabled={!canManage}
            />
          </label>
          <label>
            <span>Valid until</span>
            <input
              type="datetime-local"
              value={promoDraft.valid_until}
              onChange={(event) => setPromoDraft((current) => ({ ...current, valid_until: event.target.value }))}
              disabled={!canManage}
            />
          </label>
          <label>
            <span>Minimum order (cents)</span>
            <input
              type="number"
              min={0}
              value={promoDraft.min_order_cents}
              onChange={(event) => setPromoDraft((current) => ({ ...current, min_order_cents: event.target.value }))}
              disabled={!canManage}
            />
          </label>
          <label>
            <span>Usage limit</span>
            <input
              type="number"
              min={1}
              value={promoDraft.usage_limit}
              onChange={(event) => setPromoDraft((current) => ({ ...current, usage_limit: event.target.value }))}
              disabled={!canManage}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={promoDraft.first_time_only}
              onChange={(event) => setPromoDraft((current) => ({ ...current, first_time_only: event.target.checked }))}
              disabled={!canManage}
            />
            <span>First-time customer only</span>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={promoDraft.one_per_customer}
              onChange={(event) => setPromoDraft((current) => ({ ...current, one_per_customer: event.target.checked }))}
              disabled={!canManage}
            />
            <span>One per customer</span>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={promoDraft.active}
              onChange={(event) => setPromoDraft((current) => ({ ...current, active: event.target.checked }))}
              disabled={!canManage}
            />
            <span>Active</span>
          </label>
        </div>

        <div className="admin-actions">
          <button className="btn btn-primary" type="button" onClick={savePromoCode} disabled={!canManage}>
            {editingPromoId ? "Save changes" : "Create promo"}
          </button>
          {editingPromoId ? (
            <button className="btn btn-ghost" type="button" onClick={openCreatePromo} disabled={!canManage}>
              Cancel
            </button>
          ) : null}
        </div>
      </div>

      <div className="admin-card admin-section">
        <h2>Existing promo codes</h2>
        {promoCodes.length === 0 ? <p className="muted">No promo codes yet.</p> : null}
        {promoCodes.length ? (
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
                  <th>Discount</th>
                  <th>Window</th>
                  <th>Restrictions</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {promoCodes.map((promo) => (
                  <tr key={promo.promo_code_id}>
                    <td>{promo.code}</td>
                    <td>{promo.name}</td>
                    <td>{formatDiscount(promo)}</td>
                    <td>{formatWindow(promo)}</td>
                    <td>
                      {promo.first_time_only ? "First-time" : "Any customer"}
                      {promo.one_per_customer ? ", one per customer" : ""}
                      {promo.min_order_cents ? `, min $${(promo.min_order_cents / 100).toFixed(2)}` : ""}
                      {promo.usage_limit ? `, limit ${promo.usage_limit}` : ""}
                    </td>
                    <td>{promo.active ? "Active" : "Paused"}</td>
                    <td>
                      <div className="admin-actions">
                        <button className="btn btn-ghost" type="button" onClick={() => openEditPromo(promo)}>
                          Edit
                        </button>
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => deletePromoCode(promo.promo_code_id)}
                          disabled={!canManage}
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
      </div>
    </div>
  );
}
