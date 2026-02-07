"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import AdminNav from "./components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "./lib/featureVisibility";
import { DEFAULT_ORG_TIMEZONE, type OrgSettingsResponse } from "./lib/orgSettings";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const KPI_PRESETS = [7, 28, 90];

type AdminMetricsResponse = {
  range_start: string;
  range_end: string;
  conversions: {
    lead_created: number;
    booking_created: number;
    booking_confirmed: number;
    job_completed: number;
  };
  revenue: { average_estimated_revenue_cents: number | null };
  accuracy: {
    sample_size: number;
    average_estimated_duration_minutes: number | null;
    average_actual_duration_minutes: number | null;
    average_delta_minutes: number | null;
  };
  financial: {
    total_revenue_cents: number;
    revenue_per_day_cents: number;
    margin_cents: number;
    average_order_value_cents: number | null;
  };
  operational: {
    crew_utilization: number | null;
    cancellation_rate: number;
    retention_30_day: number;
    retention_60_day: number;
    retention_90_day: number;
  };
};

type Lead = {
  lead_id: string;
  name: string;
  email?: string | null;
  status?: string;
};

type LeadListResponse = {
  items: Lead[];
  total: number;
  page: number;
  page_size: number;
};

type Booking = {
  booking_id: string;
  lead_id?: string | null;
  starts_at: string;
  duration_minutes: number;
  status: string;
  lead_name?: string | null;
  lead_email?: string | null;
};

type ExportEvent = {
  event_id: string;
  lead_id?: string | null;
  mode: string;
  target_url_host?: string | null;
  attempts: number;
  last_error_code?: string | null;
  created_at: string;
};

type OutboxEvent = {
  event_id: string;
  kind: string;
  attempts: number;
  status: string;
  dedupe_key: string;
  last_error?: string | null;
  next_attempt_at?: string | null;
  created_at: string;
};

function formatDateTime(value: string, timeZone: string) {
  const dt = new Date(value);
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(dt);
}

