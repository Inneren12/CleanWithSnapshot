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

type ServiceAddon = {
  addon_id: number;
  service_type_id: number;
  name: string;
  price_cents: number;
  active: boolean;
};

type ServiceType = {
  service_type_id: number;
  name: string;
  description?: string | null;
  active: boolean;
  default_duration_minutes: number;
  pricing_model: "flat" | "hourly";
  base_price_cents: number;
  hourly_rate_cents: number;
  currency: string;
  addons: ServiceAddon[];
};

type PricingAdjustment = {
  label: string;
  kind: "percent" | "flat";
  percent?: number | null;
  amount_cents?: number | null;
};

type PricingSettingsResponse = {
  org_id: string;
  gst_rate: number;
  discounts: PricingAdjustment[];
  surcharges: PricingAdjustment[];
  promo_enabled: boolean;
};

type ServiceTypeDraft = Omit<ServiceType, "service_type_id" | "addons">;

type AddonDraft = {
  name: string;
  price_cents: number;
  active: boolean;
};

const defaultServiceDraft: ServiceTypeDraft = {
  name: "",
  description: "",
  active: true,
  default_duration_minutes: 180,
  pricing_model: "flat",
  base_price_cents: 0,
  hourly_rate_cents: 0,
  currency: "CAD",
};

const defaultAddonDraft: AddonDraft = {
  name: "",
  price_cents: 0,
  active: true,
};

function centsFromInput(value: string): number {
  const parsed = Number.parseFloat(value);
  if (Number.isNaN(parsed)) return 0;
  return Math.round(parsed * 100);
}

function dollarsFromCents(value: number): string {
  return (value / 100).toFixed(2);
}

