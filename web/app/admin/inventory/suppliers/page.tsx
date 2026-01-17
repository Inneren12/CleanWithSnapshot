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
const DEFAULT_PAGE_SIZE = 25;
const CURRENCY_CODE = "CAD";

type InventorySupplier = {
  supplier_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  address: string | null;
  terms: string | null;
  delivery_days: string | null;
  min_order_cents: number | null;
  notes: string | null;
  created_at: string;
};

type InventorySupplierListResponse = {
  items: InventorySupplier[];
  total: number;
  page: number;
  page_size: number;
};

type SupplierDraft = {
  name: string;
  email: string;
  phone: string;
  address: string;
  terms: string;
  delivery_days: string;
  min_order: string;
  notes: string;
};

const EMPTY_DRAFT: SupplierDraft = {
  name: "",
  email: "",
  phone: "",
  address: "",
  terms: "",
  delivery_days: "",
  min_order: "",
  notes: "",
};

function formatCurrencyFromCents(value: number | null | undefined) {
  if (value === null || typeof value === "undefined") return "—";
  const amount = value / 100;
  return amount.toLocaleString("en-CA", { style: "currency", currency: CURRENCY_CODE });
}

function formatMinOrderInput(value: number | null | undefined) {
  if (value === null || typeof value === "undefined") return "";
  return (value / 100).toFixed(2);
}

function parseMinOrderInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const numeric = Number(trimmed);
  if (!Number.isFinite(numeric) || numeric < 0) return null;
  return Math.round(numeric * 100);
}

function normalizeOptional(value: string) {
  const trimmed = value.trim();
  return trimmed.length ? trimmed : null;
}

