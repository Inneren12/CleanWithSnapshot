"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const LOW_STOCK_ORDERED_KEY = "inventory_low_stock_ordered";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const DEFAULT_PAGE_SIZE = 25;

type InventoryCategory = {
  category_id: string;
  name: string;
  sort_order: number;
};

type InventoryCategoryListResponse = {
  items: InventoryCategory[];
  total: number;
  page: number;
  page_size: number;
};

type InventoryItem = {
  item_id: string;
  category_id: string | null;
  category_name?: string | null;
  sku?: string | null;
  name: string;
  unit: string;
  current_qty: number | string;
  min_qty: number | string;
  location_label?: string | null;
  active: boolean;
};

type InventoryItemListResponse = {
  items: InventoryItem[];
  total: number;
  page: number;
  page_size: number;
};

type ItemDraft = {
  category_id: string;
  sku: string;
  name: string;
  unit: string;
  current_qty: string;
  min_qty: string;
  location_label: string;
  active: boolean;
};

const EMPTY_DRAFT: ItemDraft = {
  category_id: "",
  sku: "",
  name: "",
  unit: "",
  current_qty: "0",
  min_qty: "0",
  location_label: "",
  active: true,
};

function formatQuantity(value: number | string | null | undefined) {
  if (value === null || typeof value === "undefined") return "—";
  const numeric = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(numeric)) return String(value);
  return numeric.toLocaleString("en-CA", { maximumFractionDigits: 2 });
}

function parseQuantity(value: number | string | null | undefined) {
  if (value === null || typeof value === "undefined") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return null;
  return numeric;
}

function normalizeOptional(value: string) {
  const trimmed = value.trim();
  return trimmed.length ? trimmed : null;
}

function isLowStock(item: InventoryItem) {
  const current = parseQuantity(item.current_qty);
  const minimum = parseQuantity(item.min_qty);
  if (current === null || minimum === null) return false;
  return current <= minimum;
}