function formatCurrency(cents: number, currency: string): string {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

function percentFromRate(rate: number): string {
  return (rate * 100).toFixed(2);
}

export default function ServiceTypesPricingPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [serviceTypes, setServiceTypes] = useState<ServiceType[]>([]);
  const [pricingDraft, setPricingDraft] = useState<PricingSettingsResponse | null>(null);
  const [editingServiceId, setEditingServiceId] = useState<number | null>(null);
  const [serviceDraft, setServiceDraft] = useState<ServiceTypeDraft>(defaultServiceDraft);
  const [addonDraft, setAddonDraft] = useState<AddonDraft>(defaultAddonDraft);
  const [addonServiceId, setAddonServiceId] = useState<number | null>(null);
  const [editingAddonId, setEditingAddonId] = useState<number | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const isOwner = profile?.role === "owner";
  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const pageVisible = visibilityReady
    ? isVisible("pricing.service_types", profile?.role, featureOverrides, hiddenKeys)
    : true;

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "pricing", label: "Service Types & Pricing", href: "/admin/settings/pricing", featureKey: "pricing.service_types" },
      { key: "policies", label: "Booking Policies", href: "/admin/settings/booking-policies", featureKey: "pricing.booking_policies" },
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "api.settings" },
    ];
    return candidates
      .filter((entry) => isVisible(entry.featureKey, profile.role, featureOverrides, hiddenKeys))
      .map(({ featureKey, ...link }) => link);
  }, [featureOverrides, hiddenKeys, profile, visibilityReady]);

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

  const loadServiceTypes = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/service-types`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as ServiceType[];
      setServiceTypes(data);
    } else {
      setSettingsError("Failed to load service types");
    }
  }, [authHeaders, password, username]);

  const loadPricingSettings = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    const response = await fetch(`${API_BASE}/v1/admin/pricing-settings`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as PricingSettingsResponse;
      setPricingDraft(data);
    } else {
      setSettingsError("Failed to load pricing settings");
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
    void loadServiceTypes();
    void loadPricingSettings();
  }, [loadFeatureConfig, loadPricingSettings, loadProfile, loadServiceTypes, loadUiPrefs]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadServiceTypes();
    void loadPricingSettings();
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
    setServiceTypes([]);
    setPricingDraft(null);
    setSettingsError(null);
    setStatusMessage("Cleared credentials");
  };

  const openCreateService = () => {
    setEditingServiceId(null);
    setServiceDraft(defaultServiceDraft);
  };

  const openEditService = (serviceType: ServiceType) => {
    setEditingServiceId(serviceType.service_type_id);
    setServiceDraft({
      name: serviceType.name,
      description: serviceType.description ?? "",
      active: serviceType.active,
      default_duration_minutes: serviceType.default_duration_minutes,
      pricing_model: serviceType.pricing_model,
      base_price_cents: serviceType.base_price_cents,
      hourly_rate_cents: serviceType.hourly_rate_cents,
      currency: serviceType.currency,
    });
  };

  const saveServiceType = async () => {
    if (!isOwner) return;
    const payload = { ...serviceDraft };
    const response = await fetch(
      editingServiceId
        ? `${API_BASE}/v1/admin/service-types/${editingServiceId}`
        : `${API_BASE}/v1/admin/service-types`,
      {
        method: editingServiceId ? "PATCH" : "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    );
    if (response.ok) {
      setStatusMessage(editingServiceId ? "Updated service type" : "Created service type");
      setEditingServiceId(null);
      setServiceDraft(defaultServiceDraft);
      await loadServiceTypes();
    } else {
      setStatusMessage("Failed to save service type");
    }
  };

  const deleteServiceType = async (serviceTypeId: number) => {
    if (!isOwner) return;
    const confirmed = window.confirm("Delete this service type?");
    if (!confirmed) return;
    const response = await fetch(`${API_BASE}/v1/admin/service-types/${serviceTypeId}`, {
      method: "DELETE",
      headers: authHeaders,
    });
    if (response.ok) {
      setStatusMessage("Service type deleted");
      await loadServiceTypes();
    } else {
      setStatusMessage("Failed to delete service type");
    }
  };

  const startAddAddon = (serviceTypeId: number) => {
    setAddonServiceId(serviceTypeId);
    setEditingAddonId(null);
    setAddonDraft(defaultAddonDraft);
  };

  const startEditAddon = (addon: ServiceAddon) => {
    setAddonServiceId(addon.service_type_id);
    setEditingAddonId(addon.addon_id);
    setAddonDraft({
      name: addon.name,
      price_cents: addon.price_cents,
      active: addon.active,
    });
  };

  const cancelAddonEdit = () => {
    setAddonServiceId(null);
    setEditingAddonId(null);
    setAddonDraft(defaultAddonDraft);
  };

  const saveAddon = async () => {
    if (!isOwner || addonServiceId == null) return;
    const response = await fetch(
      editingAddonId
        ? `${API_BASE}/v1/admin/service-addons/${editingAddonId}`
        : `${API_BASE}/v1/admin/service-types/${addonServiceId}/addons`,
      {
        method: editingAddonId ? "PATCH" : "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify(addonDraft),
      }
    );
    if (response.ok) {
      setStatusMessage(editingAddonId ? "Addon updated" : "Addon added");
      cancelAddonEdit();
      await loadServiceTypes();
    } else {
      setStatusMessage("Failed to save add-on");
    }
  };

  const deleteAddon = async (addonId: number) => {
    if (!isOwner) return;
    const confirmed = window.confirm("Delete this add-on?");
    if (!confirmed) return;
    const response = await fetch(`${API_BASE}/v1/admin/service-addons/${addonId}`, {
      method: "DELETE",
      headers: authHeaders,
    });
    if (response.ok) {
      setStatusMessage("Add-on deleted");
      await loadServiceTypes();
    } else {
      setStatusMessage("Failed to delete add-on");
    }
  };

  const updatePricingDraft = (updates: Partial<PricingSettingsResponse>) => {
    setPricingDraft((current) => (current ? { ...current, ...updates } : current));
  };

  const updateAdjustment = (
    kind: "discounts" | "surcharges",
    index: number,
    updates: Partial<PricingAdjustment>
  ) => {
    setPricingDraft((current) => {
      if (!current) return current;
      const updated = [...current[kind]];
      updated[index] = { ...updated[index], ...updates };
      return { ...current, [kind]: updated };
    });
  };

  const addAdjustment = (kind: "discounts" | "surcharges") => {
    setPricingDraft((current) => {
      if (!current) return current;
      return {
        ...current,
        [kind]: [
          ...current[kind],
          { label: "", kind: "percent", percent: 0.0, amount_cents: null },
        ],
      };
    });
  };

  const removeAdjustment = (kind: "discounts" | "surcharges", index: number) => {
    setPricingDraft((current) => {
      if (!current) return current;
      const updated = current[kind].filter((_, idx) => idx !== index);
      return { ...current, [kind]: updated };
    });
  };

  const savePricingSettings = async () => {
    if (!isOwner || !pricingDraft) return;
    const payload = {
      gst_rate: pricingDraft.gst_rate,
      discounts: pricingDraft.discounts,
      surcharges: pricingDraft.surcharges,
      promo_enabled: pricingDraft.promo_enabled,
    };
    const response = await fetch(`${API_BASE}/v1/admin/pricing-settings`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      const data = (await response.json()) as PricingSettingsResponse;
      setPricingDraft(data);
      setStatusMessage("Pricing settings updated");
    } else {
      setStatusMessage("Failed to update pricing settings");
    }
  };

  if (visibilityReady && !pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="pricing" />
        <div className="admin-card admin-section">
          <h1>Service Types & Pricing</h1>
          <p className="alert alert-warning">Disabled by org settings.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="pricing" />
      <div className="admin-section">
        <h1>Service Types & Pricing</h1>
        <p className="muted">Define service catalog entries, add-ons, and tax/discount rules.</p>
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
          <p className="alert alert-warning">Read-only role: only Owners can edit pricing settings.</p>
        ) : null}
      </div>

      <div className="admin-card admin-section">
        <div className="section-heading">
          <h2>Service catalog</h2>
          <p className="muted">Create core services and attach add-on pricing.</p>
        </div>

        <div className="settings-actions">
          <button className="btn btn-primary" type="button" onClick={openCreateService} disabled={!isOwner}>
            Add service type
          </button>
        </div>

        <div className="service-form">
          <div className="form-grid">
            <label>
              <span>Name</span>
              <input
                value={serviceDraft.name}
                onChange={(event) => setServiceDraft((current) => ({ ...current, name: event.target.value }))}
                disabled={!isOwner}
              />
            </label>
            <label>
              <span>Default duration (minutes)</span>
              <input
                type="number"
                min={15}
                value={serviceDraft.default_duration_minutes}
                onChange={(event) =>
                  setServiceDraft((current) => ({
                    ...current,
                    default_duration_minutes: Number(event.target.value || 0),
                  }))
                }
                disabled={!isOwner}
              />
            </label>
            <label>
              <span>Pricing model</span>
              <select
                value={serviceDraft.pricing_model}
                onChange={(event) =>
                  setServiceDraft((current) => ({
                    ...current,
                    pricing_model: event.target.value as "flat" | "hourly",
                  }))
                }
                disabled={!isOwner}
              >
                <option value="flat">Flat</option>
                <option value="hourly">Hourly</option>
              </select>
            </label>
            <label>
              <span>Base price ({serviceDraft.currency})</span>
              <input
                type="number"
                step="0.01"
                value={dollarsFromCents(serviceDraft.base_price_cents)}
                onChange={(event) =>
                  setServiceDraft((current) => ({
                    ...current,
                    base_price_cents: centsFromInput(event.target.value),
                  }))
                }
                disabled={!isOwner}
              />
            </label>
            <label>
              <span>Hourly rate ({serviceDraft.currency})</span>
              <input
                type="number"
                step="0.01"
                value={dollarsFromCents(serviceDraft.hourly_rate_cents)}
                onChange={(event) =>
                  setServiceDraft((current) => ({
                    ...current,
                    hourly_rate_cents: centsFromInput(event.target.value),
                  }))
                }
                disabled={!isOwner}
              />
            </label>
            <label>
              <span>Currency</span>
              <input
                value={serviceDraft.currency}
                onChange={(event) => setServiceDraft((current) => ({ ...current, currency: event.target.value }))}
                disabled={!isOwner}
              />
            </label>
            <label className="full">
              <span>Description</span>
              <input
                value={serviceDraft.description ?? ""}
                onChange={(event) => setServiceDraft((current) => ({ ...current, description: event.target.value }))}
                disabled={!isOwner}
              />
            </label>
            <label>
              <span>Active</span>
              <select
                value={serviceDraft.active ? "active" : "inactive"}
                onChange={(event) =>
                  setServiceDraft((current) => ({ ...current, active: event.target.value === "active" }))
                }
                disabled={!isOwner}
              >
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </label>
          </div>
          <div className="settings-actions">
            <button className="btn btn-primary" type="button" onClick={() => void saveServiceType()} disabled={!isOwner}>
              {editingServiceId ? "Update service" : "Create service"}
            </button>
            {editingServiceId ? (
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => {
                  setEditingServiceId(null);
                  setServiceDraft(defaultServiceDraft);
                }}
              >
                Cancel
              </button>
            ) : null}
          </div>
        </div>

        <div className="settings-grid">
          {serviceTypes.length === 0 ? <p className="muted">No service types yet.</p> : null}
          {serviceTypes.map((serviceType) => (
            <div key={serviceType.service_type_id} className="settings-card">
              <div className="settings-card-header">
                <div>
                  <h3>{serviceType.name}</h3>
                  <p className="muted">{serviceType.description || "No description"}</p>
                </div>
                <span className={`pill ${serviceType.active ? "pill-success" : "pill-muted"}`}>
                  {serviceType.active ? "Active" : "Inactive"}
                </span>
              </div>
              <div className="settings-card-body">
                <div className="settings-meta">
                  <span>Duration: {serviceType.default_duration_minutes} min</span>
                  <span>Model: {serviceType.pricing_model === "flat" ? "Flat" : "Hourly"}</span>
                  <span>Base: {formatCurrency(serviceType.base_price_cents, serviceType.currency)}</span>
                  <span>Hourly: {formatCurrency(serviceType.hourly_rate_cents, serviceType.currency)}</span>
                </div>
                <div className="settings-actions">
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => openEditService(serviceType)}
                    disabled={!isOwner}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => void deleteServiceType(serviceType.service_type_id)}
                    disabled={!isOwner}
                  >
                    Delete
                  </button>
                </div>
                <div className="addon-section">
                  <div className="addon-header">
                    <h4>Add-ons</h4>
                    <button
                      className="btn btn-ghost"
                      type="button"
                      onClick={() => startAddAddon(serviceType.service_type_id)}
                      disabled={!isOwner}
                    >
                      Add add-on
                    </button>
                  </div>
                  {serviceType.addons.length === 0 ? (
                    <p className="muted">No add-ons yet.</p>
                  ) : (
                    <table className="table-like">
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Price</th>
                          <th>Status</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {serviceType.addons.map((addon) => (
                          <tr key={addon.addon_id}>
                            <td>{addon.name}</td>
                            <td>{formatCurrency(addon.price_cents, serviceType.currency)}</td>
                            <td>{addon.active ? "Active" : "Inactive"}</td>
                            <td>
                              <div className="settings-actions">
                                <button
                                  className="btn btn-ghost"
                                  type="button"
                                  onClick={() => startEditAddon(addon)}
                                  disabled={!isOwner}
                                >
                                  Edit
                                </button>
                                <button
                                  className="btn btn-ghost"
                                  type="button"
                                  onClick={() => void deleteAddon(addon.addon_id)}
                                  disabled={!isOwner}
                                >
                                  Delete
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {addonServiceId === serviceType.service_type_id ? (
                    <div className="addon-form">
                      <div className="form-grid">
                        <label>
                          <span>Name</span>
                          <input
                            value={addonDraft.name}
                            onChange={(event) => setAddonDraft((current) => ({ ...current, name: event.target.value }))}
                            disabled={!isOwner}
                          />
                        </label>
                        <label>
                          <span>Price ({serviceType.currency})</span>
                          <input
                            type="number"
                            step="0.01"
                            value={dollarsFromCents(addonDraft.price_cents)}
                            onChange={(event) =>
                              setAddonDraft((current) => ({
                                ...current,
                                price_cents: centsFromInput(event.target.value),
                              }))
                            }
                            disabled={!isOwner}
                          />
                        </label>
                        <label>
                          <span>Status</span>
                          <select
                            value={addonDraft.active ? "active" : "inactive"}
                            onChange={(event) =>
                              setAddonDraft((current) => ({ ...current, active: event.target.value === "active" }))
                            }
                            disabled={!isOwner}
                          >
                            <option value="active">Active</option>
                            <option value="inactive">Inactive</option>
                          </select>
                        </label>
                      </div>
                      <div className="settings-actions">
                        <button className="btn btn-primary" type="button" onClick={() => void saveAddon()} disabled={!isOwner}>
                          {editingAddonId ? "Update add-on" : "Add add-on"}
                        </button>
                        <button className="btn btn-ghost" type="button" onClick={cancelAddonEdit}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="admin-card admin-section">
        <div className="section-heading">
          <h2>Pricing settings</h2>
          <p className="muted">Configure tax rate, promotions, and global adjustments.</p>
        </div>
        {pricingDraft ? (
          <div className="settings-form">
            <div className="form-grid">
              <label>
                <span>GST rate (%)</span>
                <input
                  type="number"
                  step="0.01"
                  value={percentFromRate(pricingDraft.gst_rate)}
                  onChange={(event) =>
                    updatePricingDraft({ gst_rate: Number(event.target.value || 0) / 100 })
                  }
                  disabled={!isOwner}
                />
              </label>
              <label>
                <span>Promo enabled</span>
                <select
                  value={pricingDraft.promo_enabled ? "enabled" : "disabled"}
                  onChange={(event) => updatePricingDraft({ promo_enabled: event.target.value === "enabled" })}
                  disabled={!isOwner}
                >
                  <option value="enabled">Enabled</option>
                  <option value="disabled">Disabled</option>
                </select>
              </label>
            </div>

            <div className="settings-subsection">
              <h3>Discounts</h3>
              {pricingDraft.discounts.map((discount, index) => (
                <div key={`discount-${index}`} className="adjustment-row">
                  <input
                    placeholder="Label"
                    value={discount.label}
                    onChange={(event) => updateAdjustment("discounts", index, { label: event.target.value })}
                    disabled={!isOwner}
                  />
                  <select
                    value={discount.kind}
                    onChange={(event) => {
                      const nextKind = event.target.value as PricingAdjustment["kind"];
                      updateAdjustment("discounts", index, {
                        kind: nextKind,
                        percent: nextKind === "percent" ? discount.percent ?? 0 : null,
                        amount_cents: nextKind === "flat" ? discount.amount_cents ?? 0 : null,
                      });
                    }}
                    disabled={!isOwner}
                  >
                    <option value="percent">Percent</option>
                    <option value="flat">Flat</option>
                  </select>
                  {discount.kind === "percent" ? (
                    <input
                      type="number"
                      step="0.1"
                      placeholder="%"
                      value={(discount.percent ?? 0) * 100}
                      onChange={(event) =>
                        updateAdjustment("discounts", index, {
                          percent: Number(event.target.value || 0) / 100,
                          amount_cents: null,
                        })
                      }
                      disabled={!isOwner}
                    />
                  ) : (
                    <input
                      type="number"
                      step="0.01"
                      placeholder="Amount"
                      value={dollarsFromCents(discount.amount_cents ?? 0)}
                      onChange={(event) =>
                        updateAdjustment("discounts", index, {
                          amount_cents: centsFromInput(event.target.value),
                          percent: null,
                        })
                      }
                      disabled={!isOwner}
                    />
                  )}
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => removeAdjustment("discounts", index)}
                    disabled={!isOwner}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <button className="btn btn-ghost" type="button" onClick={() => addAdjustment("discounts")} disabled={!isOwner}>
                Add discount
              </button>
            </div>

            <div className="settings-subsection">
              <h3>Surcharges</h3>
              {pricingDraft.surcharges.map((surcharge, index) => (
                <div key={`surcharge-${index}`} className="adjustment-row">
                  <input
                    placeholder="Label"
                    value={surcharge.label}
                    onChange={(event) => updateAdjustment("surcharges", index, { label: event.target.value })}
                    disabled={!isOwner}
                  />
                  <select
                    value={surcharge.kind}
                    onChange={(event) => {
                      const nextKind = event.target.value as PricingAdjustment["kind"];
                      updateAdjustment("surcharges", index, {
                        kind: nextKind,
                        percent: nextKind === "percent" ? surcharge.percent ?? 0 : null,
                        amount_cents: nextKind === "flat" ? surcharge.amount_cents ?? 0 : null,
                      });
                    }}
                    disabled={!isOwner}
                  >
                    <option value="percent">Percent</option>
                    <option value="flat">Flat</option>
                  </select>
                  {surcharge.kind === "percent" ? (
                    <input
                      type="number"
                      step="0.1"
                      placeholder="%"
                      value={(surcharge.percent ?? 0) * 100}
                      onChange={(event) =>
                        updateAdjustment("surcharges", index, {
                          percent: Number(event.target.value || 0) / 100,
                          amount_cents: null,
                        })
                      }
                      disabled={!isOwner}
                    />
                  ) : (
                    <input
                      type="number"
                      step="0.01"
                      placeholder="Amount"
                      value={dollarsFromCents(surcharge.amount_cents ?? 0)}
                      onChange={(event) =>
                        updateAdjustment("surcharges", index, {
                          amount_cents: centsFromInput(event.target.value),
                          percent: null,
                        })
                      }
                      disabled={!isOwner}
                    />
                  )}
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => removeAdjustment("surcharges", index)}
                    disabled={!isOwner}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <button className="btn btn-ghost" type="button" onClick={() => addAdjustment("surcharges")} disabled={!isOwner}>
                Add surcharge
              </button>
            </div>

            <div className="settings-actions">
              <button className="btn btn-primary" type="button" onClick={() => void savePricingSettings()} disabled={!isOwner}>
                Save pricing settings
              </button>
              {!isOwner ? <span className="muted">Only Owners can save changes.</span> : null}
            </div>
          </div>
        ) : (
          <p className="muted">Load credentials to see pricing settings.</p>
        )}
      </div>
    </div>
  );
}