export default function InventorySuppliersPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [suppliers, setSuppliers] = useState<InventorySupplier[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [query, setQuery] = useState("");
  const [suppliersLoading, setSuppliersLoading] = useState(false);
  const [suppliersError, setSuppliersError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState<SupplierDraft>(EMPTY_DRAFT);
  const [draftErrors, setDraftErrors] = useState<string[]>([]);
  const [editingSupplier, setEditingSupplier] = useState<InventorySupplier | null>(null);

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
    ? isVisible("module.inventory", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const canViewInventory = permissionKeys.includes("inventory.view");
  const canManageInventory = permissionKeys.includes("inventory.manage");

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const listCountLabel = suppliersLoading
    ? "Loading suppliers…"
    : `${total} supplier${total === 1 ? "" : "s"}`;

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
    try {
      const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Unable to load feature configuration");
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    } catch (error) {
      console.error("Failed to load feature config", error);
      setSettingsError("Unable to load feature configuration");
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/ui-prefs`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Unable to load UI preferences");
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    } catch (error) {
      console.error("Failed to load UI preferences", error);
      setSettingsError("Unable to load UI preferences");
    }
  }, [authHeaders, password, username]);

  const loadSuppliers = useCallback(async () => {
    if (!username || !password) return;
    setSuppliersLoading(true);
    setSuppliersError(null);
    const params = new URLSearchParams();
    if (query) params.set("query", query);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));

    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/suppliers?${params.toString()}`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as InventorySupplierListResponse;
        setSuppliers(data.items);
        setTotal(data.total);
        setPageSize(data.page_size);
      } else {
        setSuppliersError("Unable to load suppliers.");
      }
    } catch (error) {
      console.error("Failed to load inventory suppliers", error);
      setSuppliersError("Network error");
    } finally {
      setSuppliersLoading(false);
    }
  }, [authHeaders, page, pageSize, password, query, username]);

  const saveCredentials = () => {
    if (!username || !password) return;
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Saved credentials");
  };

  const clearCredentials = () => {
    setUsername("");
    setPassword("");
    setProfile(null);
    setFeatureConfig(null);
    setUiPrefs(null);
    setStatusMessage("Cleared credentials");
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_USERNAME_KEY);
      window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    }
  };

  const resetDraft = useCallback(() => {
    setDraft(EMPTY_DRAFT);
    setDraftErrors([]);
    setEditingSupplier(null);
  }, []);

  const openCreateModal = () => {
    resetDraft();
    setModalOpen(true);
  };

  const openEditModal = (supplier: InventorySupplier) => {
    setEditingSupplier(supplier);
    setDraft({
      name: supplier.name,
      email: supplier.email ?? "",
      phone: supplier.phone ?? "",
      address: supplier.address ?? "",
      terms: supplier.terms ?? "",
      delivery_days: supplier.delivery_days ?? "",
      min_order: formatMinOrderInput(supplier.min_order_cents),
      notes: supplier.notes ?? "",
    });
    setDraftErrors([]);
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setDraftErrors([]);
  };

  const validateDraft = () => {
    const errors: string[] = [];
    if (!draft.name.trim()) errors.push("Supplier name is required.");
    if (draft.min_order.trim()) {
      const parsed = parseMinOrderInput(draft.min_order);
      if (parsed === null) errors.push("Minimum order must be 0 or higher.");
    }
    return errors;
  };

  const persistSupplier = async () => {
    if (!canManageInventory) return;
    const errors = validateDraft();
    if (errors.length) {
      setDraftErrors(errors);
      return;
    }
    setDraftErrors([]);
    setStatusMessage(null);

    const minOrderCents = parseMinOrderInput(draft.min_order);
    const payload = {
      name: draft.name.trim(),
      email: normalizeOptional(draft.email),
      phone: normalizeOptional(draft.phone),
      address: normalizeOptional(draft.address),
      terms: normalizeOptional(draft.terms),
      delivery_days: normalizeOptional(draft.delivery_days),
      min_order_cents: minOrderCents,
      notes: normalizeOptional(draft.notes),
    };

    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/inventory/suppliers${editingSupplier ? `/${editingSupplier.supplier_id}` : ""}`,
        {
          method: editingSupplier ? "PATCH" : "POST",
          headers: { ...authHeaders, "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      if (response.ok) {
        setStatusMessage(editingSupplier ? "Supplier updated." : "Supplier created.");
        setModalOpen(false);
        resetDraft();
        void loadSuppliers();
      } else {
        setStatusMessage("Failed to save supplier.");
      }
    } catch (error) {
      console.error("Failed to save inventory supplier", error);
      setStatusMessage("Failed to save supplier.");
    }
  };

  const deleteSupplier = async (supplier: InventorySupplier) => {
    if (!canManageInventory) return;
    const confirmed = window.confirm(`Delete ${supplier.name}? This cannot be undone.`);
    if (!confirmed) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/suppliers/${supplier.supplier_id}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (response.ok) {
        setStatusMessage("Supplier deleted.");
        void loadSuppliers();
      } else {
        setStatusMessage("Failed to delete supplier.");
      }
    } catch (error) {
      console.error("Failed to delete inventory supplier", error);
      setStatusMessage("Failed to delete supplier.");
    }
  };

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (username && password) {
      void loadProfile();
      void loadFeatureConfig();
      void loadUiPrefs();
    }
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    setPage(1);
  }, [query]);

  useEffect(() => {
    if (username && password) {
      void loadSuppliers();
    }
  }, [loadSuppliers, password, username]);

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <div className="card">
          <div className="card-body">Inventory module is disabled for your account.</div>
        </div>
      </div>
    );
  }

  if (!canViewInventory) {
    return (
      <div className="admin-page">
        <div className="card">
          <div className="card-body">You do not have permission to view inventory.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="inventory" />
      <section className="admin-card admin-section">
        <div className="section-heading" style={{ alignItems: "flex-start" }}>
          <div>
            <h1>Inventory suppliers</h1>
            <p className="muted">Manage preferred vendors, delivery expectations, and ordering notes.</p>
          </div>
          <div className="admin-actions">
            <a className="btn btn-ghost" href="/admin/inventory">
              Inventory items
            </a>
            <a className="btn btn-ghost" href="/admin/inventory/purchase-orders">
              Purchase orders
            </a>
            {canManageInventory ? (
              <button className="btn btn-primary" type="button" onClick={openCreateModal}>
                Create supplier
              </button>
            ) : null}
          </div>
        </div>
        <div className="admin-actions" style={{ flexWrap: "wrap" }}>
          <label style={{ minWidth: 200 }}>
            <span className="label">Username</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label style={{ minWidth: 200 }}>
            <span className="label">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <div className="admin-actions">
            <button className="btn btn-primary" type="button" onClick={saveCredentials}>
              Save
            </button>
            <button className="btn btn-ghost" type="button" onClick={clearCredentials}>
              Clear
            </button>
          </div>
        </div>
        {statusMessage ? <p className="alert">{statusMessage}</p> : null}
        {settingsError ? <p className="alert alert-error">{settingsError}</p> : null}
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading" style={{ alignItems: "flex-start" }}>
          <div>
            <h2>Suppliers list</h2>
            <p className="muted">
              {listCountLabel} · Page {page} of {totalPages}
            </p>
          </div>
        </div>
        <div className="admin-actions" style={{ flexWrap: "wrap" }}>
          <label style={{ minWidth: 240 }}>
            <span className="label">Search</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Name, email, or phone"
            />
          </label>
        </div>

        {suppliersError ? <p className="alert alert-error">{suppliersError}</p> : null}

        <div className="table-responsive">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Supplier</th>
                <th>Contact</th>
                <th>Delivery</th>
                <th>Min order</th>
                <th>Notes</th>
                {canManageInventory ? <th>Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {suppliers.length === 0 && !suppliersLoading ? (
                <tr>
                  <td colSpan={canManageInventory ? 6 : 5} className="muted">
                    No suppliers match these filters.
                  </td>
                </tr>
              ) : (
                suppliers.map((supplier) => (
                  <tr key={supplier.supplier_id}>
                    <td>
                      <div style={{ display: "grid", gap: "2px" }}>
                        <strong>{supplier.name}</strong>
                        <span className="muted small">{supplier.address || "No address"}</span>
                      </div>
                    </td>
                    <td>
                      <div style={{ display: "grid", gap: "2px" }}>
                        <span>{supplier.email || "No email"}</span>
                        <span className="muted small">{supplier.phone || "No phone"}</span>
                      </div>
                    </td>
                    <td>
                      <div style={{ display: "grid", gap: "2px" }}>
                        <span>{supplier.delivery_days || "No delivery schedule"}</span>
                        <span className="muted small">{supplier.terms || "No terms"}</span>
                      </div>
                    </td>
                    <td>{formatCurrencyFromCents(supplier.min_order_cents)}</td>
                    <td>{supplier.notes || "—"}</td>
                    {canManageInventory ? (
                      <td>
                        <div className="admin-actions">
                          <button className="btn btn-ghost" type="button" onClick={() => openEditModal(supplier)}>
                            Edit
                          </button>
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => deleteSupplier(supplier)}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="admin-actions" style={{ marginTop: "16px" }}>
          <button
            className="btn btn-ghost"
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((prev) => Math.max(1, prev - 1))}
          >
            Previous
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
          >
            Next
          </button>
          <span className="muted">
            Page {page} of {totalPages}
          </span>
        </div>
      </section>

      {modalOpen ? (
        <div className="schedule-modal" role="dialog" aria-modal="true">
          <div className="schedule-modal-backdrop" onClick={closeModal} />
          <div className="schedule-modal-panel" style={{ maxWidth: "760px" }}>
            <header className="schedule-modal-header">
              <div>
                <h3>{editingSupplier ? "Edit supplier" : "Create supplier"}</h3>
                <p className="muted">Capture ordering preferences so replenishment stays consistent.</p>
              </div>
              <button className="btn btn-ghost" type="button" onClick={closeModal}>
                Close
              </button>
            </header>
            <div className="schedule-modal-body" style={{ display: "grid", gap: "16px" }}>
              {draftErrors.length ? (
                <div className="alert alert-error">
                  <ul>
                    {draftErrors.map((error) => (
                      <li key={error}>{error}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div className="schedule-modal-grid">
                <div className="schedule-modal-section">
                  <label>
                    <span className="label">Supplier name</span>
                    <input
                      value={draft.name}
                      onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span className="label">Email</span>
                    <input
                      value={draft.email}
                      onChange={(event) => setDraft((prev) => ({ ...prev, email: event.target.value }))}
                      placeholder="Optional"
                    />
                  </label>
                  <label>
                    <span className="label">Phone</span>
                    <input
                      value={draft.phone}
                      onChange={(event) => setDraft((prev) => ({ ...prev, phone: event.target.value }))}
                      placeholder="Optional"
                    />
                  </label>
                  <label>
                    <span className="label">Address</span>
                    <input
                      value={draft.address}
                      onChange={(event) => setDraft((prev) => ({ ...prev, address: event.target.value }))}
                      placeholder="Optional"
                    />
                  </label>
                </div>
                <div className="schedule-modal-section">
                  <label>
                    <span className="label">Delivery days</span>
                    <input
                      value={draft.delivery_days}
                      onChange={(event) => setDraft((prev) => ({ ...prev, delivery_days: event.target.value }))}
                      placeholder="Mon/Wed/Fri"
                    />
                  </label>
                  <label>
                    <span className="label">Terms</span>
                    <input
                      value={draft.terms}
                      onChange={(event) => setDraft((prev) => ({ ...prev, terms: event.target.value }))}
                      placeholder="Net 30, COD"
                    />
                  </label>
                  <label>
                    <span className="label">Minimum order ({CURRENCY_CODE})</span>
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      value={draft.min_order}
                      onChange={(event) => setDraft((prev) => ({ ...prev, min_order: event.target.value }))}
                      placeholder="0.00"
                    />
                  </label>
                  <label>
                    <span className="label">Notes</span>
                    <textarea
                      value={draft.notes}
                      onChange={(event) => setDraft((prev) => ({ ...prev, notes: event.target.value }))}
                      rows={4}
                      placeholder="Ordering instructions, preferred rep, or pickup notes."
                    />
                  </label>
                </div>
              </div>
            </div>
            <footer className="schedule-modal-footer">
              <button className="btn btn-ghost" type="button" onClick={closeModal}>
                Cancel
              </button>
              <button className="btn btn-primary" type="button" onClick={persistSupplier}>
                {editingSupplier ? "Save changes" : "Create supplier"}
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </div>
  );
}
