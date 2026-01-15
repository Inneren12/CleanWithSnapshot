"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";

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

type InvoiceItem = {
  item_id: number;
  description: string;
  qty: number;
  unit_price_cents: number;
  line_total_cents: number;
  tax_rate: number | null;
};

type Payment = {
  payment_id: string;
  provider: string;
  provider_ref: string | null;
  method: string;
  amount_cents: number;
  currency: string;
  status: string;
  received_at: string | null;
  reference: string | null;
  created_at: string;
};

type EmailEvent = {
  event_id: string;
  email_type: string;
  recipient: string;
  subject: string;
  created_at: string;
};

type CustomerInfo = {
  customer_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  address: string | null;
};

type BookingInfo = {
  booking_id: string;
  booking_number: string | null;
  scheduled_start: string | null;
  status: string | null;
};

type Invoice = {
  invoice_id: string;
  invoice_number: string;
  order_id: string | null;
  customer_id: string | null;
  status: string;
  issue_date: string;
  due_date: string | null;
  currency: string;
  subtotal_cents: number;
  tax_cents: number;
  total_cents: number;
  paid_cents: number;
  balance_due_cents: number;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  items: InvoiceItem[];
  payments: Payment[];
  email_events: EmailEvent[];
  public_link: string | null;
  customer: CustomerInfo | null;
  booking: BookingInfo | null;
};

const PAYMENT_METHOD_OPTIONS = [
  { value: "cash", label: "Cash" },
  { value: "etransfer", label: "E-Transfer" },
  { value: "card", label: "Card" },
  { value: "other", label: "Other" },
];

function formatMoney(cents: number, currency: string): string {
  const dollars = cents / 100;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency || "CAD",
  }).format(dollars);
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getStatusColor(status: string): string {
  switch (status) {
    case "PAID":
      return "bg-green-100 text-green-800";
    case "SENT":
      return "bg-blue-100 text-blue-800";
    case "PARTIAL":
      return "bg-yellow-100 text-yellow-800";
    case "OVERDUE":
      return "bg-red-100 text-red-800";
    case "DRAFT":
      return "bg-gray-100 text-gray-800";
    case "VOID":
      return "bg-gray-300 text-gray-600";
    default:
      return "bg-gray-100 text-gray-800";
  }
}

function calculateDaysOverdue(dueDate: string | null): number | null {
  if (!dueDate) return null;
  const due = new Date(dueDate);
  const today = new Date();
  const diffTime = today.getTime() - due.getTime();
  const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
  return diffDays > 0 ? diffDays : null;
}

