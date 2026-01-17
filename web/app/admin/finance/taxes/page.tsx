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

const TAB_DEFS = [
  { key: "gst", label: "GST" },
  { key: "instalments", label: "Instalments" },
  { key: "calendar", label: "Calendar" },
  { key: "export", label: "Export" },
] as const;

type TabKey = (typeof TAB_DEFS)[number]["key"];

type GstSummary = {
  from: string;
  to: string;
  tax_collected_cents: number;
  tax_paid_cents: number;
  tax_owed_cents: number;
  currency_code: string;
};

type TaxInstalment = {
  instalment_id: string;
  tax_type: string;
  due_on: string;
  amount_cents: number;
  paid_on: string | null;
  note: string | null;
};

type TaxCalendarEntry = {
  tax_type: string;
  label: string;
  period_start: string;
  period_end: string;
  due_on: string;
};

function formatCurrency(cents: number, currency: string) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency,
  }).format(cents / 100);
}

function formatDateInput(value: Date) {
  return value.toISOString().slice(0, 10);
}

function defaultFromDate() {
  const date = new Date();
  date.setDate(date.getDate() - 90);
  return date;
}

function defaultToDate() {
  return new Date();
}

function defaultCalendarFrom() {
  const date = new Date();
  return new Date(date.getFullYear(), 0, 1);
}

function defaultCalendarTo() {
  const date = new Date();
  return new Date(date.getFullYear(), 11, 31);
}

function parseCurrencyInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed.length) return null;
  const normalized = trimmed.replace(/,/g, "");
  const numeric = Number(normalized);
  if (!Number.isFinite(numeric)) return null;
  return Math.round(numeric * 100);
}

