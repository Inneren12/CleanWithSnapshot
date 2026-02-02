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

type OverdueInvoiceSummary = {
  invoice_id: string;
  invoice_number: string;
  client: string | null;
  client_email: string | null;
  amount_due: number;
  due_at: string;
  days_overdue: number;
  status: string;
};

type OverdueBucketKey = "critical" | "attention" | "recent";

type OverdueBucketSummary = {
  bucket: OverdueBucketKey;
  total_count: number;
  total_amount_due: number;
  template_key: string;
  invoices: OverdueInvoiceSummary[];
};

type OverdueSummaryResponse = {
  as_of: string;
  buckets: OverdueBucketSummary[];
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
  const [overdueSummary, setOverdueSummary] = useState<OverdueSummaryResponse | null>(null);
  const [overdueLoading, setOverdueLoading] = useState(false);
  const [overdueError, setOverdueError] = useState<string | null>(null);
  const [overdueBucketFilter, setOverdueBucketFilter] = useState<OverdueBucketKey | null>(null);
  const [asOfFilter, setAsOfFilter] = useState("");
  const [bucketActionMessage, setBucketActionMessage] = useState<Record<OverdueBucketKey, string | null>>({
    critical: null,
    attention: null,
    recent: null,
  });
  const [bucketActionError, setBucketActionError] = useState<Record<OverdueBucketKey, string | null>>({
    critical: null,
    attention: null,
    recent: null,
  });
  const [bucketActionLoading, setBucketActionLoading] = useState<Record<OverdueBucketKey, boolean>>({
    critical: false,
    attention: false,
    recent: false,
  });
  const [invoiceActionMessage, setInvoiceActionMessage] = useState<Record<string, string | null>>({});
  const [invoiceActionError, setInvoiceActionError] = useState<Record<string, string | null>>({});
  const [invoiceActionLoading, setInvoiceActionLoading] = useState<Record<string, boolean>>({});

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
  const hasSendPermission = permissionKeys.includes("invoices.send");
  const hasRecordPaymentPermission = permissionKeys.includes("payments.record");

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      {
        key: "notifications",
        label: "Notifications",
        href: "/admin/notifications",
        featureKey: "module.notifications_center",
      },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
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
    if (overdueBucketFilter) params.set("overdue_bucket", overdueBucketFilter);
    if (asOfFilter) params.set("as_of", asOfFilter);

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
  }, [
    authHeaders,
    username,
    password,
    page,
    pageSize,
    searchQuery,
    statusFilter,
    fromDate,
    toDate,
    amountMin,
    amountMax,
    overdueBucketFilter,
    asOfFilter,
  ]);

  const loadOverdueSummary = useCallback(async () => {
    if (!username || !password) return;
    setOverdueLoading(true);
    setOverdueError(null);
    const params = new URLSearchParams();
    if (asOfFilter) params.set("as_of", asOfFilter);
    try {
      const response = await fetch(
        `${API_BASE}/v1/admin/invoices/overdue_summary${params.toString() ? `?${params.toString()}` : ""}`,
        {
          headers: authHeaders,
          cache: "no-store",
        }
      );
      if (response.ok) {
        const data = (await response.json()) as OverdueSummaryResponse;
        setOverdueSummary(data);
      } else {
        setOverdueError("Failed to load overdue summary");
      }
    } catch (err) {
      setOverdueError("Network error loading overdue summary");
    } finally {
      setOverdueLoading(false);
    }
  }, [authHeaders, username, password, asOfFilter]);

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername && storedPassword) {
      setUsername(storedUsername);
      setPassword(storedPassword);
    }
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const bucket = params.get("overdue_bucket");
    if (bucket === "critical" || bucket === "attention" || bucket === "recent") {
      setOverdueBucketFilter(bucket);
      setStatusFilter("OVERDUE");
    }
    const asOf = params.get("as_of");
    if (asOf) {
      setAsOfFilter(asOf);
    }
    const status = params.get("status");
    if (status) {
      setStatusFilter(status.toUpperCase());
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

  useEffect(() => {
    if (hasViewPermission) {
      void loadOverdueSummary();
    }
  }, [hasViewPermission, loadOverdueSummary]);

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

  const handleBucketRemind = useCallback(
    async (bucket: OverdueBucketKey) => {
      if (!username || !password) return;
      setBucketActionMessage((prev) => ({ ...prev, [bucket]: null }));
      setBucketActionError((prev) => ({ ...prev, [bucket]: null }));
      setBucketActionLoading((prev) => ({ ...prev, [bucket]: true }));
      try {
        const response = await fetch(`${API_BASE}/v1/admin/invoices/overdue_remind`, {
          method: "POST",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ bucket }),
        });
        if (response.ok) {
          const result = await response.json();
          setBucketActionMessage((prev) => ({
            ...prev,
            [bucket]: `Sent ${result.succeeded.length} reminders. ${result.failed.length} failed.`,
          }));
          void loadOverdueSummary();
        } else {
          setBucketActionError((prev) => ({ ...prev, [bucket]: "Failed to send reminders" }));
        }
      } catch (err) {
        setBucketActionError((prev) => ({ ...prev, [bucket]: "Network error sending reminders" }));
      } finally {
        setBucketActionLoading((prev) => ({ ...prev, [bucket]: false }));
      }
    },
    [authHeaders, username, password, loadOverdueSummary]
  );

  const handleInvoiceRemind = useCallback(
    async (bucket: OverdueBucketKey, invoiceId: string) => {
      if (!username || !password) return;
      setInvoiceActionMessage((prev) => ({ ...prev, [invoiceId]: null }));
      setInvoiceActionError((prev) => ({ ...prev, [invoiceId]: null }));
      setInvoiceActionLoading((prev) => ({ ...prev, [invoiceId]: true }));
      try {
        const response = await fetch(`${API_BASE}/v1/admin/invoices/overdue_remind`, {
          method: "POST",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ bucket, invoice_ids: [invoiceId] }),
        });
        if (response.ok) {
          const result = await response.json();
          if (result.succeeded?.includes(invoiceId)) {
            setInvoiceActionMessage((prev) => ({ ...prev, [invoiceId]: "Reminder sent." }));
          } else {
            const failure = result.failed?.find((item: { invoice_id: string }) => item.invoice_id === invoiceId);
            setInvoiceActionError((prev) => ({
              ...prev,
              [invoiceId]: failure?.error ?? "Failed to send reminder",
            }));
          }
          void loadOverdueSummary();
        } else {
          setInvoiceActionError((prev) => ({ ...prev, [invoiceId]: "Failed to send reminder" }));
        }
      } catch (err) {
        setInvoiceActionError((prev) => ({ ...prev, [invoiceId]: "Network error sending reminder" }));
      } finally {
        setInvoiceActionLoading((prev) => ({ ...prev, [invoiceId]: false }));
      }
    },
    [authHeaders, username, password, loadOverdueSummary]
  );

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
      <div className="admin-page" data-testid="invoices-login-page">
        <div className="admin-card">
          <h2>Admin Login</h2>
          <form onSubmit={handleLogin} style={{ maxWidth: "400px" }} data-testid="invoices-login-form">
            <div className="form-field">
              <label htmlFor="username">Username</label>
              <input
                type="text"
                id="username"
                data-testid="invoices-username-input"
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
                data-testid="invoices-password-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <button type="submit" className="btn" data-testid="invoices-login-btn">
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
    <div className="admin-page" data-testid="invoices-page">
      <AdminNav links={navLinks} activeKey="invoices" />
      <div className="admin-content">
        <div className="admin-card">
          <h2 data-testid="invoices-title">Invoices</h2>
          <p className="muted">Search, filter and manage invoices with bulk actions</p>

          <section className="overdue-summary" aria-label="Overdue invoice summary" data-testid="overdue-summary">
            <div className="overdue-summary-header">
              <div>
                <h3>Overdue invoices</h3>
                <p className="muted">
                  As of {overdueSummary?.as_of ? formatDate(overdueSummary.as_of) : "today"}
                </p>
              </div>
              {overdueBucketFilter && (
                <div className="chip">Filtered: {overdueBucketFilter}</div>
              )}
            </div>
            {overdueLoading && <div>Loading overdue summary...</div>}
            {overdueError && <div className="error">{overdueError}</div>}
            {!overdueLoading && !overdueError && overdueSummary && (
              <div className="overdue-grid">
                {overdueSummary.buckets.map((bucket) => (
                  <div key={bucket.bucket} className={`overdue-card overdue-${bucket.bucket}`}>
                    <div className="overdue-card-header">
                      <div>
                        <h4>
                          {bucket.bucket === "critical" && "Critical (>14 days)"}
                          {bucket.bucket === "attention" && "Attention (7–14 days)"}
                          {bucket.bucket === "recent" && "Recent (<7 days)"}
                        </h4>
                        <div className="muted small">Template: {bucket.template_key}</div>
                      </div>
                      <div className="overdue-count">{bucket.total_count}</div>
                    </div>
                    <div className="overdue-total">
                      Total due: {formatMoney(bucket.total_amount_due, "CAD")}
                    </div>
                    <div className="overdue-list-header">Top invoices</div>
                    <ul className="overdue-list">
                      {bucket.invoices.length === 0 && (
                        <li className="muted">No overdue invoices in this bucket.</li>
                      )}
                      {bucket.invoices.map((invoice) => (
                        <li key={invoice.invoice_id} className="overdue-item">
                          <div className="overdue-item-main">
                            <div className="overdue-item-title">
                              <a href={`/admin/invoices/${invoice.invoice_id}`} className="overdue-link">
                                {invoice.invoice_number}
                              </a>
                              <span className="overdue-client">{invoice.client ?? "Unknown client"}</span>
                              {invoice.client_email && (
                                <span className="overdue-email">{invoice.client_email}</span>
                              )}
                            </div>
                            <span className="overdue-amount">
                              {formatMoney(invoice.amount_due, "CAD")}
                            </span>
                          </div>
                          <div className="overdue-item-meta">
                            Due {formatDate(invoice.due_at)} · {invoice.days_overdue} days overdue · Status{" "}
                            {invoice.status}
                          </div>
                          <div className="overdue-item-actions">
                            <a className="btn secondary" href={`/admin/invoices/${invoice.invoice_id}`}>
                              View invoice
                            </a>
                            {hasSendPermission && (
                              <button
                                className="btn"
                                type="button"
                                onClick={() => handleInvoiceRemind(bucket.bucket, invoice.invoice_id)}
                                disabled={
                                  invoiceActionLoading[invoice.invoice_id] || !invoice.client_email
                                }
                              >
                                {invoiceActionLoading[invoice.invoice_id] ? "Sending..." : "Send reminder"}
                              </button>
                            )}
                          </div>
                          {!invoice.client_email && hasSendPermission && (
                            <div className="muted small">Missing client email for reminder.</div>
                          )}
                          {invoiceActionMessage[invoice.invoice_id] && (
                            <div className="bulk-message success">{invoiceActionMessage[invoice.invoice_id]}</div>
                          )}
                          {invoiceActionError[invoice.invoice_id] && (
                            <div className="bulk-message error">{invoiceActionError[invoice.invoice_id]}</div>
                          )}
                        </li>
                      ))}
                    </ul>
                    <div className="overdue-actions">
                      {hasSendPermission && (
                        <button
                          className="btn"
                          type="button"
                          onClick={() => handleBucketRemind(bucket.bucket)}
                          disabled={bucketActionLoading[bucket.bucket] || bucket.total_count === 0}
                        >
                          {bucketActionLoading[bucket.bucket] ? "Sending..." : "Send reminders"}
                        </button>
                      )}
                      <a
                        className="btn secondary"
                        href={`/admin/invoices?status=OVERDUE&overdue_bucket=${bucket.bucket}${
                          overdueSummary.as_of ? `&as_of=${overdueSummary.as_of}` : ""
                        }`}
                      >
                        View all
                      </a>
                    </div>
                    {bucketActionMessage[bucket.bucket] && (
                      <div className="bulk-message success">{bucketActionMessage[bucket.bucket]}</div>
                    )}
                    {bucketActionError[bucket.bucket] && (
                      <div className="bulk-message error">{bucketActionError[bucket.bucket]}</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

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
                  setOverdueBucketFilter(null);
                  setAsOfFilter("");
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
          {loading && <div data-testid="invoices-loading">Loading...</div>}
          {error && (
            <div className="error" data-testid="invoices-error">
              {error}
            </div>
          )}
          <>
            <table className="invoices-table" data-testid="invoices-table">
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
                {loading ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: "center" }}>
                      Loading invoices…
                    </td>
                  </tr>
                ) : error ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: "center" }}>
                      {error}
                    </td>
                  </tr>
                ) : invoices.length === 0 ? (
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
            {!loading && !error && totalPages > 1 && (
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

        .overdue-summary {
          margin-bottom: 1.5rem;
          padding: 1.5rem;
          border: 1px solid #eee;
          border-radius: 8px;
          background: #fafafa;
        }

        .overdue-summary-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 1rem;
          margin-bottom: 1rem;
        }

        .overdue-summary h3 {
          margin: 0 0 0.25rem 0;
        }

        .chip {
          padding: 0.25rem 0.75rem;
          border-radius: 999px;
          background: #e3f2fd;
          color: #0d47a1;
          font-size: 0.75rem;
          font-weight: 600;
        }

        .overdue-grid {
          display: grid;
          gap: 1rem;
          grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        }

        .overdue-card {
          padding: 1rem;
          border-radius: 8px;
          border: 1px solid #e0e0e0;
          background: white;
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }

        .overdue-card-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 0.5rem;
        }

        .overdue-card h4 {
          margin: 0;
        }

        .overdue-count {
          font-size: 1.5rem;
          font-weight: 700;
        }

        .overdue-total {
          font-weight: 600;
        }

        .overdue-list-header {
          font-size: 0.875rem;
          font-weight: 600;
          color: #555;
        }

        .overdue-list {
          list-style: none;
          margin: 0;
          padding: 0;
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }

        .overdue-item {
          padding-bottom: 0.5rem;
          border-bottom: 1px solid #f0f0f0;
        }

        .overdue-item:last-child {
          border-bottom: none;
          padding-bottom: 0;
        }

        .overdue-item-main {
          display: flex;
          justify-content: space-between;
          gap: 0.5rem;
          font-weight: 500;
          align-items: flex-start;
        }

        .overdue-item-title {
          display: flex;
          flex-direction: column;
          gap: 0.15rem;
        }

        .overdue-link {
          color: #1976d2;
          text-decoration: none;
          font-weight: 600;
        }

        .overdue-link:hover {
          text-decoration: underline;
        }

        .overdue-email {
          font-size: 0.75rem;
          color: #777;
        }

        .overdue-item-meta {
          font-size: 0.75rem;
          color: #666;
        }

        .overdue-item-actions {
          display: flex;
          gap: 0.5rem;
          flex-wrap: wrap;
        }

        .overdue-actions {
          display: flex;
          gap: 0.5rem;
          flex-wrap: wrap;
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
