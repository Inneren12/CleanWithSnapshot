"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../components/AdminNav";
import { type AdminProfile, type FeatureConfigResponse, type UiPrefsResponse, isVisible } from "../../lib/featureVisibility";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type OpsDashboardAlert = {
  type: string;
  severity: string;
  title: string;
  description: string;
  entity_ref?: Record<string, unknown> | null;
  actions: OpsDashboardAlertAction[];
  created_at?: string | null;
};

type OpsDashboardAlertAction = {
  label: string;
  href: string;
  method?: string;
};

type OpsDashboardUpcomingEvent = {
  booking_id: string;
  starts_at: string;
  ends_at: string;
  status: string;
  team_id?: number | null;
  worker_id?: number | null;
};

type OpsDashboardWorkerAvailability = {
  worker_id: number;
  name?: string | null;
  available: boolean;
  next_available_at?: string | null;
};

type OpsDashboardBookingStatusTotals = {
  total: number;
  pending: number;
  confirmed: number;
  done: number;
  cancelled: number;
};

type OpsDashboardBookingStatusBand = {
  label: string;
  count: number;
};

type OpsDashboardBookingStatusToday = {
  totals: OpsDashboardBookingStatusTotals;
  bands: OpsDashboardBookingStatusBand[];
};

type OpsDashboardResponse = {
  as_of: string;
  org_timezone: string;
  critical_alerts: OpsDashboardAlert[];
  upcoming_events: OpsDashboardUpcomingEvent[];
  worker_availability: OpsDashboardWorkerAvailability[];
  booking_status_today: OpsDashboardBookingStatusToday;
};

function formatDateTime(value: string, timeZone: string) {
  const dt = new Date(value);
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(dt);
}