function formatYMDInTz(date: Date, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = formatter.formatToParts(date);
  const lookup: Record<string, string> = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${lookup.year}-${lookup.month}-${lookup.day}`;
}

function ymdToDate(ymd: string) {
  const [year, month, day] = ymd.split("-").map((value) => parseInt(value, 10));
  return new Date(Date.UTC(year, month - 1, day, 12, 0, 0));
}

function addDaysYMD(day: string, delta: number, timeZone: string) {
  const base = ymdToDate(day);
  base.setUTCDate(base.getUTCDate() + delta);
  return formatYMDInTz(base, timeZone);
}

function bookingLocalYMD(startsAt: string, timeZone: string) {
  return formatYMDInTz(new Date(startsAt), timeZone);
}

function statusBadge(status?: string) {
  const normalized = (status ?? "").toLowerCase();
  const className = `status-badge ${normalized}`;
  return <span className={className}>{status || "UNKNOWN"}</span>;
}

function formatCurrency(cents: number | null | undefined) {
  if (cents === null || typeof cents === "undefined") return "—";
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function formatPercentage(value: number | null | undefined) {
  if (value === null || typeof value === "undefined") return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatMinutes(value: number | null | undefined) {
  if (value === null || typeof value === "undefined") return "—";
  return `${value.toFixed(1)} min`;
}

function presetRange(days: number) {
  const end = new Date();
  const start = new Date(end);
  start.setUTCDate(end.getUTCDate() - (days - 1));
  return { from: start.toISOString(), to: end.toISOString() };
}

function isoFromDateInput(value: string) {
  const date = new Date(`${value}T00:00:00Z`);
  return date.toISOString();
}

function readableDate(isoValue: string) {
  return new Intl.DateTimeFormat("en-CA", { dateStyle: "medium" }).format(new Date(isoValue));
}

export default function AdminPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [orgSettings, setOrgSettings] = useState<OrgSettingsResponse | null>(null);
  const [orgSettingsError, setOrgSettingsError] = useState<string | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [exportEvents, setExportEvents] = useState<ExportEvent[]>([]);
  const [outboxEvents, setOutboxEvents] = useState<OutboxEvent[]>([]);
  const [metrics, setMetrics] = useState<AdminMetricsResponse | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const [metricsRange, setMetricsRange] = useState(() => presetRange(7));
  const [metricsPreset, setMetricsPreset] = useState<number | null>(7);
  const [leadStatusFilter, setLeadStatusFilter] = useState<string>("");
  const [leadsLoading, setLeadsLoading] = useState(false);
  const [bookingsLoading, setBookingsLoading] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string>(() => {
    const today = new Date();
    return formatYMDInTz(today, DEFAULT_ORG_TIMEZONE);
  });
  const [message, setMessage] = useState<string | null>(null);
  const timezoneRef = useRef(DEFAULT_ORG_TIMEZONE);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const permissionKeys = profile?.permissions ?? [];
  const canManageBookings =
    permissionKeys.includes("bookings.edit") || permissionKeys.includes("bookings.assign");
  const isReadOnly = !canManageBookings;
  const canEditLeads = permissionKeys.includes("contacts.edit") || permissionKeys.includes("leads.edit");
  const canAdminMetrics = permissionKeys.includes("admin.manage");

  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];

  const orgTimezone = orgSettings?.timezone ?? DEFAULT_ORG_TIMEZONE;

  const dashboardVisible = visibilityReady
    ? isVisible("module.dashboard", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const financeReportsVisible = visibilityReady
    ? isVisible("finance.reports", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];

    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "leads", label: "Leads", href: "/admin/leads", featureKey: "module.leads" },
      { key: "training", label: "Training", href: "/admin/training/courses", featureKey: "module.training" },
      {
        key: "notifications",
        label: "Notifications",
        href: "/admin/notifications",
        featureKey: "module.notifications_center",
      },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
      { key: "inventory", label: "Inventory", href: "/admin/inventory", featureKey: "module.inventory" },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
      {
        key: "availability-blocks",
        label: "Availability Blocks",
        href: "/admin/settings/availability-blocks",
        featureKey: "module.settings",
      },
      { key: "pricing", label: "Service Types & Pricing", href: "/admin/settings/pricing", featureKey: "module.settings" },
      {
        key: "policies",
        label: "Booking Policies",
        href: "/admin/settings/booking-policies",
        featureKey: "module.settings",
      },
      {
        key: "integrations",
        label: "Integrations",
        href: "/admin/settings/integrations",
        featureKey: "module.integrations",
      },
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "module.settings" },
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
    try {
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
    } catch (error) {
      console.error("Failed to load profile:", error);
      setProfile(null);
    }
  }, [authHeaders, password, username]);

  const loadFeatureConfig = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    try {
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
    } catch (error) {
      console.error("Failed to load feature config:", error);
      setFeatureConfig(null);
      setSettingsError("Failed to load module settings");
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    setSettingsError(null);
    try {
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
    } catch (error) {
      console.error("Failed to load UI preferences:", error);
      setUiPrefs(null);
      setSettingsError("Failed to load UI preferences");
    }
  }, [authHeaders, password, username]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadUiPrefs]);

  const loadMetrics = async () => {
    if (!username || !password) return;
    if (profile && !canAdminMetrics) {
      setMetrics(null);
      setMetricsError("Metrics require admin access");
      return;
    }
    setMetricsLoading(true);
    setMetricsError(null);
    try {
      const params = new URLSearchParams({
        from: metricsRange.from,
        to: metricsRange.to,
      });
      const response = await fetch(`${API_BASE}/v1/admin/metrics?${params.toString()}`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as AdminMetricsResponse;
        setMetrics(data);
      } else {
        setMetrics(null);
        if (response.status === 403) {
          setMetricsError("Metrics require admin access");
        } else {
          setMetricsError("Failed to load metrics");
        }
      }
    } catch (error) {
      console.error("Failed to load metrics:", error);
      setMetrics(null);
      setMetricsError("Failed to load metrics");
    } finally {
      setMetricsLoading(false);
    }
  };

  const downloadMetricsCsv = async () => {
    if (!username || !password) return;
    if (profile && !canAdminMetrics) {
      setMetricsError("Metrics require admin access");
      return;
    }
    try {
      const params = new URLSearchParams({
        from: metricsRange.from,
        to: metricsRange.to,
        format: "csv",
      });
      const response = await fetch(`${API_BASE}/v1/admin/metrics?${params.toString()}`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) {
        setMessage("CSV download failed");
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const safeFrom = metricsRange.from.split("T")[0];
      const safeTo = metricsRange.to.split("T")[0];
      link.download = `kpis-${safeFrom}-${safeTo}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Failed to download CSV:", error);
      setMessage("CSV download failed");
    }
  };

  const loadLeads = async () => {
    if (!username || !password) return;
    setLeadsLoading(true);
    try {
      const filter = leadStatusFilter ? `?status=${encodeURIComponent(leadStatusFilter)}` : "";
      const response = await fetch(`${API_BASE}/v1/admin/leads${filter}`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) return;
      const data = (await response.json()) as LeadListResponse;
      setLeads(data.items);
    } catch (error) {
      console.error("Failed to load leads:", error);
    } finally {
      setLeadsLoading(false);
    }
  };

  const loadBookings = async () => {
    if (!username || !password) return;
    setBookingsLoading(true);
    try {
      const endDate = addDaysYMD(selectedDate, 6, orgTimezone);
      const response = await fetch(
        `${API_BASE}/v1/admin/bookings?from=${selectedDate}&to=${endDate}`,
        { headers: authHeaders, cache: "no-store" }
      );
      if (!response.ok) return;
      const data = (await response.json()) as Booking[];
      setBookings(data);
    } catch (error) {
      console.error("Failed to load bookings:", error);
    } finally {
      setBookingsLoading(false);
    }
  };

  const loadExportDeadLetter = async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/export-dead-letter?limit=50`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) return;
      const data = (await response.json()) as ExportEvent[];
      setExportEvents(data);
    } catch (error) {
      console.error("Failed to load export dead letter:", error);
    }
  };

  const loadOutboxDeadLetter = async () => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/outbox/dead-letter?limit=50`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) return;
      const data = (await response.json()) as OutboxEvent[];
      setOutboxEvents(data);
    } catch (error) {
      console.error("Failed to load outbox dead letter:", error);
    }
  };

  const replayOutboxEvent = async (eventId: string) => {
    if (!username || !password) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/outbox/${eventId}/replay`, {
        method: "POST",
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        setMessage("Replay scheduled");
        void loadOutboxDeadLetter();
      } else {
        setMessage("Replay failed");
      }
    } catch (error) {
      console.error("Failed to replay outbox event:", error);
      setMessage("Replay failed");
    }
  };

  useEffect(() => {
    void loadLeads();
    void loadExportDeadLetter();
    void loadOutboxDeadLetter();
  }, [authHeaders, leadStatusFilter]);

  useEffect(() => {
    void loadBookings();
  }, [authHeaders, selectedDate]);

  useEffect(() => {
    void loadMetrics();
  }, [authHeaders, metricsRange]);

  const saveCredentials = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
      window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    }
    setMessage("Saved credentials");
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  };

  const clearCredentials = () => {
    setUsername("");
    setPassword("");
    setProfile(null);
    setFeatureConfig(null);
    setUiPrefs(null);
    setBookings([]);
    setLeads([]);
    setMetrics(null);
    setMetricsError(null);
    setSettingsError(null);
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_USERNAME_KEY);
      window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    }
    setMessage("Cleared credentials");
  };

  const updateLeadStatus = async (leadId: string, status: string) => {
    if (!canEditLeads) {
      setMessage("Read-only role cannot update leads");
      return;
    }
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/leads/${leadId}`, {
        method: "PATCH",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (response.ok) {
        setMessage("Lead updated");
        void loadLeads();
      } else {
        setMessage("Failed to update lead");
      }
    } catch (error) {
      console.error("Failed to update lead status:", error);
      setMessage("Failed to update lead");
    }
  };

  const performBookingAction = async (bookingId: string, action: "confirm" | "cancel") => {
    if (isReadOnly) {
      setMessage("Read-only role cannot change bookings");
      return;
    }
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/bookings/${bookingId}/${action}`, {
        method: "POST",
        headers: authHeaders,
      });
      if (response.ok) {
        setMessage(`Booking ${action}ed`);
        void loadBookings();
      } else {
        setMessage("Booking action failed");
      }
    } catch (error) {
      console.error("Failed to perform booking action:", error);
      setMessage("Booking action failed");
    }
  };

  const rescheduleBooking = async (bookingId: string) => {
    if (isReadOnly) {
      setMessage("Read-only role cannot reschedule bookings");
      return;
    }
    const newStart = prompt("New start (ISO8601, local time accepted)");
    if (!newStart) return;
    const duration = prompt("Time on site hours", "1.5");
    if (!duration) return;
    try {
      const response = await fetch(`${API_BASE}/v1/admin/bookings/${bookingId}/reschedule`, {
        method: "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ starts_at: newStart, time_on_site_hours: parseFloat(duration) }),
      });
      if (response.ok) {
        setMessage("Booking rescheduled");
        void loadBookings();
      } else {
        setMessage("Reschedule failed");
      }
    } catch (error) {
      console.error("Failed to reschedule booking:", error);
      setMessage("Reschedule failed");
    }
  };

  const weekView = useMemo(() => {
    const start = ymdToDate(selectedDate);
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: orgTimezone,
      weekday: "short",
      month: "short",
      day: "numeric",
    });
    const days: { label: string; date: string; items: Booking[] }[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(start);
      d.setUTCDate(start.getUTCDate() + i);
      const key = formatYMDInTz(d, orgTimezone);
      days.push({
        label: formatter.format(d),
        date: key,
        items: bookings.filter((b) => bookingLocalYMD(b.starts_at, orgTimezone) === key),
      });
    }
    return days;
  }, [bookings, orgTimezone, selectedDate]);

  const applyPresetRange = (days: number) => {
    setMetricsPreset(days);
    setMetricsRange(presetRange(days));
  };

  const updateRangeBoundary = (boundary: "from" | "to", value: string) => {
    if (!value) return;
    setMetricsPreset(null);
    setMetricsRange((previous) => ({
      ...previous,
      [boundary]: isoFromDateInput(value),
    }));
  };

  const metricsFromInput = metricsRange.from.slice(0, 10);
const metricsToInput = metricsRange.to.slice(0, 10);

if (visibilityReady && !dashboardVisible) {
  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="dashboard" />
      <div className="admin-card admin-section">
        <h1>Dashboard</h1>
        <p className="alert alert-warning">Disabled by org settings.</p>
      </div>
    </div>
  );
}

return (
  <div className="admin-page">
    <AdminNav links={navLinks} activeKey="dashboard" />
    <div className="admin-section" data-testid="admin-shell-ready">
      <h1>Admin / Dispatcher</h1>
      <p className="muted">Save credentials locally, then load leads, bookings, and exports.</p>
    </div>

    {settingsError ? <p className="alert alert-warning">{settingsError}</p> : null}
    {orgSettingsError ? <p className="alert alert-warning">{orgSettingsError}</p> : null}

    {profile ? (
      <div className={`alert ${isReadOnly ? "alert-warning" : "alert-info"}`}>
        Signed in as <strong>{profile.username}</strong> ({profile.role})
        {isReadOnly ? " · Your account is read-only without booking edit/assign permissions." : ""}
      </div>
    ) : null}

        <div className="admin-card" data-testid="admin-credentials-card">
        <div className="admin-section">
          <h2>Credentials</h2>
          <div className="admin-actions" data-testid="admin-login-form">
            <input data-testid="admin-username-input" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
            <input
              data-testid="admin-password-input"
              placeholder="Password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button data-testid="admin-save-credentials-btn" className="btn btn-primary" type="button" onClick={saveCredentials}>
              Save
            </button>
            <button data-testid="admin-clear-credentials-btn" className="btn btn-ghost" type="button" onClick={clearCredentials}>
              Clear
            </button>
          </div>
          {message ? <p className="alert alert-success" data-testid="admin-message">{message}</p> : null}
        </div>
      </div>

      {financeReportsVisible ? (
        <section className="admin-card admin-section">
          <div className="section-heading">
            <h2>KPI Dashboard</h2>
            <p className="muted">Preset ranges keep dates consistent while KPIs come directly from the backend.</p>
          </div>
        <div className="kpi-controls">
          <div className="chip-group">
            {KPI_PRESETS.map((days) => (
              <button
                key={days}
                className={`chip ${metricsPreset === days ? "chip-selected" : ""}`}
                type="button"
                onClick={() => applyPresetRange(days)}
              >
                Last {days} days
              </button>
            ))}
          </div>
          <div className="kpi-date-range">
            <label>
              <span className="label">From</span>
              <input type="date" value={metricsFromInput} onChange={(e) => updateRangeBoundary("from", e.target.value)} />
            </label>
            <label>
              <span className="label">To</span>
              <input type="date" value={metricsToInput} onChange={(e) => updateRangeBoundary("to", e.target.value)} />
            </label>
          </div>
          <div className="admin-actions" style={{ marginLeft: "auto" }}>
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => void loadMetrics()}
              disabled={metricsLoading || (profile ? !canAdminMetrics : false)}
            >
              Refresh
            </button>
            <button
              className="btn btn-secondary"
              type="button"
              onClick={() => void downloadMetricsCsv()}
              disabled={metricsLoading || !!metricsError || (profile ? !canAdminMetrics : false)}
            >
              Download CSV
            </button>
          </div>
        </div>
        {metricsError ? <p className="alert alert-warning">{metricsError}</p> : null}
        {metricsLoading ? <p className="muted">Loading metrics…</p> : null}
        {metrics ? (
          <div className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-label">Range</div>
              <div className="kpi-value">
                {readableDate(metrics.range_start)} – {readableDate(metrics.range_end)}
              </div>
              <div className="muted">UTC timestamps</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Conversions</div>
              <div className="kpi-list">
                <div className="kpi-row">
                  <span>Leads</span>
                  <strong>{metrics.conversions.lead_created.toLocaleString()}</strong>
                </div>
                <div className="kpi-row">
                  <span>Bookings</span>
                  <strong>{metrics.conversions.booking_created.toLocaleString()}</strong>
                </div>
                <div className="kpi-row">
                  <span>Confirmed</span>
                  <strong>{metrics.conversions.booking_confirmed.toLocaleString()}</strong>
                </div>
                <div className="kpi-row">
                  <span>Jobs completed</span>
                  <strong>{metrics.conversions.job_completed.toLocaleString()}</strong>
                </div>
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Financial</div>
              <div className="kpi-list">
                <div className="kpi-row">
                  <span>Total revenue</span>
                  <strong>{formatCurrency(metrics.financial.total_revenue_cents)}</strong>
                </div>
                <div className="kpi-row">
                  <span>Revenue / day</span>
                  <strong>{formatCurrency(metrics.financial.revenue_per_day_cents)}</strong>
                </div>
                <div className="kpi-row">
                  <span>Margin</span>
                  <strong>{formatCurrency(metrics.financial.margin_cents)}</strong>
                </div>
                <div className="kpi-row">
                  <span>Average order value</span>
                  <strong>{formatCurrency(metrics.financial.average_order_value_cents)}</strong>
                </div>
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Duration accuracy</div>
              <div className="kpi-list">
                <div className="kpi-row">
                  <span>Sample size</span>
                  <strong>{metrics.accuracy.sample_size.toLocaleString()}</strong>
                </div>
                <div className="kpi-row">
                  <span>Estimated</span>
                  <strong>{formatMinutes(metrics.accuracy.average_estimated_duration_minutes)}</strong>
                </div>
                <div className="kpi-row">
                  <span>Actual</span>
                  <strong>{formatMinutes(metrics.accuracy.average_actual_duration_minutes)}</strong>
                </div>
                <div className="kpi-row">
                  <span>Delta</span>
                  <strong>{formatMinutes(metrics.accuracy.average_delta_minutes)}</strong>
                </div>
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Operational</div>
              <div className="kpi-list">
                <div className="kpi-row">
                  <span>Crew utilization</span>
                  <strong>{formatPercentage(metrics.operational.crew_utilization)}</strong>
                </div>
                <div className="kpi-row">
                  <span>Cancellation rate</span>
                  <strong>{formatPercentage(metrics.operational.cancellation_rate)}</strong>
                </div>
                <div className="kpi-row">
                  <span>Retention 30 / 60 / 90</span>
                  <strong>
                    {formatPercentage(metrics.operational.retention_30_day)} / {formatPercentage(metrics.operational.retention_60_day)}
                    {" "}/ {formatPercentage(metrics.operational.retention_90_day)}
                  </strong>
                </div>
              </div>
            </div>
          </div>
        ) : metricsLoading ? null : (
          <div className="muted">Metrics will load after credentials are saved.</div>
        )}
        </section>
      ) : null}

      <div className="admin-grid">
        <section className="admin-card admin-section" data-testid="admin-leads-section">
          <div className="section-heading">
            <h2>Leads</h2>
            <p className="muted">Filter and set statuses directly.</p>
          </div>
          <div className="admin-actions" data-testid="leads-controls">
            <label style={{ width: "100%" }}>
              <span className="label">Status filter</span>
              <input
                data-testid="leads-status-filter"
                value={leadStatusFilter}
                onChange={(e) => setLeadStatusFilter(e.target.value.toUpperCase())}
                placeholder="e.g. CONTACTED"
                disabled={leadsLoading}
              />
            </label>
            <button
              data-testid="leads-refresh-btn"
              className="btn btn-ghost"
              type="button"
              onClick={() => void loadLeads()}
              disabled={leadsLoading}
            >
              {leadsLoading ? "Loading…" : "Refresh"}
            </button>
          </div>
          <table className="table-like" data-testid="leads-table">
            <thead>
              <tr>
                <th data-testid="leads-column-name">Name</th>
                <th data-testid="leads-column-email">Email</th>
                <th data-testid="leads-column-status">Status</th>
                <th data-testid="leads-column-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <tr key={lead.lead_id}>
                  <td>{lead.name}</td>
                  <td>{lead.email || "no email"}</td>
                  <td>{statusBadge(lead.status)}</td>
                  <td>
                    <div className="admin-actions">
                      {["CONTACTED", "QUOTED", "WON", "LOST"].map((status) => (
                        <button
                          key={status}
                          className="btn btn-ghost"
                          type="button"
                          disabled={!canEditLeads}
                          onClick={() => updateLeadStatus(lead.lead_id, status)}
                        >
                          {status}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="admin-card admin-section">
          <div className="section-heading">
            <h2>Export dead-letter</h2>
            <p className="muted">Failed webhook deliveries (latest 50).</p>
          </div>
          <div className="admin-actions">
            <button className="btn btn-ghost" type="button" onClick={() => void loadExportDeadLetter()}>
              Refresh
            </button>
          </div>
          {exportEvents.length === 0 ? <div className="muted">No failed exports recorded.</div> : null}
          <div className="dead-letter-list">
            {exportEvents.map((event) => (
              <div key={event.event_id} className="admin-card">
                <div className="admin-section">
                  <div className="admin-actions" style={{ justifyContent: "space-between" }}>
                    <strong>{event.mode}</strong>
                    <span className="muted">{event.target_url_host ?? "unknown host"}</span>
                  </div>
                  <div className="muted">
                    Attempts: {event.attempts} · Lead: {event.lead_id ?? "unknown"} · Created: {formatDateTime(event.created_at, orgTimezone)}
                  </div>
                  <div className="muted">Last error: {event.last_error_code || "unknown"}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="admin-card admin-section">
          <div className="section-heading">
            <h2>Outbox dead-letter</h2>
            <p className="muted">Email/webhook/export retries that exhausted max attempts.</p>
          </div>
          <div className="admin-actions">
            <button className="btn btn-ghost" type="button" onClick={() => void loadOutboxDeadLetter()}>
              Refresh
            </button>
          </div>
          {outboxEvents.length === 0 ? <div className="muted">No failed outbox events.</div> : null}
          <div className="dead-letter-list">
            {outboxEvents.map((event) => (
              <div key={event.event_id} className="admin-card">
                <div className="admin-section">
                  <div className="admin-actions" style={{ justifyContent: "space-between" }}>
                    <strong>{event.kind}</strong>
                    <span className="muted">Attempts: {event.attempts}</span>
                  </div>
                  <div className="muted">Created: {formatDateTime(event.created_at, orgTimezone)}</div>
                  <div className="muted">Last error: {event.last_error || "unknown"}</div>
                  <div className="muted">Dedupe: {event.dedupe_key}</div>
                  <div className="admin-actions">
                    <button className="btn btn-secondary" type="button" onClick={() => void replayOutboxEvent(event.event_id)}>
                      Replay
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="admin-card admin-section" data-testid="admin-bookings-section">
        <div className="section-heading">
          <h2>Bookings</h2>
          <p className="muted">Day view with actions, plus a quick week glance.</p>
        </div>
        <div className="admin-actions" data-testid="bookings-controls">
          <label>
            <span className="label">Date</span>
            <input
              data-testid="bookings-date-input"
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              disabled={bookingsLoading}
            />
          </label>
          <button
            data-testid="bookings-refresh-btn"
            className="btn btn-ghost"
            type="button"
            onClick={() => void loadBookings()}
            disabled={bookingsLoading}
          >
            {bookingsLoading ? "Loading…" : "Refresh"}
          </button>
        </div>
        <table className="table-like" data-testid="bookings-table">
          <thead>
            <tr>
              <th data-testid="bookings-column-when">When</th>
              <th data-testid="bookings-column-status">Status</th>
              <th data-testid="bookings-column-lead">Lead</th>
              <th data-testid="bookings-column-duration">Duration</th>
              <th data-testid="bookings-column-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {bookings
              .filter((booking) => bookingLocalYMD(booking.starts_at, orgTimezone) === selectedDate)
              .map((booking) => (
                <tr key={booking.booking_id}>
                  <td>{formatDateTime(booking.starts_at, orgTimezone)}</td>
                  <td>{statusBadge(booking.status)}</td>
                  <td>
                    <div>{booking.lead_name || "Unassigned"}</div>
                    <div className="muted">{booking.lead_email || "no email"}</div>
                  </td>
                  <td>{booking.duration_minutes}m</td>
                  <td>
                    <div className="admin-actions">
                      <button
                        className="btn btn-ghost"
                        type="button"
                        disabled={isReadOnly}
                        onClick={() => performBookingAction(booking.booking_id, "confirm")}
                      >
                        Confirm
                      </button>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        disabled={isReadOnly}
                        onClick={() => performBookingAction(booking.booking_id, "cancel")}
                      >
                        Cancel
                      </button>
                      <button
                        className="btn btn-secondary"
                        type="button"
                        disabled={isReadOnly}
                        onClick={() => rescheduleBooking(booking.booking_id)}
                      >
                        Reschedule
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>

        <h2 data-testid="bookings-week-view">Week view</h2>
        <div className="slot-grid">
          {weekView.map((day) => (
            <div key={day.date} className="slot-column admin-card" style={{ boxShadow: "none" }}>
              <div className="admin-section">
                <strong>{day.label}</strong>
                <div className="muted">{day.items.length} bookings</div>
                <ul style={{ paddingLeft: 16, margin: 0, display: "grid", gap: 6 }}>
                  {day.items.map((booking) => (
                    <li key={booking.booking_id}>• {formatDateTime(booking.starts_at, orgTimezone)}</li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
