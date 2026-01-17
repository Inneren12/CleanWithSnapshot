"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

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
const CURRENCY_CODE = "CAD";

type InventorySupplier = {
  supplier_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  min_order_cents: number | null;
  delivery_days: string | null;
};

type InventorySupplierListResponse = {
  items: InventorySupplier[];
  total: number;
  page: number;
  page_size: number;
};

type InventoryItem = {
  item_id: string;
  name: string;
  sku?: string | null;
  unit: string;
  active: boolean;
};

type InventoryItemListResponse = {
  items: InventoryItem[];
  total: number;
  page: number;
  page_size: number;
};

type PurchaseOrderItem = {
  po_item_id: string;
  po_id: string;
  item_id: string;
  qty: number | string;
  unit_cost_cents: number;
  line_total_cents: number;
};

type PurchaseOrderDetail = {
  po_id: string;
  supplier_id: string;
  status: "draft" | "ordered" | "received";
  ordered_at: string | null;
  received_at: string | null;
  notes: string | null;
  subtotal_cents: number;
  tax_cents: number;
  shipping_cents: number;
  total_cents: number;
  items: PurchaseOrderItem[];
};

type PurchaseOrderLineDraft = {
  item_id: string;
  qty: string;
  unit_cost: string;
};

type PurchaseOrderDraft = {
  supplier_id: string;
  notes: string;
  tax: string;
  shipping: string;
  items: PurchaseOrderLineDraft[];
};

const EMPTY_LINE: PurchaseOrderLineDraft = {
  item_id: "",
  qty: "",
  unit_cost: "",
};

const EMPTY_DRAFT: PurchaseOrderDraft = {
  supplier_id: "",
  notes: "",
  tax: "0",
  shipping: "0",
  items: [{ ...EMPTY_LINE }],
};

function formatCurrencyFromCents(value: number | null | undefined) {
  if (value === null || typeof value === "undefined") return "—";
  const amount = value / 100;
  return amount.toLocaleString("en-CA", { style: "currency", currency: CURRENCY_CODE });
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleString("en-CA");
}

function parseCurrencyInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return 0;
  const numeric = Number(trimmed);
  if (!Number.isFinite(numeric) || numeric < 0) return null;
  return Math.round(numeric * 100);
}

function parseQtyInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const numeric = Number(trimmed);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  return numeric;
}

function normalizeNotes(value: string) {
  const trimmed = value.trim();
  return trimmed.length ? trimmed : "";
}

function lineTotalCents(line: PurchaseOrderLineDraft) {
  const qty = parseQtyInput(line.qty);
  const unitCost = parseCurrencyInput(line.unit_cost);
  if (qty === null || unitCost === null) return null;
  return Math.round(qty * unitCost);
}

function toDraft(order: PurchaseOrderDetail): PurchaseOrderDraft {
  return {
    supplier_id: order.supplier_id,
    notes: order.notes ?? "",
    tax: (order.tax_cents / 100).toFixed(2),
    shipping: (order.shipping_cents / 100).toFixed(2),
    items: order.items.map((item) => ({
      item_id: item.item_id,
      qty: String(item.qty ?? ""),
      unit_cost: (item.unit_cost_cents / 100).toFixed(2),
    })),
  };
}