export default function OpsDashboardPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [opsData, setOpsData] = useState<OpsDashboardResponse | null>(null);
  const [opsLoading, setOpsLoading] = useState(false);
  const [opsError, setOpsError] = useState<string | null>(null);
  const [dismissedAlerts, setDismissedAlerts] = useState<Set<string>>(new Set());

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const permissionKeys = profile?.permissions ?? [];
  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];

  const dashboardVisible = visibilityReady
    ? isVisible("module.dashboard", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "ops-dashboard", label: "Ops Dashboard", href: "/admin/dashboard/ops", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
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
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "api.settings" },
      { key: "roles", label: "Roles & Permissions", href: "/admin/iam/roles", featureKey: "module.teams" },
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

  const loadOpsDashboard = useCallback(async () => {
    if (!username || !password || !profile) return;
    setOpsLoading(true);
    setOpsError(null);
    try {
      const response = await fetch(`${API_BASE}/v1/admin/dashboard/ops`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (response.ok) {
        const data = (await response.json()) as OpsDashboardResponse;
        setOpsData(data);
      } else {
        setOpsData(null);
        setOpsError("Failed to load ops dashboard data");
      }
    } catch (error) {
      console.error("Failed to load ops dashboard", error);
      setOpsData(null);
      setOpsError("Failed to load ops dashboard data");
    } finally {
      setOpsLoading(false);
    }
  }, [authHeaders, password, profile, username]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs]);

  useEffect(() => {
    if (!profile || (visibilityReady && !dashboardVisible)) return;
    void loadOpsDashboard();
  }, [dashboardVisible, loadOpsDashboard, profile, visibilityReady]);

  const handleSaveCredentials = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
      window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    }
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    setStatusMessage("Saved credentials");
  };

  const handleClearCredentials = () => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_USERNAME_KEY);
      window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    }
    setUsername("");
    setPassword("");
    setProfile(null);
    setFeatureConfig(null);
    setUiPrefs(null);
    setOpsData(null);
    setOpsError(null);
    setStatusMessage("Cleared credentials");
  };

  const availableWorkers = opsData?.worker_availability.filter((worker) => worker.available).length ?? 0;
  const totalWorkers = opsData?.worker_availability.length ?? 0;
  const bookingTotals = opsData?.booking_status_today.totals;
  const timezoneLabel = opsData?.org_timezone ?? "UTC";
  const asOfLabel = opsData
    ? `As of ${formatDateTime(opsData.as_of, opsData.org_timezone)} (${opsData.org_timezone})`
    : "Awaiting ops data.";
  const visibleAlerts = useMemo(
    () => opsData?.critical_alerts.filter((alert) => !dismissedAlerts.has(alert.type)) ?? [],
    [dismissedAlerts, opsData?.critical_alerts]
  );

  const quickActions = [
    {
      key: "create-booking",
      label: "Create booking",
      description: "Schedule a new visit.",
      permission: "bookings.edit",
    },
    {
      key: "assign-worker",
      label: "Assign worker",
      description: "Place a worker on a booking.",
      permission: "bookings.assign",
    },
    {
      key: "follow-up-lead",
      label: "Follow up lead",
      description: "Open client contact record.",
      permission: "contacts.edit",
    },
    {
      key: "send-invoice",
      label: "Send invoice reminder",
      description: "Notify outstanding invoices.",
      permission: "invoices.send",
    },
    {
      key: "run-export",
      label: "Run export",
      description: "Generate daily ops export.",
      permission: "exports.run",
    },
  ];

  const alertClassName = useCallback((severity: string) => {
    switch (severity) {
      case "critical":
      case "high":
        return "alert alert-warning";
      case "info":
      case "low":
        return "alert alert-info";
      default:
        return "alert alert-warning";
    }
  }, []);

  const handleDismissAlert = useCallback((alertType: string) => {
    setDismissedAlerts((previous) => {
      const next = new Set(previous);
      next.add(alertType);
      return next;
    });
  }, []);

  if (visibilityReady && !dashboardVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="ops-dashboard" />
        <div className="admin-card admin-section">
          <h1>Ops Dashboard</h1>
          <p className="alert alert-warning">Disabled by org settings.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="ops-dashboard" />
      <div className="admin-section">
        <h1>Ops Dashboard</h1>
        <p className="muted">Operational overview for today and the next 24 hours.</p>
      </div>

      {settingsError ? <p className="alert alert-warning">{settingsError}</p> : null}

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
        {statusMessage ? <p className="alert alert-success">{statusMessage}</p> : null}
      </div>

      {opsError ? <p className="alert alert-warning">{opsError}</p> : null}
      {opsLoading ? <p className="muted">Loading ops dashboard…</p> : null}

      <div className="admin-grid">
        <section className="admin-card admin-section">
          <div className="section-heading">
            <h2>Critical Alerts</h2>
            <p className="muted">Escalations needing immediate attention.</p>
          </div>
          <p className="muted">{asOfLabel}</p>
          {opsData ? (
            visibleAlerts.length === 0 ? (
              <p className="muted">No critical alerts reported.</p>
            ) : (
              <div className="admin-actions" style={{ flexDirection: "column", alignItems: "stretch", gap: "12px" }}>
                {visibleAlerts.map((alert) => (
                  <div key={alert.type} className={alertClassName(alert.severity)}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: "12px" }}>
                      <div>
                        <strong>{alert.title}</strong>
                        <div className="muted">{alert.description}</div>
                      </div>
                      <span className="muted">{alert.severity.toUpperCase()}</span>
                    </div>
                    {alert.actions.length > 0 ? (
                      <div className="admin-actions" style={{ marginTop: "8px", flexWrap: "wrap" }}>
                        {alert.actions.map((action) => (
                          <a key={action.href} className="btn btn-secondary" href={action.href}>
                            {action.label}
                          </a>
                        ))}
                        <button className="btn btn-ghost" type="button" onClick={() => handleDismissAlert(alert.type)}>
                          Dismiss
                        </button>
                      </div>
                    ) : (
                      <div className="admin-actions" style={{ marginTop: "8px" }}>
                        <button className="btn btn-ghost" type="button" onClick={() => handleDismissAlert(alert.type)}>
                          Dismiss
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )
          ) : (
            <p className="muted">Alerts will populate after credentials are saved.</p>
          )}
        </section>

        <section className="admin-card admin-section">
          <div className="section-heading">
            <h2>Upcoming 24h</h2>
            <p className="muted">Next 24 hours in {timezoneLabel}.</p>
          </div>
          {opsData ? (
            <p className="muted">
              {opsData.upcoming_events.length} upcoming booking(s). Timeline view placeholder.
            </p>
          ) : (
            <p className="muted">Upcoming events will appear here.</p>
          )}
        </section>

        <section className="admin-card admin-section">
          <div className="section-heading">
            <h2>Workers Availability Matrix</h2>
            <p className="muted">Staffing status for today.</p>
          </div>
          {opsData ? (
            <p className="muted">
              {availableWorkers} of {totalWorkers} workers available. Matrix placeholder.
            </p>
          ) : (
            <p className="muted">Availability matrix will load after ops data.</p>
          )}
        </section>

        <section className="admin-card admin-section">
          <div className="section-heading">
            <h2>Booking Status Overview</h2>
            <p className="muted">Today&apos;s totals by status.</p>
          </div>
          {bookingTotals ? (
            <div className="muted">
              Total: {bookingTotals.total} · Pending: {bookingTotals.pending} · Confirmed: {bookingTotals.confirmed} ·
              Done: {bookingTotals.done} · Cancelled: {bookingTotals.cancelled}
            </div>
          ) : (
            <p className="muted">Status summary will populate here.</p>
          )}
        </section>

        <section className="admin-card admin-section">
          <div className="section-heading">
            <h2>Quick Actions</h2>
            <p className="muted">Shortcuts are disabled without permission.</p>
          </div>
          <div className="admin-actions" style={{ flexDirection: "column", alignItems: "stretch" }}>
            {quickActions.map((action) => {
              const allowed = permissionKeys.includes(action.permission);
              return (
                <button
                  key={action.key}
                  className="btn btn-secondary"
                  type="button"
                  disabled={!allowed}
                  title={allowed ? "Ready" : "Permission required"}
                >
                  {action.label} · <span className="muted">{action.description}</span>
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