export default function InvoiceDetailPage() {
  const params = useParams();
  const router = useRouter();
  const invoiceId = params.invoice_id as string;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Manual payment form
  const [showPaymentForm, setShowPaymentForm] = useState(false);
  const [paymentAmount, setPaymentAmount] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [paymentReference, setPaymentReference] = useState("");

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
    try {
      const response = await fetch(`${API_BASE}/v1/admin/profile`, {
        headers: authHeaders,
      });
      if (response.ok) {
        const data: AdminProfile = await response.json();
        setProfile(data);
      }
    } catch (err) {
      console.error("Failed to load profile", err);
    }
  }, [username, password, authHeaders]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/features/config`, {
        headers: authHeaders,
      });
      if (response.ok) {
        const data: FeatureConfigResponse = await response.json();
        setFeatureConfig(data);
      }
    } catch (err) {
      console.error("Failed to load feature config", err);
    }
  }, [username, password, authHeaders]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/ui/prefs`, {
        headers: authHeaders,
      });
      if (response.ok) {
        const data: UiPrefsResponse = await response.json();
        setUiPrefs(data);
      }
    } catch (err) {
      console.error("Failed to load UI prefs", err);
    }
  }, [username, password, authHeaders]);

  const loadInvoice = useCallback(async () => {
    if (!username || !password || !invoiceId) return;
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/v1/admin/invoices/${invoiceId}`, {
        headers: authHeaders,
      });

      if (response.ok) {
        const data: Invoice = await response.json();
        setInvoice(data);
      } else if (response.status === 404) {
        setError("Invoice not found");
      } else {
        setError("Failed to load invoice");
      }
    } catch (err) {
      console.error("Failed to load invoice", err);
      setError("Network error");
    } finally {
      setLoading(false);
    }
  }, [username, password, invoiceId, authHeaders]);

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
      void loadInvoice();
    }
  }, [hasViewPermission, loadInvoice]);

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

  const handleCopyPaymentLink = useCallback(() => {
    if (!invoice?.public_link) return;
    navigator.clipboard
      .writeText(invoice.public_link)
      .then(() => {
        setActionMessage("Payment link copied to clipboard!");
        setTimeout(() => setActionMessage(null), 3000);
      })
      .catch(() => {
        setActionError("Failed to copy link");
        setTimeout(() => setActionError(null), 3000);
      });
  }, [invoice?.public_link]);

  const handleSendReminder = useCallback(async () => {
    if (!username || !password || !invoiceId) return;
    setActionMessage(null);
    setActionError(null);

    try {
      const response = await fetch(`${API_BASE}/v1/admin/invoices/${invoiceId}/remind`, {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
      });

      if (response.ok) {
        setActionMessage("Reminder sent successfully!");
        setTimeout(() => setActionMessage(null), 3000);
        void loadInvoice();
      } else {
        const errorData = await response.json();
        setActionError(errorData.detail || "Failed to send reminder");
        setTimeout(() => setActionError(null), 3000);
      }
    } catch (err) {
      setActionError("Network error sending reminder");
      setTimeout(() => setActionError(null), 3000);
    }
  }, [authHeaders, username, password, invoiceId, loadInvoice]);

  const handleRecordPayment = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!username || !password || !invoiceId) return;

      const amountCents = Math.round(parseFloat(paymentAmount) * 100);
      if (isNaN(amountCents) || amountCents <= 0) {
        setActionError("Invalid payment amount");
        setTimeout(() => setActionError(null), 3000);
        return;
      }

      setActionMessage(null);
      setActionError(null);

      try {
        const response = await fetch(`${API_BASE}/v1/admin/invoices/${invoiceId}/record-payment`, {
          method: "POST",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            amount_cents: amountCents,
            method: paymentMethod,
            reference: paymentReference || null,
          }),
        });

        if (response.ok) {
          setActionMessage("Payment recorded successfully!");
          setTimeout(() => setActionMessage(null), 3000);
          setShowPaymentForm(false);
          setPaymentAmount("");
          setPaymentReference("");
          void loadInvoice();
        } else {
          const errorData = await response.json();
          setActionError(errorData.detail || "Failed to record payment");
          setTimeout(() => setActionError(null), 3000);
        }
      } catch (err) {
        setActionError("Network error recording payment");
        setTimeout(() => setActionError(null), 3000);
      }
    },
    [authHeaders, username, password, invoiceId, paymentAmount, paymentMethod, paymentReference, loadInvoice]
  );

  const handleDownloadPDF = useCallback(() => {
    if (!username || !password || !invoiceId) return;
    const encoded = btoa(`${username}:${password}`);
    const pdfUrl = `${API_BASE}/v1/admin/invoices/${invoiceId}/pdf`;

    // Create a temporary link to trigger download
    const link = document.createElement("a");
    link.href = pdfUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    // Add auth header through fetch and blob
    fetch(pdfUrl, {
      headers: { Authorization: `Basic ${encoded}` },
    })
      .then((response) => response.blob())
      .then((blob) => {
        const url = window.URL.createObjectURL(blob);
        link.href = url;
        link.download = `${invoice?.invoice_number || "invoice"}.pdf`;
        link.click();
        window.URL.revokeObjectURL(url);
      })
      .catch(() => {
        setActionError("Failed to download PDF");
        setTimeout(() => setActionError(null), 3000);
      });
  }, [username, password, invoiceId, invoice?.invoice_number]);

  const handleCallClient = useCallback(() => {
    if (!invoice?.customer?.phone) return;
    // Remove non-numeric characters
    const cleanPhone = invoice.customer.phone.replace(/\D/g, "");
    window.location.href = `tel:${cleanPhone}`;
  }, [invoice?.customer?.phone]);

  if (!profile) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="bg-white p-8 rounded shadow-md w-full max-w-md">
          <h1 className="text-2xl font-bold mb-4">Admin Login</h1>
          <form onSubmit={handleLogin}>
            <div className="mb-4">
              <label className="block text-sm font-medium mb-1">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full border rounded px-3 py-2"
                required
              />
            </div>
            <div className="mb-4">
              <label className="block text-sm font-medium mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full border rounded px-3 py-2"
                required
              />
            </div>
            <button type="submit" className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700">
              Login
            </button>
          </form>
        </div>
      </div>
    );
  }

  if (!pageVisible) {
    return (
      <div className="min-h-screen bg-gray-50">
        <AdminNav links={navLinks} activeKey="invoices" />
        <div className="p-8">
          <p>You don&apos;t have permission to view this page.</p>
        </div>
      </div>
    );
  }

  const daysOverdue = invoice?.due_date ? calculateDaysOverdue(invoice.due_date) : null;

  return (
    <div className="min-h-screen bg-gray-50">
      <AdminNav links={navLinks} activeKey="invoices" />

      <div className="max-w-7xl mx-auto p-8">
        {/* Back button */}
        <button
          onClick={() => router.push("/admin/invoices")}
          className="mb-4 text-blue-600 hover:text-blue-800 flex items-center gap-2"
        >
          ← Back to Invoices
        </button>

        {loading && <p className="text-gray-600">Loading invoice...</p>}
        {error && <p className="text-red-600 mb-4">{error}</p>}

        {actionMessage && (
          <div className="mb-4 p-3 bg-green-100 text-green-800 rounded">{actionMessage}</div>
        )}
        {actionError && <div className="mb-4 p-3 bg-red-100 text-red-800 rounded">{actionError}</div>}

        {invoice && (
          <>
            {/* Header */}
            <div className="bg-white rounded-lg shadow p-6 mb-6">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h1 className="text-3xl font-bold mb-2">{invoice.invoice_number}</h1>
                  <div className="flex items-center gap-3">
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(invoice.status)}`}>
                      {invoice.status}
                    </span>
                    {daysOverdue && invoice.status === "OVERDUE" && (
                      <span className="text-red-600 text-sm font-medium">
                        {daysOverdue} days overdue
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-3xl font-bold text-gray-900">
                    {formatMoney(invoice.total_cents, invoice.currency)}
                  </div>
                  {invoice.balance_due_cents > 0 && (
                    <div className="text-sm text-gray-600 mt-1">
                      Balance: {formatMoney(invoice.balance_due_cents, invoice.currency)}
                    </div>
                  )}
                </div>
              </div>

              {/* Invoice Details */}
              <div className="grid grid-cols-3 gap-4 pt-4 border-t">
                <div>
                  <p className="text-sm text-gray-500">Issue Date</p>
                  <p className="font-medium">{formatDate(invoice.issue_date)}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">Due Date</p>
                  <p className="font-medium">{invoice.due_date ? formatDate(invoice.due_date) : "—"}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">Currency</p>
                  <p className="font-medium">{invoice.currency}</p>
                </div>
              </div>

              {invoice.notes && (
                <div className="mt-4 pt-4 border-t">
                  <p className="text-sm text-gray-500">Notes</p>
                  <p className="mt-1 text-gray-700">{invoice.notes}</p>
                </div>
              )}
            </div>

            {/* Customer & Booking Info */}
            <div className="grid grid-cols-2 gap-6 mb-6">
              {invoice.customer && (
                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-lg font-semibold mb-4">Customer</h2>
                  <div className="space-y-2">
                    <div>
                      <p className="text-sm text-gray-500">Name</p>
                      <p className="font-medium">{invoice.customer.name}</p>
                    </div>
                    {invoice.customer.email && (
                      <div>
                        <p className="text-sm text-gray-500">Email</p>
                        <p className="font-medium">{invoice.customer.email}</p>
                      </div>
                    )}
                    {invoice.customer.phone && (
                      <div>
                        <p className="text-sm text-gray-500">Phone</p>
                        <p className="font-medium">{invoice.customer.phone}</p>
                      </div>
                    )}
                    {invoice.customer.address && (
                      <div>
                        <p className="text-sm text-gray-500">Address</p>
                        <p className="font-medium">{invoice.customer.address}</p>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {invoice.booking && (
                <div className="bg-white rounded-lg shadow p-6">
                  <h2 className="text-lg font-semibold mb-4">Booking</h2>
                  <div className="space-y-2">
                    <div>
                      <p className="text-sm text-gray-500">Booking ID</p>
                      <p className="font-medium">{invoice.booking.booking_number || invoice.booking.booking_id}</p>
                    </div>
                    {invoice.booking.status && (
                      <div>
                        <p className="text-sm text-gray-500">Status</p>
                        <p className="font-medium">{invoice.booking.status}</p>
                      </div>
                    )}
                    {invoice.booking.scheduled_start && (
                      <div>
                        <p className="text-sm text-gray-500">Scheduled</p>
                        <p className="font-medium">{formatDateTime(invoice.booking.scheduled_start)}</p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Line Items */}
            <div className="bg-white rounded-lg shadow p-6 mb-6">
              <h2 className="text-lg font-semibold mb-4">Line Items</h2>
              <table className="w-full">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2">Description</th>
                    <th className="text-right py-2">Qty</th>
                    <th className="text-right py-2">Unit Price</th>
                    <th className="text-right py-2">Tax Rate</th>
                    <th className="text-right py-2">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {invoice.items.map((item) => (
                    <tr key={item.item_id} className="border-b">
                      <td className="py-2">{item.description}</td>
                      <td className="text-right py-2">{item.qty}</td>
                      <td className="text-right py-2">
                        {formatMoney(item.unit_price_cents, invoice.currency)}
                      </td>
                      <td className="text-right py-2">
                        {item.tax_rate ? `${(item.tax_rate * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className="text-right py-2 font-medium">
                        {formatMoney(item.line_total_cents, invoice.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t">
                    <td colSpan={4} className="text-right py-2 font-medium">
                      Subtotal
                    </td>
                    <td className="text-right py-2 font-medium">
                      {formatMoney(invoice.subtotal_cents, invoice.currency)}
                    </td>
                  </tr>
                  <tr>
                    <td colSpan={4} className="text-right py-2 font-medium">
                      Tax
                    </td>
                    <td className="text-right py-2 font-medium">
                      {formatMoney(invoice.tax_cents, invoice.currency)}
                    </td>
                  </tr>
                  <tr className="border-t">
                    <td colSpan={4} className="text-right py-2 text-lg font-bold">
                      Total
                    </td>
                    <td className="text-right py-2 text-lg font-bold">
                      {formatMoney(invoice.total_cents, invoice.currency)}
                    </td>
                  </tr>
                  {invoice.paid_cents > 0 && (
                    <>
                      <tr>
                        <td colSpan={4} className="text-right py-2 font-medium text-green-600">
                          Paid
                        </td>
                        <td className="text-right py-2 font-medium text-green-600">
                          {formatMoney(invoice.paid_cents, invoice.currency)}
                        </td>
                      </tr>
                      <tr className="border-t">
                        <td colSpan={4} className="text-right py-2 text-lg font-bold">
                          Balance Due
                        </td>
                        <td className="text-right py-2 text-lg font-bold">
                          {formatMoney(invoice.balance_due_cents, invoice.currency)}
                        </td>
                      </tr>
                    </>
                  )}
                </tfoot>
              </table>
            </div>

            {/* Payments Timeline */}
            {invoice.payments.length > 0 && (
              <div className="bg-white rounded-lg shadow p-6 mb-6">
                <h2 className="text-lg font-semibold mb-4">Payments</h2>
                <div className="space-y-3">
                  {invoice.payments
                    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
                    .map((payment) => (
                      <div key={payment.payment_id} className="border-l-4 border-blue-500 pl-4 py-2">
                        <div className="flex justify-between items-start">
                          <div>
                            <p className="font-medium">
                              {formatMoney(payment.amount_cents, payment.currency)}
                              <span className="ml-2 text-sm text-gray-600">via {payment.method}</span>
                            </p>
                            <p className="text-sm text-gray-500">
                              {formatDateTime(payment.received_at || payment.created_at)}
                            </p>
                            {payment.reference && (
                              <p className="text-sm text-gray-600">Ref: {payment.reference}</p>
                            )}
                          </div>
                          <span
                            className={`px-2 py-1 rounded text-xs font-medium ${
                              payment.status === "SUCCEEDED"
                                ? "bg-green-100 text-green-800"
                                : payment.status === "PENDING"
                                ? "bg-yellow-100 text-yellow-800"
                                : "bg-red-100 text-red-800"
                            }`}
                          >
                            {payment.status}
                          </span>
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            )}

            {/* Email/Reminders History */}
            {invoice.email_events.length > 0 && (
              <div className="bg-white rounded-lg shadow p-6 mb-6">
                <h2 className="text-lg font-semibold mb-4">Email History</h2>
                <div className="space-y-3">
                  {invoice.email_events.map((event) => (
                    <div key={event.event_id} className="border-l-4 border-purple-500 pl-4 py-2">
                      <p className="font-medium">{event.subject}</p>
                      <p className="text-sm text-gray-600">
                        To: {event.recipient} • Type: {event.email_type}
                      </p>
                      <p className="text-sm text-gray-500">{formatDateTime(event.created_at)}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Action Buttons */}
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-lg font-semibold mb-4">Actions</h2>
              <div className="flex flex-wrap gap-3">
                {invoice.public_link && (
                  <button
                    onClick={handleCopyPaymentLink}
                    className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                  >
                    Copy Payment Link
                  </button>
                )}

                {hasSendPermission && invoice.status !== "VOID" && invoice.status !== "PAID" && (
                  <button
                    onClick={handleSendReminder}
                    className="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700"
                  >
                    Send Reminder
                  </button>
                )}

                {invoice.customer?.phone && (
                  <button
                    onClick={handleCallClient}
                    className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
                  >
                    Call Client
                  </button>
                )}

                {hasRecordPaymentPermission && invoice.balance_due_cents > 0 && (
                  <button
                    onClick={() => setShowPaymentForm(!showPaymentForm)}
                    className="px-4 py-2 bg-orange-600 text-white rounded hover:bg-orange-700"
                  >
                    Record Manual Payment
                  </button>
                )}

                {hasViewPermission && (
                  <button
                    onClick={handleDownloadPDF}
                    className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700"
                  >
                    Download PDF
                  </button>
                )}
              </div>

              {/* Manual Payment Form */}
              {showPaymentForm && (
                <form onSubmit={handleRecordPayment} className="mt-6 p-4 border rounded bg-gray-50">
                  <h3 className="font-semibold mb-4">Record Manual Payment</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium mb-1">Amount ({invoice.currency})</label>
                      <input
                        type="number"
                        step="0.01"
                        value={paymentAmount}
                        onChange={(e) => setPaymentAmount(e.target.value)}
                        className="w-full border rounded px-3 py-2"
                        placeholder="0.00"
                        required
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium mb-1">Payment Method</label>
                      <select
                        value={paymentMethod}
                        onChange={(e) => setPaymentMethod(e.target.value)}
                        className="w-full border rounded px-3 py-2"
                      >
                        {PAYMENT_METHOD_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="mt-4">
                    <label className="block text-sm font-medium mb-1">Reference (optional)</label>
                    <input
                      type="text"
                      value={paymentReference}
                      onChange={(e) => setPaymentReference(e.target.value)}
                      className="w-full border rounded px-3 py-2"
                      placeholder="Check number, transaction ID, etc."
                    />
                  </div>
                  <div className="mt-4 flex gap-2">
                    <button
                      type="submit"
                      className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
                    >
                      Record Payment
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowPaymentForm(false)}
                      className="px-4 py-2 bg-gray-300 text-gray-700 rounded hover:bg-gray-400"
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