export default function FinanceTaxesPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("gst");

  const [gstFrom, setGstFrom] = useState(() => formatDateInput(defaultFromDate()));
  const [gstTo, setGstTo] = useState(() => formatDateInput(defaultToDate()));
  const [gstSummary, setGstSummary] = useState<GstSummary | null>(null);
  const [gstLoading, setGstLoading] = useState(false);
  const [gstError, setGstError] = useState<string | null>(null);

  const [instalments, setInstalments] = useState<TaxInstalment[]>([]);
  const [instalmentsLoading, setInstalmentsLoading] = useState(false);
  const [instalmentsError, setInstalmentsError] = useState<string | null>(null);
  const [instalmentDraft, setInstalmentDraft] = useState({
    tax_type: "GST",
    due_on: "",
    amount: "",
    paid_on: "",
    note: "",
  });
  const [instalmentEdits, setInstalmentEdits] = useState<Record<string, { paid_on: string; note: string }>>({});

  const [calendarFrom, setCalendarFrom] = useState(() => formatDateInput(defaultCalendarFrom()));
  const [calendarTo, setCalendarTo] = useState(() => formatDateInput(defaultCalendarTo()));
  const [calendarEntries, setCalendarEntries] = useState<TaxCalendarEntry[]>([]);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [calendarError, setCalendarError] = useState<string | null>(null);

  const [exportFrom, setExportFrom] = useState(() => formatDateInput(defaultFromDate()));
  const [exportTo, setExportTo] = useState(() => formatDateInput(defaultToDate()));
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportLoading, setExportLoading] = useState(false);

  const authHeaders = useMemo<Record<string, string>>(() => {
    const headers: Record<string, string> = {};
    if (!username || !password) return headers;
    headers.Authorization = `Basic ${btoa(`${username}:${password}`)}`;
    return headers;
  }, [password, username]);

  const permissionKeys = profile?.permissions ?? [];
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const visibilityReady = !!profile && !!featureConfig && !!uiPrefs;

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
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      {
        key: "finance-balance-sheet",
        label: "Balance sheet",
        href: "/admin/finance/balance-sheet",
        featureKey: "module.finance",
      },
      {
        key: "finance-cashflow",
        label: "Cashflow",
        href: "/admin/finance/cashflow",
        featureKey: "module.finance",
      },
      {
        key: "finance-pnl",
        label: "P&L",
        href: "/admin/finance/pnl",
        featureKey: "module.finance",
      },
      {
        key: "finance-expenses",
        label: "Expenses",
        href: "/admin/finance/expenses",
        featureKey: "module.finance",
      },
      {
        key: "finance-taxes",
        label: "Taxes",
        href: "/admin/finance/taxes",
        featureKey: "module.finance",
      },
      {
        key: "finance-budgets",
        label: "Budgets",
        href: "/admin/finance/budgets",
        featureKey: "module.finance",
      },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
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

  const loadGstSummary = useCallback(async () => {
    if (!username || !password) return;
    setGstLoading(true);
    setGstError(null);
    const response = await fetch(
      `${API_BASE}/v1/admin/finance/taxes/gst_summary?from=${gstFrom}&to=${gstTo}`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as GstSummary;
      setGstSummary(data);
    } else {
      setGstSummary(null);
      setGstError("Failed to load GST summary");
    }
    setGstLoading(false);
  }, [authHeaders, gstFrom, gstTo, password, username]);

  const loadInstalments = useCallback(async () => {
    if (!username || !password) return;
    setInstalmentsLoading(true);
    setInstalmentsError(null);
    const response = await fetch(
      `${API_BASE}/v1/admin/finance/taxes/instalments?from=${gstFrom}&to=${gstTo}`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as { items: TaxInstalment[] };
      setInstalments(data.items);
      setInstalmentEdits((prev) => {
        const next: Record<string, { paid_on: string; note: string }> = { ...prev };
        data.items.forEach((item) => {
          next[item.instalment_id] = {
            paid_on: item.paid_on ?? "",
            note: item.note ?? "",
          };
        });
        return next;
      });
    } else {
      setInstalments([]);
      setInstalmentsError("Failed to load instalments");
    }
    setInstalmentsLoading(false);
  }, [authHeaders, gstFrom, gstTo, password, username]);

  const loadCalendar = useCallback(async () => {
    if (!username || !password) return;
    setCalendarLoading(true);
    setCalendarError(null);
    const response = await fetch(
      `${API_BASE}/v1/admin/finance/taxes/calendar?from=${calendarFrom}&to=${calendarTo}`,
      {
        headers: authHeaders,
        cache: "no-store",
      }
    );
    if (response.ok) {
      const data = (await response.json()) as { items: TaxCalendarEntry[] };
      setCalendarEntries(data.items);
    } else {
      setCalendarEntries([]);
      setCalendarError("Failed to load calendar");
    }
    setCalendarLoading(false);
  }, [authHeaders, calendarFrom, calendarTo, password, username]);

  const createInstalment = useCallback(async () => {
    if (!username || !password) return;
    setInstalmentsError(null);
    const amountCents = parseCurrencyInput(instalmentDraft.amount);
    if (amountCents === null) {
      setInstalmentsError("Enter a valid amount");
      return;
    }
    const response = await fetch(`${API_BASE}/v1/admin/finance/taxes/instalments`, {
      method: "POST",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({
        tax_type: instalmentDraft.tax_type || "GST",
        due_on: instalmentDraft.due_on,
        amount_cents: amountCents,
        paid_on: instalmentDraft.paid_on || null,
        note: instalmentDraft.note || null,
      }),
    });
    if (!response.ok) {
      setInstalmentsError("Failed to create instalment");
      return;
    }
    setInstalmentDraft({ tax_type: "GST", due_on: "", amount: "", paid_on: "", note: "" });
    await loadInstalments();
  }, [authHeaders, instalmentDraft, loadInstalments, password, username]);

  const updateInstalment = useCallback(
    async (instalmentId: string) => {
      if (!username || !password) return;
      const edit = instalmentEdits[instalmentId];
      if (!edit) return;
      const response = await fetch(`${API_BASE}/v1/admin/finance/taxes/instalments/${instalmentId}`, {
        method: "PATCH",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({
          paid_on: edit.paid_on || null,
          note: edit.note || null,
        }),
      });
      if (!response.ok) {
        setInstalmentsError("Failed to update instalment");
        return;
      }
      await loadInstalments();
    },
    [authHeaders, instalmentEdits, loadInstalments, password, username]
  );

  const runExport = useCallback(async () => {
    if (!username || !password) return;
    setExportLoading(true);
    setExportError(null);
    const response = await fetch(
      `${API_BASE}/v1/admin/finance/taxes/export?from=${exportFrom}&to=${exportTo}`,
      {
        headers: authHeaders,
      }
    );
    if (!response.ok) {
      setExportError("Failed to export GST package");
      setExportLoading(false);
      return;
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `gst_export_${exportFrom}_${exportTo}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
    setExportLoading(false);
  }, [authHeaders, exportFrom, exportTo, password, username]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (!username || !password) return;
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (activeTab === "gst") {
      void loadGstSummary();
    }
    if (activeTab === "instalments") {
      void loadInstalments();
    }
    if (activeTab === "calendar") {
      void loadCalendar();
    }
  }, [activeTab, loadCalendar, loadGstSummary, loadInstalments]);

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="finance-taxes" />
      <div className="admin-section">
        <h1>Finance · Taxes</h1>
        <p className="muted">GST summary and instalments use invoice tax snapshots and expense tax fields.</p>
      </div>

      {settingsError ? <p className="alert alert-warning">{settingsError}</p> : null}

      <div className="admin-card admin-section">
        <div className="chip-group">
          {TAB_DEFS.map((tab) => (
            <button
              key={tab.key}
              className={`chip ${activeTab === tab.key ? "chip-selected" : ""}`}
              type="button"
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "gst" ? (
        <div className="admin-card admin-section">
          <div className="section-heading">
            <h2>GST summary</h2>
            <p className="muted">Collected taxes are allocated from invoice payments.</p>
          </div>
          <div className="admin-actions">
            <label>
              <span className="label">From</span>
              <input type="date" value={gstFrom} onChange={(e) => setGstFrom(e.target.value)} />
            </label>
            <label>
              <span className="label">To</span>
              <input type="date" value={gstTo} onChange={(e) => setGstTo(e.target.value)} />
            </label>
            <button className="btn btn-secondary" type="button" onClick={() => void loadGstSummary()}>
              Refresh
            </button>
          </div>
          {gstError ? <p className="alert alert-warning">{gstError}</p> : null}
          {gstLoading ? <p className="muted">Loading summary…</p> : null}
          {gstSummary ? (
            <div className="kpi-grid">
              <div className="kpi-card">
                <div className="kpi-label">Collected</div>
                <div className="kpi-value">
                  {formatCurrency(gstSummary.tax_collected_cents, gstSummary.currency_code)}
                </div>
                <div className="muted">Payments in range</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-label">Paid</div>
                <div className="kpi-value">{formatCurrency(gstSummary.tax_paid_cents, gstSummary.currency_code)}</div>
                <div className="muted">Expense tax in range</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-label">Owed</div>
                <div className="kpi-value">{formatCurrency(gstSummary.tax_owed_cents, gstSummary.currency_code)}</div>
                <div className="muted">Collected minus paid</div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {activeTab === "instalments" ? (
        <div className="admin-card admin-section">
          <div className="section-heading">
            <h2>Instalments</h2>
            <p className="muted">Record instalment payments and mark them as paid.</p>
          </div>
          <div className="admin-actions" style={{ flexWrap: "wrap" }}>
            <input
              placeholder="Tax type"
              value={instalmentDraft.tax_type}
              onChange={(e) => setInstalmentDraft((prev) => ({ ...prev, tax_type: e.target.value }))}
            />
            <input
              type="date"
              value={instalmentDraft.due_on}
              onChange={(e) => setInstalmentDraft((prev) => ({ ...prev, due_on: e.target.value }))}
            />
            <input
              placeholder="Amount"
              value={instalmentDraft.amount}
              onChange={(e) => setInstalmentDraft((prev) => ({ ...prev, amount: e.target.value }))}
            />
            <input
              type="date"
              value={instalmentDraft.paid_on}
              onChange={(e) => setInstalmentDraft((prev) => ({ ...prev, paid_on: e.target.value }))}
            />
            <input
              placeholder="Note"
              value={instalmentDraft.note}
              onChange={(e) => setInstalmentDraft((prev) => ({ ...prev, note: e.target.value }))}
            />
            <button className="btn btn-primary" type="button" onClick={() => void createInstalment()}>
              Add instalment
            </button>
          </div>
          {instalmentsError ? <p className="alert alert-warning">{instalmentsError}</p> : null}
          {instalmentsLoading ? <p className="muted">Loading instalments…</p> : null}
          {instalments.length ? (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Tax</th>
                    <th>Due</th>
                    <th>Amount</th>
                    <th>Paid on</th>
                    <th>Note</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {instalments.map((item) => {
                    const edit = instalmentEdits[item.instalment_id] ?? { paid_on: "", note: "" };
                    return (
                      <tr key={item.instalment_id}>
                        <td>{item.tax_type}</td>
                        <td>{item.due_on}</td>
                        <td>{formatCurrency(item.amount_cents, "CAD")}</td>
                        <td>
                          <input
                            type="date"
                            value={edit.paid_on}
                            onChange={(e) =>
                              setInstalmentEdits((prev) => ({
                                ...prev,
                                [item.instalment_id]: { ...edit, paid_on: e.target.value },
                              }))
                            }
                          />
                        </td>
                        <td>
                          <input
                            value={edit.note}
                            onChange={(e) =>
                              setInstalmentEdits((prev) => ({
                                ...prev,
                                [item.instalment_id]: { ...edit, note: e.target.value },
                              }))
                            }
                          />
                        </td>
                        <td>
                          <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => void updateInstalment(item.instalment_id)}
                          >
                            Save
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No instalments yet.</p>
          )}
        </div>
      ) : null}

      {activeTab === "calendar" ? (
        <div className="admin-card admin-section">
          <div className="section-heading">
            <h2>Tax calendar</h2>
            <p className="muted">Default Alberta GST filing schedule (quarterly).</p>
          </div>
          <div className="admin-actions">
            <label>
              <span className="label">From</span>
              <input type="date" value={calendarFrom} onChange={(e) => setCalendarFrom(e.target.value)} />
            </label>
            <label>
              <span className="label">To</span>
              <input type="date" value={calendarTo} onChange={(e) => setCalendarTo(e.target.value)} />
            </label>
            <button className="btn btn-secondary" type="button" onClick={() => void loadCalendar()}>
              Refresh
            </button>
          </div>
          {calendarError ? <p className="alert alert-warning">{calendarError}</p> : null}
          {calendarLoading ? <p className="muted">Loading calendar…</p> : null}
          {calendarEntries.length ? (
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Label</th>
                    <th>Period</th>
                    <th>Due on</th>
                  </tr>
                </thead>
                <tbody>
                  {calendarEntries.map((entry) => (
                    <tr key={`${entry.tax_type}-${entry.due_on}`}>
                      <td>{entry.label}</td>
                      <td>
                        {entry.period_start} → {entry.period_end}
                      </td>
                      <td>{entry.due_on}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No due dates in range.</p>
          )}
        </div>
      ) : null}

      {activeTab === "export" ? (
        <div className="admin-card admin-section">
          <div className="section-heading">
            <h2>Export package</h2>
            <p className="muted">Download a ZIP of GST summary, payment allocations, and expenses.</p>
          </div>
          <div className="admin-actions">
            <label>
              <span className="label">From</span>
              <input type="date" value={exportFrom} onChange={(e) => setExportFrom(e.target.value)} />
            </label>
            <label>
              <span className="label">To</span>
              <input type="date" value={exportTo} onChange={(e) => setExportTo(e.target.value)} />
            </label>
            <button className="btn btn-primary" type="button" onClick={() => void runExport()} disabled={exportLoading}>
              {exportLoading ? "Preparing…" : "Download ZIP"}
            </button>
          </div>
          {exportError ? <p className="alert alert-warning">{exportError}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
