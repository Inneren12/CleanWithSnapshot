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
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type Invoice = {
  invoice_id: string;
  invoice_number: string;
  order_id: string | null;
  customer_id: string | null;
  status: string;
  issue_date: string;
  due_date: string | null;
  currency: string;
  total_cents: number;
  paid_cents: number;
  balance_due_cents: number;
  created_at: string;
  updated_at: string;
};

type InvoiceListResponse = {
  invoices: Invoice[];
  page: number;
  page_size: number;
  total: number;
};

const STATUS_OPTIONS = [
  { value: "", label: "All Statuses" },
  { value: "DRAFT", label: "Draft" },
  { value: "SENT", label: "Sent" },
  { value: "PARTIAL", label: "Partial" },
  { value: "PAID", label: "Paid" },
  { value: "OVERDUE", label: "Overdue" },
  { value: "VOID", label: "Void" },
];

const PAYMENT_METHOD_OPTIONS = [
  { value: "cash", label: "Cash" },
  { value: "etransfer", label: "E-Transfer" },
  { value: "card", label: "Card" },
  { value: "other", label: "Other" },
];

export default function InvoicesPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkActionMessage, setBulkActionMessage] = useState<string | null>(null);
  const [bulkActionError, setBulkActionError] = useState<string | null>(null);

  // Filter states
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [amountMin, setAmountMin] = useState("");
  const [amountMax, setAmountMax] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [bulkNote, setBulkNote] = useState("");

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
    ? isVisible("module.invoices", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const hasViewPermission = permissionKeys.includes("invoices.view");
  const hasSendPermission = permissionKeys.includes("invoices.edit");
  const hasRecordPaymentPermission = permissionKeys.includes("payments.record");

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      {
        key: "org-settings",
        label: "Org Settings",
        href: "/admin/settings/org",
        featureKey: "module.settings",
      },
      {
        key: "integrations",
        label: "Integrations",
        href: "/admin/settings/integrations",
        featureKey: "module.integrations",
      },
    ];
    return candidates
      .filter((entry) => isVisible(entry.featureKey, permissionKeys, featureOverrides, hiddenKeys))
      .map(({ featureKey, ...link }) => link);
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
    }
  }, [authHeaders, username, password]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/feature-config`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    }
  }, [authHeaders, username, password]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/ui-preferences`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    }
  }, [authHeaders, username, password]);

  const loadInvoices = useCallback(async () => {
    if (!username || !password) return;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams();
    params.set("page", page.toString());
    params.set("page_size", pageSize.toString());
    if (searchQuery) params.set("q", searchQuery);
    if (statusFilter) params.set("status", statusFilter);
    if (fromDate) params.set("from", fromDate);
    if (toDate) params.set("to", toDate);
    if (amountMin) params.set("amount_min", (parseFloat(amountMin) * 100).toString());
    if (amountMax) params.set("amount_max", (parseFloat(amountMax) * 100).toString());

    try {
      const response = await fetch(`${API_BASE}/v1/admin/invoices?${params.toString()}`, {
        headers: authHeaders,
        cache: "no-store",
      });

      if (response.ok) {
        const data = (await response.json()) as InvoiceListResponse;
        setInvoices(data.invoices);
        setTotal(data.total);
        setPage(data.page);
      } else {
        setError("Failed to load invoices");
      }
    } catch (err) {
      setError("Network error loading invoices");
    } finally {
      setLoading(false);
    }
  }, [authHeaders, username, password, page, pageSize, searchQuery, statusFilter, fromDate, toDate, amountMin, amountMax]);

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername && storedPassword) {
      setUsername(storedUsername);
      setPassword(storedPassword);
    }
  }, []);

  useEffect(() => {
    if (username && password) {
      void loadProfile();
      void loadFeatureConfig();
      void loadUiPrefs();
    }
  }, [loadProfile, loadFeatureConfig, loadUiPrefs, username, password]);

  useEffect(() => {
    if (hasViewPermission) {
      void loadInvoices();
    }
  }, [hasViewPermission, loadInvoices]);

  const handleLogin = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      localStorage.setItem(STORAGE_USERNAME_KEY, username);
      localStorage.setItem(STORAGE_PASSWORD_KEY, password);
      void loadProfile();
      void loadFeatureConfig();
      void loadUiPrefs();
    },
    [username, password, loadProfile, loadFeatureConfig, loadUiPrefs]
  );

  const toggleSelectAll = useCallback(() => {
    if (selectedIds.size === invoices.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(invoices.map((inv) => inv.invoice_id)));
    }
  }, [invoices, selectedIds.size]);

  const toggleSelect = useCallback((invoiceId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(invoiceId)) {
        next.delete(invoiceId);
      } else {
        next.add(invoiceId);
      }
      return next;
    });
  }, []);

  const handleBulkRemind = useCallback(async () => {
    if (!username || !password || selectedIds.size === 0) return;
    setBulkActionMessage(null);
    setBulkActionError(null);

    try {
      const response = await fetch(`${API_BASE}/v1/admin/invoices/bulk/remind`, {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ invoice_ids: Array.from(selectedIds) }),
      });

      if (response.ok) {
        const result = await response.json();
        setBulkActionMessage(`Sent ${result.succeeded.length} reminders. ${result.failed.length} failed.`);
        setSelectedIds(new Set());
        void loadInvoices();
      } else {
        setBulkActionError("Failed to send reminders");
      }
    } catch (err) {
      setBulkActionError("Network error sending reminders");
    }
  }, [authHeaders, username, password, selectedIds, loadInvoices]);

  const handleBulkMarkPaid = useCallback(async () => {
    if (!username || !password || selectedIds.size === 0) return;
    setBulkActionMessage(null);
    setBulkActionError(null);

    try {
      const response = await fetch(`${API_BASE}/v1/admin/invoices/bulk/mark_paid`, {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          invoice_ids: Array.from(selectedIds),
          method: paymentMethod,
          note: bulkNote || null,
        }),
      });

      if (response.ok) {
        const result = await response.json();
        setBulkActionMessage(`Marked ${result.succeeded.length} as paid. ${result.failed.length} failed.`);
        setSelectedIds(new Set());
        setBulkNote("");
        void loadInvoices();
      } else {
        setBulkActionError("Failed to mark invoices as paid");
      }
    } catch (err) {
      setBulkActionError("Network error marking invoices as paid");
    }
  }, [authHeaders, username, password, selectedIds, paymentMethod, bulkNote, loadInvoices]);

  const handleSearch = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    void loadInvoices();
  }, [loadInvoices]);

  const formatMoney = (cents: number, currency: string) => {
    const amount = (cents / 100).toFixed(2);
    return `${currency} $${amount}`;
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "—";
    return new Date(dateStr).toLocaleDateString();
  };

  if (!username || !password) {
    return (
      <div className="admin-page">
        <div className="admin-card">
          <h2>Admin Login</h2>
          <form onSubmit={handleLogin} style={{ maxWidth: "400px" }}>
            <div className="form-field">
              <label htmlFor="username">Username</label>
              <input
                type="text"
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div className="form-field">
              <label htmlFor="password">Password</label>
              <input
                type="password"
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <button type="submit" className="btn">
              Login
            </button>
          </form>
        </div>
      </div>
    );
  }

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="invoices" />
        <div className="admin-card">
          <p>Invoices module is not enabled or you do not have permission to access it.</p>
        </div>
      </div>
    );
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="invoices" />
      <div className="admin-content">
        <div className="admin-card">
          <h2>Invoices</h2>
          <p className="muted">Search, filter and manage invoices with bulk actions</p>

          {/* Search and Filters */}
          <form onSubmit={handleSearch} className="invoice-filters">
            <div className="filter-row">
              <div className="form-field">
                <label htmlFor="search">Search</label>
                <input
                  type="text"
                  id="search"
                  placeholder="Invoice #, client name, email..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="status">Status</label>
                <select id="status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="filter-row">
              <div className="form-field">
                <label htmlFor="from">From Date</label>
                <input
                  type="date"
                  id="from"
                  value={fromDate}
                  onChange={(e) => setFromDate(e.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="to">To Date</label>
                <input
                  type="date"
                  id="to"
                  value={toDate}
                  onChange={(e) => setToDate(e.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="amountMin">Min Amount</label>
                <input
                  type="number"
                  id="amountMin"
                  step="0.01"
                  placeholder="0.00"
                  value={amountMin}
                  onChange={(e) => setAmountMin(e.target.value)}
                />
              </div>
              <div className="form-field">
                <label htmlFor="amountMax">Max Amount</label>
                <input
                  type="number"
                  id="amountMax"
                  step="0.01"
                  placeholder="0.00"
                  value={amountMax}
                  onChange={(e) => setAmountMax(e.target.value)}
                />
              </div>
            </div>
            <div className="filter-row">
              <button type="submit" className="btn">
                Apply Filters
              </button>
              <button
                type="button"
                className="btn secondary"
                onClick={() => {
                  setSearchQuery("");
                  setStatusFilter("");
                  setFromDate("");
                  setToDate("");
                  setAmountMin("");
                  setAmountMax("");
                  setPage(1);
                }}
              >
                Reset
              </button>
            </div>
          </form>

          {/* Bulk Actions */}
          {selectedIds.size > 0 && (
            <div className="bulk-actions">
              <div className="bulk-actions-header">
                <strong>{selectedIds.size} selected</strong>
              </div>
              <div className="bulk-actions-controls">
                {hasSendPermission && (
                  <button className="btn" onClick={handleBulkRemind}>
                    Send Reminders
                  </button>
                )}
                {hasRecordPaymentPermission && (
                  <div className="bulk-mark-paid">
                    <select
                      value={paymentMethod}
                      onChange={(e) => setPaymentMethod(e.target.value)}
                    >
                      {PAYMENT_METHOD_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    <input
                      type="text"
                      placeholder="Note (optional)"
                      value={bulkNote}
                      onChange={(e) => setBulkNote(e.target.value)}
                    />
                    <button className="btn" onClick={handleBulkMarkPaid}>
                      Mark as Paid
                    </button>
                  </div>
                )}
              </div>
              {bulkActionMessage && <div className="bulk-message success">{bulkActionMessage}</div>}
              {bulkActionError && <div className="bulk-message error">{bulkActionError}</div>}
            </div>
          )}

          {/* Invoices Table */}
          {loading && <div>Loading...</div>}
          {error && <div className="error">{error}</div>}
          {!loading && !error && (
            <>
              <table className="invoices-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        checked={selectedIds.size === invoices.length && invoices.length > 0}
                        onChange={toggleSelectAll}
                      />
                    </th>
                    <th>Invoice #</th>
                    <th>Status</th>
                    <th>Issue Date</th>
                    <th>Due Date</th>
                    <th>Total</th>
                    <th>Paid</th>
                    <th>Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ textAlign: "center" }}>
                        No invoices found
                      </td>
                    </tr>
                  ) : (
                    invoices.map((invoice) => (
                      <tr key={invoice.invoice_id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedIds.has(invoice.invoice_id)}
                            onChange={() => toggleSelect(invoice.invoice_id)}
                          />
                        </td>
                        <td>
                          <a href={`/v1/admin/ui/invoices/${invoice.invoice_id}`}>
                            {invoice.invoice_number}
                          </a>
                        </td>
                        <td>
                          <span className={`status-badge status-${invoice.status.toLowerCase()}`}>
                            {invoice.status}
                          </span>
                        </td>
                        <td>{formatDate(invoice.issue_date)}</td>
                        <td>{formatDate(invoice.due_date)}</td>
                        <td>{formatMoney(invoice.total_cents, invoice.currency)}</td>
                        <td>{formatMoney(invoice.paid_cents, invoice.currency)}</td>
                        <td>{formatMoney(invoice.balance_due_cents, invoice.currency)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="pagination">
                  <button
                    className="btn secondary"
                    disabled={page <= 1}
                    onClick={() => setPage(page - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    Page {page} of {totalPages} ({total} total)
                  </span>
                  <button
                    className="btn secondary"
                    disabled={page >= totalPages}
                    onClick={() => setPage(page + 1)}
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <style>{`
        .admin-page {
          padding: 2rem;
          max-width: 1400px;
          margin: 0 auto;
        }

        .admin-content {
          margin-top: 2rem;
        }

        .admin-card {
          background: white;
          padding: 2rem;
          border-radius: 8px;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }

        .admin-card h2 {
          margin: 0 0 0.5rem 0;
        }

        .muted {
          color: #666;
          margin-bottom: 1.5rem;
        }

        .invoice-filters {
          margin-bottom: 1.5rem;
          padding: 1rem;
          background: #f5f5f5;
          border-radius: 4px;
        }

        .filter-row {
          display: flex;
          gap: 1rem;
          margin-bottom: 1rem;
        }

        .filter-row:last-child {
          margin-bottom: 0;
        }

        .form-field {
          display: flex;
          flex-direction: column;
          flex: 1;
        }

        .form-field label {
          font-size: 0.875rem;
          font-weight: 500;
          margin-bottom: 0.25rem;
        }

        .form-field input,
        .form-field select {
          padding: 0.5rem;
          border: 1px solid #ddd;
          border-radius: 4px;
        }

        .bulk-actions {
          margin-bottom: 1.5rem;
          padding: 1rem;
          background: #e3f2fd;
          border-radius: 4px;
        }

        .bulk-actions-header {
          margin-bottom: 0.5rem;
        }

        .bulk-actions-controls {
          display: flex;
          gap: 1rem;
          align-items: center;
          flex-wrap: wrap;
        }

        .bulk-mark-paid {
          display: flex;
          gap: 0.5rem;
          align-items: center;
        }

        .bulk-mark-paid select,
        .bulk-mark-paid input {
          padding: 0.5rem;
          border: 1px solid #ddd;
          border-radius: 4px;
        }

        .bulk-message {
          margin-top: 0.5rem;
          padding: 0.5rem;
          border-radius: 4px;
        }

        .bulk-message.success {
          background: #d4edda;
          color: #155724;
        }

        .bulk-message.error {
          background: #f8d7da;
          color: #721c24;
        }

        .invoices-table {
          width: 100%;
          border-collapse: collapse;
          margin-bottom: 1rem;
        }

        .invoices-table th {
          text-align: left;
          padding: 0.75rem;
          border-bottom: 2px solid #ddd;
          background: #f9f9f9;
        }

        .invoices-table td {
          padding: 0.75rem;
          border-bottom: 1px solid #eee;
        }

        .invoices-table tr:hover {
          background: #f9f9f9;
        }

        .status-badge {
          display: inline-block;
          padding: 0.25rem 0.5rem;
          border-radius: 4px;
          font-size: 0.875rem;
          font-weight: 500;
        }

        .status-draft {
          background: #e0e0e0;
          color: #424242;
        }

        .status-sent {
          background: #bbdefb;
          color: #1565c0;
        }

        .status-partial {
          background: #fff9c4;
          color: #f57f17;
        }

        .status-paid {
          background: #c8e6c9;
          color: #2e7d32;
        }

        .status-overdue {
          background: #ffccbc;
          color: #d84315;
        }

        .status-void {
          background: #e0e0e0;
          color: #757575;
        }

        .pagination {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1rem 0;
        }

        .btn {
          padding: 0.5rem 1rem;
          border: none;
          border-radius: 4px;
          background: #1976d2;
          color: white;
          cursor: pointer;
          font-size: 0.875rem;
        }

        .btn:hover:not(:disabled) {
          background: #1565c0;
        }

        .btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .btn.secondary {
          background: #757575;
        }

        .btn.secondary:hover:not(:disabled) {
          background: #616161;
        }

        .error {
          color: #d32f2f;
          padding: 0.5rem;
          background: #ffebee;
          border-radius: 4px;
        }
      `}</style>
    </div>
  );
}