export default function PurchaseOrderDetailPage() {
  const params = useParams();
  const poId = params?.po_id ? String(params.po_id) : "";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [suppliers, setSuppliers] = useState<InventorySupplier[]>([]);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [purchaseOrder, setPurchaseOrder] = useState<PurchaseOrderDetail | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [draft, setDraft] = useState<PurchaseOrderDraft>(EMPTY_DRAFT);
  const [draftErrors, setDraftErrors] = useState<string[]>([]);
  const [draftSubmitting, setDraftSubmitting] = useState(false);

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

  const supplierMap = useMemo(() => {
    return suppliers.reduce<Record<string, InventorySupplier>>((acc, supplier) => {
      acc[supplier.supplier_id] = supplier;
      return acc;
    }, {});
  }, [suppliers]);

  const itemMap = useMemo(() => {
    return items.reduce<Record<string, InventoryItem>>((acc, item) => {
      acc[item.item_id] = item;
      return acc;
    }, {});
  }, [items]);

  const lineTotals = useMemo(() => draft.items.map((line) => lineTotalCents(line)), [draft.items]);
  const subtotalCents = useMemo(() => {
    // Draft lines can be incomplete; default missing totals to 0 until all inputs are valid.
    return lineTotals.reduce<number>((sum, lineTotal) => sum + (lineTotal ?? 0), 0);
  }, [lineTotals]);

  const taxCents = parseCurrencyInput(draft.tax);
  const shippingCents = parseCurrencyInput(draft.shipping);
  const totalsInvalid = lineTotals.some((total) => total === null) || taxCents === null || shippingCents === null;
  const totalCents = totalsInvalid ? null : subtotalCents + (taxCents ?? 0) + (shippingCents ?? 0);

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
    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/suppliers?page=1&page_size=100`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Unable to load suppliers");
      const data = (await response.json()) as InventorySupplierListResponse;
      setSuppliers(data.items);
    } catch (error) {
      console.error("Failed to load suppliers", error);
      setSettingsError("Unable to load suppliers");
    }
  }, [authHeaders, password, username]);

  const loadItems = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/items?page=1&page_size=100`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Unable to load items");
      const data = (await response.json()) as InventoryItemListResponse;
      setItems(data.items);
    } catch (error) {
      console.error("Failed to load items", error);
      setSettingsError("Unable to load items");
    }
  }, [authHeaders, password, username]);

  const loadPurchaseOrder = useCallback(async () => {
    if (!username || !password || !poId) return;
    setPageError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/purchase-orders/${poId}`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) {
        if (response.status === 404) {
          setPageError("Purchase order not found.");
        } else {
          setPageError("Unable to load purchase order.");
        }
        return;
      }
      const data = (await response.json()) as PurchaseOrderDetail;
      setPurchaseOrder(data);
      setDraft(toDraft(data));
    } catch (error) {
      console.error("Failed to load purchase order", error);
      setPageError("Network error");
    }
  }, [authHeaders, password, poId, username]);

  const saveCredentials = () => {
    if (!username || !password) return;
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Saved credentials");
  };

  const clearCredentials = () => {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setStatusMessage("Cleared saved credentials");
  };

  const addLine = () => {
    setDraft((prev) => ({ ...prev, items: [...prev.items, { ...EMPTY_LINE }] }));
  };

  const removeLine = (index: number) => {
    setDraft((prev) => ({
      ...prev,
      items: prev.items.length > 1 ? prev.items.filter((_, idx) => idx !== index) : prev.items,
    }));
  };

  const updateLine = (index: number, updates: Partial<PurchaseOrderLineDraft>) => {
    setDraft((prev) => ({
      ...prev,
      items: prev.items.map((line, idx) => (idx === index ? { ...line, ...updates } : line)),
    }));
  };

  const validateDraft = () => {
    const errors: string[] = [];
    if (!draft.supplier_id) errors.push("Select a supplier.");

    const parsedTax = parseCurrencyInput(draft.tax);
    if (parsedTax === null) errors.push("Tax must be 0 or greater.");

    const parsedShipping = parseCurrencyInput(draft.shipping);
    if (parsedShipping === null) errors.push("Shipping must be 0 or greater.");

    const preparedItems = draft.items
      .map((line, index) => {
        if (!line.item_id) {
          errors.push(`Line ${index + 1}: select an item.`);
          return null;
        }
        const qty = parseQtyInput(line.qty);
        if (qty === null) {
          errors.push(`Line ${index + 1}: enter a quantity greater than 0.`);
          return null;
        }
        const unitCost = parseCurrencyInput(line.unit_cost);
        if (unitCost === null) {
          errors.push(`Line ${index + 1}: enter a unit cost of 0 or more.`);
          return null;
        }
        return { item_id: line.item_id, qty, unit_cost_cents: unitCost };
      })
      .filter(Boolean) as Array<{ item_id: string; qty: number; unit_cost_cents: number }>;

    if (!preparedItems.length) {
      errors.push("Add at least one valid line item.");
    }

    return { errors, preparedItems, parsedTax, parsedShipping };
  };

  const updatePurchaseOrder = async () => {
    if (!canManageInventory || !purchaseOrder) return;
    const { errors, preparedItems, parsedTax, parsedShipping } = validateDraft();
    setDraftErrors(errors);
    if (errors.length) return;
    setDraftSubmitting(true);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/inventory/purchase-orders/${purchaseOrder.po_id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        body: JSON.stringify({
          supplier_id: draft.supplier_id,
          notes: normalizeNotes(draft.notes),
          tax_cents: parsedTax ?? 0,
          shipping_cents: parsedShipping ?? 0,
          items: preparedItems,
        }),
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        setStatusMessage(errorPayload?.detail || "Failed to update purchase order.");
        return;
      }
      const data = (await response.json()) as PurchaseOrderDetail;
      setPurchaseOrder(data);
      setDraft(toDraft(data));
      setStatusMessage("Purchase order updated.");
    } catch (error) {
      console.error("Failed to update purchase order", error);
      setStatusMessage("Failed to update purchase order.");
    } finally {
      setDraftSubmitting(false);
    }
  };

  const markOrdered = async () => {
    if (!canManageInventory || !purchaseOrder) return;
    if (!window.confirm("Mark this purchase order as ordered?")) return;
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/inventory/purchase-orders/${purchaseOrder.po_id}/mark_ordered`,
        {
          method: "POST",
          headers: authHeaders,
        }
      );
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        setStatusMessage(errorPayload?.detail || "Failed to mark as ordered.");
        return;
      }
      const data = (await response.json()) as PurchaseOrderDetail;
      setPurchaseOrder(data);
      setStatusMessage("Purchase order marked as ordered.");
    } catch (error) {
      console.error("Failed to mark purchase order ordered", error);
      setStatusMessage("Failed to mark as ordered.");
    }
  };

  const markReceived = async () => {
    if (!canManageInventory || !purchaseOrder) return;
    if (!window.confirm("Mark this purchase order as received and update stock?")) return;
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/inventory/purchase-orders/${purchaseOrder.po_id}/mark_received`,
        {
          method: "POST",
          headers: authHeaders,
        }
      );
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        setStatusMessage(errorPayload?.detail || "Failed to mark as received.");
        return;
      }
      const data = (await response.json()) as PurchaseOrderDetail;
      setPurchaseOrder(data);
      setStatusMessage("Purchase order marked as received.");
    } catch (error) {
      console.error("Failed to mark purchase order received", error);
      setStatusMessage("Failed to mark as received.");
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
      void loadSuppliers();
      void loadItems();
    }
  }, [loadFeatureConfig, loadItems, loadProfile, loadSuppliers, loadUiPrefs, password, username]);

  useEffect(() => {
    if (username && password && poId) {
      void loadPurchaseOrder();
    }
  }, [loadPurchaseOrder, password, poId, username]);

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
            <h1>Purchase order</h1>
            <p className="muted">Review line items and move the order through ordered → received.</p>
          </div>
          <div className="admin-actions">
            <a className="btn btn-ghost" href="/admin/inventory/purchase-orders">
              Back to list
            </a>
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

      {pageError ? (
        <section className="admin-card admin-section">
          <p className="alert alert-error">{pageError}</p>
        </section>
      ) : null}

      {purchaseOrder ? (
        <>
          <section className="admin-card admin-section">
            <div className="section-heading" style={{ alignItems: "flex-start" }}>
              <div>
                <h2>Order summary</h2>
                <p className="muted">Supplier, status, and totals for this purchase order.</p>
              </div>
              {canManageInventory ? (
                <div className="admin-actions">
                  {purchaseOrder.status === "draft" ? (
                    <button className="btn btn-primary" type="button" onClick={() => void markOrdered()}>
                      Mark ordered
                    </button>
                  ) : null}
                  {purchaseOrder.status === "ordered" ? (
                    <button className="btn btn-primary" type="button" onClick={() => void markReceived()}>
                      Mark received
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="schedule-modal-grid">
              <div className="schedule-modal-section">
                <div className="card" style={{ padding: "12px" }}>
                  <div className="muted small">Supplier</div>
                  <div style={{ fontWeight: 600 }}>
                    {supplierMap[purchaseOrder.supplier_id]?.name ?? "Unknown supplier"}
                  </div>
                  <div className="muted small">{purchaseOrder.po_id}</div>
                </div>
                <div className="card" style={{ padding: "12px" }}>
                  <div className="muted small">Status</div>
                  <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                    <span className={`pill pill-${purchaseOrder.status === "received" ? "success" : "warning"}`}>
                      {purchaseOrder.status}
                    </span>
                    <span className="muted small">Ordered: {formatDateTime(purchaseOrder.ordered_at)}</span>
                  </div>
                  <div className="muted small">Received: {formatDateTime(purchaseOrder.received_at)}</div>
                </div>
                {purchaseOrder.notes ? (
                  <div className="card" style={{ padding: "12px" }}>
                    <div className="muted small">Notes</div>
                    <p>{purchaseOrder.notes}</p>
                  </div>
                ) : null}
              </div>
              <div className="schedule-modal-section">
                <div className="card" style={{ padding: "12px" }}>
                  <div className="muted small">Totals</div>
                  <div style={{ display: "grid", gap: "4px" }}>
                    <div className="split-row">
                      <span>Subtotal</span>
                      <span>{formatCurrencyFromCents(purchaseOrder.subtotal_cents)}</span>
                    </div>
                    <div className="split-row">
                      <span>Tax</span>
                      <span>{formatCurrencyFromCents(purchaseOrder.tax_cents)}</span>
                    </div>
                    <div className="split-row">
                      <span>Shipping</span>
                      <span>{formatCurrencyFromCents(purchaseOrder.shipping_cents)}</span>
                    </div>
                    <div className="split-row" style={{ fontWeight: 600 }}>
                      <span>Total</span>
                      <span>{formatCurrencyFromCents(purchaseOrder.total_cents)}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="admin-card admin-section">
            <div className="section-heading">
              <div>
                <h2>Line items</h2>
                <p className="muted">Review ordered quantities and unit pricing.</p>
              </div>
            </div>
            <div className="table-responsive">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Qty</th>
                    <th>Unit</th>
                    <th>Unit cost</th>
                    <th>Line total</th>
                  </tr>
                </thead>
                <tbody>
                  {purchaseOrder.items.map((line) => {
                    const item = itemMap[line.item_id];
                    return (
                      <tr key={line.po_item_id}>
                        <td>
                          <div style={{ display: "grid", gap: "2px" }}>
                            <strong>{item?.name ?? "Unknown item"}</strong>
                            <span className="muted small">{item?.sku ?? line.item_id}</span>
                          </div>
                        </td>
                        <td>{line.qty}</td>
                        <td>{item?.unit ?? "—"}</td>
                        <td>{formatCurrencyFromCents(line.unit_cost_cents)}</td>
                        <td>{formatCurrencyFromCents(line.line_total_cents)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {purchaseOrder.status === "draft" && canManageInventory ? (
            <section className="admin-card admin-section">
              <div className="section-heading">
                <div>
                  <h2>Edit draft</h2>
                  <p className="muted">Update supplier, line items, and totals before ordering.</p>
                </div>
              </div>

              {draftErrors.length ? (
                <div className="alert alert-error">
                  <ul>
                    {draftErrors.map((error) => (
                      <li key={error}>{error}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <div className="schedule-modal-grid" style={{ marginBottom: "16px" }}>
                <div className="schedule-modal-section">
                  <label>
                    <span className="label">Supplier</span>
                    <select
                      value={draft.supplier_id}
                      onChange={(event) => setDraft((prev) => ({ ...prev, supplier_id: event.target.value }))}
                    >
                      <option value="">Select supplier</option>
                      {suppliers.map((supplier) => (
                        <option key={supplier.supplier_id} value={supplier.supplier_id}>
                          {supplier.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span className="label">Notes</span>
                    <textarea
                      rows={3}
                      value={draft.notes}
                      onChange={(event) => setDraft((prev) => ({ ...prev, notes: event.target.value }))}
                      placeholder="Optional ordering notes"
                    />
                  </label>
                </div>
                <div className="schedule-modal-section">
                  <label>
                    <span className="label">Tax ({CURRENCY_CODE})</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={draft.tax}
                      onChange={(event) => setDraft((prev) => ({ ...prev, tax: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span className="label">Shipping ({CURRENCY_CODE})</span>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={draft.shipping}
                      onChange={(event) => setDraft((prev) => ({ ...prev, shipping: event.target.value }))}
                    />
                  </label>
                  <div className="card" style={{ padding: "12px" }}>
                    <div className="muted small">Totals</div>
                    <div style={{ display: "grid", gap: "4px" }}>
                      <div className="split-row">
                        <span>Subtotal</span>
                        <span>{formatCurrencyFromCents(subtotalCents)}</span>
                      </div>
                      <div className="split-row">
                        <span>Tax</span>
                        <span>{taxCents === null ? "—" : formatCurrencyFromCents(taxCents)}</span>
                      </div>
                      <div className="split-row">
                        <span>Shipping</span>
                        <span>{shippingCents === null ? "—" : formatCurrencyFromCents(shippingCents)}</span>
                      </div>
                      <div className="split-row" style={{ fontWeight: 600 }}>
                        <span>Total</span>
                        <span>{totalCents === null ? "—" : formatCurrencyFromCents(totalCents)}</span>
                      </div>
                    </div>
                    {totalsInvalid ? <div className="muted small">Totals update when all fields are valid.</div> : null}
                  </div>
                </div>
              </div>

              <div className="table-responsive">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th style={{ width: "140px" }}>Qty</th>
                      <th style={{ width: "160px" }}>Unit cost ({CURRENCY_CODE})</th>
                      <th style={{ width: "160px" }}>Line total</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {draft.items.map((line, index) => {
                      const lineTotal = lineTotals[index];
                      const item = line.item_id ? itemMap[line.item_id] : null;
                      return (
                        <tr key={`${line.item_id}-${index}`}>
                          <td>
                            <select
                              value={line.item_id}
                              onChange={(event) => updateLine(index, { item_id: event.target.value })}
                            >
                              <option value="">Select item</option>
                              {items.map((itemOption) => (
                                <option key={itemOption.item_id} value={itemOption.item_id}>
                                  {itemOption.name} {itemOption.sku ? `(${itemOption.sku})` : ""}
                                </option>
                              ))}
                            </select>
                            {item ? <div className="muted small">Unit: {item.unit}</div> : null}
                          </td>
                          <td>
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              value={line.qty}
                              onChange={(event) => updateLine(index, { qty: event.target.value })}
                              placeholder="0"
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              value={line.unit_cost}
                              onChange={(event) => updateLine(index, { unit_cost: event.target.value })}
                              placeholder="0.00"
                            />
                          </td>
                          <td>{lineTotal === null ? "—" : formatCurrencyFromCents(lineTotal)}</td>
                          <td>
                            <button
                              className="btn btn-ghost"
                              type="button"
                              onClick={() => removeLine(index)}
                              disabled={draft.items.length === 1}
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="admin-actions" style={{ marginTop: "12px" }}>
                <button className="btn btn-ghost" type="button" onClick={addLine}>
                  Add line
                </button>
                <button
                  className="btn btn-primary"
                  type="button"
                  onClick={() => void updatePurchaseOrder()}
                  disabled={draftSubmitting}
                >
                  {draftSubmitting ? "Saving…" : "Save draft"}
                </button>
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