export default function InventoryItemsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [categories, setCategories] = useState<InventoryCategory[]>([]);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [activeFilter, setActiveFilter] = useState("active");
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState<ItemDraft>(EMPTY_DRAFT);
  const [draftErrors, setDraftErrors] = useState<string[]>([]);
  const [editingItem, setEditingItem] = useState<InventoryItem | null>(null);
  const [orderedItems, setOrderedItems] = useState<Record<string, string>>({});

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
  const lowStockItems = useMemo(
    () => items.filter((item) => item.active && isLowStock(item)),
    [items]
  );
  const filteredItems = useMemo(
    () => (lowStockOnly ? items.filter((item) => isLowStock(item)) : items),
    [items, lowStockOnly]
  );
  const listCountLabel = itemsLoading
    ? "Loading items…"
    : lowStockOnly
      ? `${filteredItems.length} low stock items on this page`
      : `${total} items`;

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

  const loadCategories = useCallback(async () => {
    if (!username || !password) return;
    const params = new URLSearchParams();
    params.set("page", "1");
    params.set("page_size", "100");
    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/categories?${params.toString()}`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as InventoryCategoryListResponse;
        setCategories(data.items);
      } else {
        setCategories([]);
      }
    } catch (error) {
      console.error("Failed to load inventory categories", error);
      setCategories([]);
    }
  }, [authHeaders, password, username]);

  const loadItems = useCallback(async () => {
    if (!username || !password) return;
    setItemsLoading(true);
    setItemsError(null);
    const params = new URLSearchParams();
    if (query) params.set("query", query);
    if (categoryFilter) params.set("category_id", categoryFilter);
    if (activeFilter === "active") params.set("active", "true");
    if (activeFilter === "inactive") params.set("active", "false");
    params.set("page", String(page));
    params.set("page_size", String(pageSize));

    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/items?${params.toString()}`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as InventoryItemListResponse;
        setItems(data.items);
        setTotal(data.total);
        setPageSize(data.page_size);
      } else {
        setItemsError("Unable to load inventory items.");
      }
    } catch (error) {
      console.error("Failed to load inventory items", error);
      setItemsError("Network error");
    } finally {
      setItemsLoading(false);
    }
  }, [activeFilter, authHeaders, categoryFilter, page, pageSize, password, query, username]);

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

  const toggleOrderedStatus = (itemId: string) => {
    setOrderedItems((prev) => {
      const next = { ...prev };
      if (next[itemId]) {
        delete next[itemId];
      } else {
        next[itemId] = new Date().toISOString();
      }
      return next;
    });
  };

  const resetDraft = useCallback(() => {
    setDraft(EMPTY_DRAFT);
    setDraftErrors([]);
    setEditingItem(null);
  }, []);

  const openCreateModal = () => {
    resetDraft();
    setModalOpen(true);
  };

  const openEditModal = (item: InventoryItem) => {
    setEditingItem(item);
    setDraft({
      category_id: item.category_id ?? "",
      sku: item.sku ?? "",
      name: item.name,
      unit: item.unit,
      current_qty: String(item.current_qty ?? "0"),
      min_qty: String(item.min_qty ?? "0"),
      location_label: item.location_label ?? "",
      active: item.active,
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
    if (!draft.name.trim()) errors.push("Item name is required.");
    if (!draft.unit.trim()) errors.push("Unit is required.");
    const currentQty = Number(draft.current_qty);
    const minQty = Number(draft.min_qty);
    if (!Number.isFinite(currentQty) || currentQty < 0) {
      errors.push("Current quantity must be 0 or higher.");
    }
    if (!Number.isFinite(minQty) || minQty < 0) {
      errors.push("Minimum quantity must be 0 or higher.");
    }
    return errors;
  };

  const persistItem = async () => {
    if (!canManageInventory) return;
    const errors = validateDraft();
    if (errors.length) {
      setDraftErrors(errors);
      return;
    }
    setDraftErrors([]);
    setStatusMessage(null);

    const payload = {
      category_id: normalizeOptional(draft.category_id),
      sku: normalizeOptional(draft.sku),
      name: draft.name.trim(),
      unit: draft.unit.trim(),
      current_qty: Number(draft.current_qty),
      min_qty: Number(draft.min_qty),
      location_label: normalizeOptional(draft.location_label),
      active: draft.active,
    };

    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/inventory/items${editingItem ? `/${editingItem.item_id}` : ""}`,
        {
          method: editingItem ? "PATCH" : "POST",
          headers: { ...authHeaders, "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      if (response.ok) {
        setStatusMessage(editingItem ? "Item updated." : "Item created.");
        setModalOpen(false);
        resetDraft();
        void loadItems();
      } else {
        setStatusMessage("Failed to save item.");
      }
    } catch (error) {
      console.error("Failed to save inventory item", error);
      setStatusMessage("Failed to save item.");
    }
  };

  const deactivateItem = async (item: InventoryItem) => {
    if (!canManageInventory || !item.active) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/items/${item.item_id}`, {
        method: "PATCH",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ active: false }),
      });
      if (response.ok) {
        setStatusMessage(`Deactivated ${item.name}.`);
        void loadItems();
      } else {
        setStatusMessage("Failed to deactivate item.");
      }
    } catch (error) {
      console.error("Failed to deactivate inventory item", error);
      setStatusMessage("Failed to deactivate item.");
    }
  };

  const deleteItem = async (item: InventoryItem) => {
    if (!canManageInventory) return;
    const confirmed = window.confirm(`Delete ${item.name}? This cannot be undone.`);
    if (!confirmed) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/items/${item.item_id}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (response.ok) {
        setStatusMessage("Item deleted.");
        void loadItems();
      } else {
        setStatusMessage("Failed to delete item.");
      }
    } catch (error) {
      console.error("Failed to delete inventory item", error);
      setStatusMessage("Failed to delete item.");
    }
  };

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedOrdered = window.localStorage.getItem(LOW_STOCK_ORDERED_KEY);
    if (!storedOrdered) return;
    try {
      setOrderedItems(JSON.parse(storedOrdered) as Record<string, string>);
    } catch (error) {
      console.error("Failed to parse low stock ordered state", error);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(LOW_STOCK_ORDERED_KEY, JSON.stringify(orderedItems));
  }, [orderedItems]);

  useEffect(() => {
    if (username && password) {
      void loadProfile();
      void loadFeatureConfig();
      void loadUiPrefs();
      void loadCategories();
    }
  }, [loadCategories, loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    setPage(1);
  }, [activeFilter, categoryFilter, query]);

  useEffect(() => {
    if (username && password) {
      void loadItems();
    }
  }, [loadItems, password, username]);

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
        <div className="section-heading">
          <h1>Inventory items</h1>
          <p className="muted">Track on-hand cleaning supplies and reorder thresholds.</p>
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
            <h2>Low stock</h2>
            <p className="muted">
              {lowStockItems.length
                ? `${lowStockItems.length} item${lowStockItems.length === 1 ? "" : "s"} below minimum on this page.`
                : "No items are below minimum stock on this page."}
            </p>
          </div>
          <div className="admin-actions">
            <button
              className="btn btn-ghost"
              type="button"
              disabled
              title="Purchase orders will be available once the PO module ships."
            >
              Generate purchase order
            </button>
          </div>
        </div>
        {lowStockItems.length ? (
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Category</th>
                  <th>Current qty</th>
                  <th>Min qty</th>
                  <th>Unit</th>
                  <th>Status</th>
                  {canManageInventory ? <th>Actions</th> : null}
                </tr>
              </thead>
              <tbody>
                {lowStockItems.map((item) => {
                  const orderedAt = orderedItems[item.item_id];
                  return (
                    <tr key={item.item_id}>
                      <td>
                        <div style={{ display: "grid", gap: "2px" }}>
                          <strong>{item.name}</strong>
                          <span className="muted small">{item.sku || "No SKU"}</span>
                        </div>
                      </td>
                      <td>{item.category_name || "Uncategorized"}</td>
                      <td>{formatQuantity(item.current_qty)}</td>
                      <td>{formatQuantity(item.min_qty)}</td>
                      <td>{item.unit}</td>
                      <td>
                        {orderedAt ? (
                          <span className="pill pill-success">Ordered</span>
                        ) : (
                          <span className="pill pill-warning">Needs reorder</span>
                        )}
                      </td>
                      {canManageInventory ? (
                        <td>
                          <div className="admin-actions">
                            <button
                              className="btn btn-ghost"
                              type="button"
                              onClick={() => toggleOrderedStatus(item.item_id)}
                            >
                              {orderedAt ? "Undo ordered" : "Mark as ordered"}
                            </button>
                            <button className="btn btn-ghost" type="button" onClick={() => openEditModal(item)}>
                              Edit
                            </button>
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading" style={{ alignItems: "flex-start" }}>
          <div>
            <h2>Inventory list</h2>
            <p className="muted">
              {listCountLabel} · Page {page} of {totalPages}
            </p>
          </div>
          {canManageInventory ? (
            <button className="btn btn-primary" type="button" onClick={openCreateModal}>
              Create item
            </button>
          ) : null}
        </div>
        <div className="admin-actions" style={{ flexWrap: "wrap" }}>
          <label style={{ minWidth: 220 }}>
            <span className="label">Search</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Name or SKU"
            />
          </label>
          <label>
            <span className="label">Category</span>
            <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
              <option value="">All categories</option>
              {categories.map((category) => (
                <option key={category.category_id} value={category.category_id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox" style={{ alignSelf: "flex-end" }}>
            <input
              type="checkbox"
              checked={lowStockOnly}
              onChange={(event) => setLowStockOnly(event.target.checked)}
            />
            <span>Low stock only (page filter)</span>
          </label>
          <label>
            <span className="label">Status</span>
            <select value={activeFilter} onChange={(event) => setActiveFilter(event.target.value)}>
              <option value="all">All</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </label>
        </div>

        {itemsError ? <p className="alert alert-error">{itemsError}</p> : null}

        <div className="table-responsive">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Category</th>
                <th>Location</th>
                <th>Current qty</th>
                <th>Min qty</th>
                <th>Unit</th>
                <th>Active</th>
                {canManageInventory ? <th>Actions</th> : null}
              </tr>
            </thead>
            <tbody>
              {filteredItems.length === 0 && !itemsLoading ? (
                <tr>
                  <td colSpan={canManageInventory ? 8 : 7} className="muted">
                    No inventory items match these filters.
                  </td>
                </tr>
              ) : (
                filteredItems.map((item) => (
                  <tr key={item.item_id}>
                    <td>
                      <div style={{ display: "grid", gap: "2px" }}>
                        <strong>{item.name}</strong>
                        <span className="muted small">{item.sku || "No SKU"}</span>
                      </div>
                    </td>
                    <td>{item.category_name || "Uncategorized"}</td>
                    <td>{item.location_label || "—"}</td>
                    <td>{formatQuantity(item.current_qty)}</td>
                    <td>{formatQuantity(item.min_qty)}</td>
                    <td>{item.unit}</td>
                    <td>{item.active ? "Active" : "Inactive"}</td>
                    {canManageInventory ? (
                      <td>
                        <div className="admin-actions">
                          <button className="btn btn-ghost" type="button" onClick={() => openEditModal(item)}>
                            Edit
                          </button>
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => deactivateItem(item)}
                            disabled={!item.active}
                          >
                            Deactivate
                          </button>
                          <button className="btn btn-ghost" type="button" onClick={() => deleteItem(item)}>
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
          <div className="schedule-modal-panel" style={{ maxWidth: "640px" }}>
            <header className="schedule-modal-header">
              <div>
                <h3>{editingItem ? "Edit inventory item" : "Create inventory item"}</h3>
                <p className="muted">Keep quantities and reorder thresholds aligned with your stockroom.</p>
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
                    <span className="label">Item name</span>
                    <input
                      value={draft.name}
                      onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span className="label">SKU</span>
                    <input
                      value={draft.sku}
                      onChange={(event) => setDraft((prev) => ({ ...prev, sku: event.target.value }))}
                      placeholder="Optional"
                    />
                  </label>
                  <label>
                    <span className="label">Category</span>
                    <select
                      value={draft.category_id}
                      onChange={(event) => setDraft((prev) => ({ ...prev, category_id: event.target.value }))}
                    >
                      <option value="">Uncategorized</option>
                      {categories.map((category) => (
                        <option key={category.category_id} value={category.category_id}>
                          {category.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span className="label">Location</span>
                    <input
                      value={draft.location_label}
                      onChange={(event) => setDraft((prev) => ({ ...prev, location_label: event.target.value }))}
                      placeholder="Storage room or shelf"
                    />
                  </label>
                </div>
                <div className="schedule-modal-section">
                  <label>
                    <span className="label">Unit</span>
                    <input
                      value={draft.unit}
                      onChange={(event) => setDraft((prev) => ({ ...prev, unit: event.target.value }))}
                      placeholder="Bottle, box, roll"
                    />
                  </label>
                  <label>
                    <span className="label">Current quantity</span>
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      value={draft.current_qty}
                      onChange={(event) => setDraft((prev) => ({ ...prev, current_qty: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span className="label">Minimum quantity</span>
                    <input
                      type="number"
                      min={0}
                      step="0.01"
                      value={draft.min_qty}
                      onChange={(event) => setDraft((prev) => ({ ...prev, min_qty: event.target.value }))}
                    />
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={draft.active}
                      onChange={(event) => setDraft((prev) => ({ ...prev, active: event.target.checked }))}
                    />
                    <span>Active</span>
                  </label>
                </div>
              </div>
            </div>
            <footer className="schedule-modal-footer">
              <button className="btn btn-ghost" type="button" onClick={closeModal}>
                Cancel
              </button>
              <button className="btn btn-primary" type="button" onClick={persistItem}>
                {editingItem ? "Save changes" : "Create item"}
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </div>
  );
}
