"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
  starts_at: string;
  title: string;
  entity_ref?: Record<string, unknown> | null;
  actions: OpsDashboardAlertAction[];
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

type OpsDashboardHeroMetrics = {
  bookings_today: number;
  revenue_today_cents: number;
  workers_available: number;
  workers_total: number;
  worker_rating_avg?: number | null;
};

type OpsDashboardRevenueDay = {
  date: string;
  revenue_cents: number;
};

type OpsDashboardRevenueGoal = {
  goal_cents: number;
  remaining_cents: number;
};

type OpsDashboardRevenueWeek = {
  week_start: string;
  week_end: string;
  days: OpsDashboardRevenueDay[];
  total_revenue_cents: number;
  currency: string;
  goal?: OpsDashboardRevenueGoal;
};

type OpsDashboardQualityToday = {
  avg_rating?: number | null;
  reviews_count: number;
  open_critical_issues: number;
};

type OpsDashboardTopWorker = {
  worker_id: number;
  name?: string | null;
  team_id?: number | null;
  team_name?: string | null;
  bookings_count: number;
  revenue_cents: number;
};

type OpsDashboardTopClient = {
  client_id: string;
  name?: string | null;
  email?: string | null;
  bookings_count: number;
  revenue_cents: number;
};

type OpsDashboardTopTeam = {
  team_id: number;
  name: string;
  bookings_count: number;
  revenue_cents: number;
};

type OpsDashboardTopService = {
  label: string;
  bookings_count: number;
  revenue_cents: number;
  share_of_revenue: number;
};

type OpsDashboardTopPerformers = {
  month_start: string;
  month_end: string;
  total_revenue_cents: number;
  workers: OpsDashboardTopWorker[];
  clients: OpsDashboardTopClient[];
  teams: OpsDashboardTopTeam[];
  services: OpsDashboardTopService[];
};

type OpsDashboardResponse = {
  as_of: string;
  org_timezone: string;
  org_currency: string;
  critical_alerts: OpsDashboardAlert[];
  upcoming_events: OpsDashboardUpcomingEvent[];
  worker_availability: OpsDashboardWorkerAvailability[];
  booking_status_today: OpsDashboardBookingStatusToday;
  hero_metrics: OpsDashboardHeroMetrics;
  revenue_week: OpsDashboardRevenueWeek;
  quality_today?: OpsDashboardQualityToday | null;
  top_performers: OpsDashboardTopPerformers;
};

type ActivityFeedAction = {
  label: string;
  href: string;
};

type ActivityFeedItem = {
  event_id: string;
  kind: string;
  title: string;
  description?: string | null;
  timestamp: string;
  entity_ref?: Record<string, unknown> | null;
  action?: ActivityFeedAction | null;
};

type ActivityFeedResponse = {
  as_of: string;
  items: ActivityFeedItem[];
};

const ACTIVITY_POLL_INTERVAL_MS = 45000;
const ACTIVITY_DEFAULT_LIMIT = 6;
const ACTIVITY_EXPANDED_LIMIT = 50;

function formatDateTime(value: string, timeZone: string) {
  const dt = new Date(value);
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(dt);
}

function formatDateForQuery(value: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone,
  }).formatToParts(value);
  const lookup = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${lookup.year}-${lookup.month}-${lookup.day}`;
}

function formatCurrency(valueCents: number, currency: string) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(valueCents / 100);
}

function formatWeekday(value: string, timeZone: string) {
  const dt = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("en-CA", {
    weekday: "short",
    timeZone,
  }).format(dt);
}

function formatMonthLabel(value: string, timeZone: string) {
  const dt = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("en-CA", {
    month: "long",
    year: "numeric",
    timeZone,
  }).format(dt);
}

function formatPercent(value: number) {
  return new Intl.NumberFormat("en-CA", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
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
  const [activityItems, setActivityItems] = useState<ActivityFeedItem[]>([]);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [activityExpanded, setActivityExpanded] = useState(false);
  const latestActivityTimestampRef = useRef<string | null>(null);

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
  const qualityVisible = visibilityReady
    ? isVisible("module.quality", permissionKeys, featureOverrides, hiddenKeys) &&
      permissionKeys.includes("quality.view")
    : false;

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "ops-dashboard", label: "Ops Dashboard", href: "/admin/dashboard/ops", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "teams", label: "Teams", href: "/admin/teams", featureKey: "module.teams" },
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

  const mergeActivityItems = useCallback((existing: ActivityFeedItem[], incoming: ActivityFeedItem[]) => {
    if (incoming.length === 0) return existing;
    const merged = new Map<string, ActivityFeedItem>();
    [...incoming, ...existing].forEach((item) => {
      merged.set(item.event_id, item);
    });
    return Array.from(merged.values()).sort(
      (left, right) => new Date(right.timestamp).getTime() - new Date(left.timestamp).getTime()
    );
  }, []);

  const loadActivityFeed = useCallback(
    async (mode: "initial" | "poll" = "initial") => {
      if (!username || !password || !profile) return;
      if (mode === "initial") {
        setActivityLoading(true);
      }
      setActivityError(null);
      try {
        const params = new URLSearchParams();
        if (mode === "poll" && latestActivityTimestampRef.current) {
          params.set("since", latestActivityTimestampRef.current);
        }
        params.set(
          "limit",
          String(activityExpanded ? ACTIVITY_EXPANDED_LIMIT : Math.max(ACTIVITY_DEFAULT_LIMIT, 20))
        );
        const response = await fetch(`${API_BASE}/v1/admin/activity?${params.toString()}`, {
          headers: authHeaders,
          cache: "no-store",
        });
        if (!response.ok) {
          setActivityError("Failed to load activity feed");
          return;
        }
        const data = (await response.json()) as ActivityFeedResponse;
        if (mode === "poll") {
          setActivityItems((previous) => mergeActivityItems(previous, data.items));
        } else {
          setActivityItems(data.items);
        }
        if (data.items.length > 0) {
          latestActivityTimestampRef.current = data.items[0].timestamp;
        }
      } catch (error) {
        console.error("Failed to load activity feed", error);
        setActivityError("Failed to load activity feed");
      } finally {
        if (mode === "initial") {
          setActivityLoading(false);
        }
      }
    },
    [activityExpanded, authHeaders, mergeActivityItems, password, profile, username]
  );

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

  useEffect(() => {
    if (!profile || (visibilityReady && !dashboardVisible)) return;
    void loadActivityFeed("initial");
  }, [dashboardVisible, loadActivityFeed, profile, visibilityReady]);

  useEffect(() => {
    if (!profile || (visibilityReady && !dashboardVisible)) return;
    const interval = window.setInterval(() => {
      void loadActivityFeed("poll");
    }, ACTIVITY_POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [dashboardVisible, loadActivityFeed, profile, visibilityReady]);

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
    setActivityItems([]);
    setActivityError(null);
    setActivityLoading(false);
    latestActivityTimestampRef.current = null;
    setStatusMessage("Cleared credentials");
  };

  const availableWorkers = opsData?.worker_availability.filter((worker) => worker.available).length ?? 0;
  const totalWorkers = opsData?.worker_availability.length ?? 0;
  const bookingTotals = opsData?.booking_status_today.totals;
  const timezoneLabel = opsData?.org_timezone ?? "UTC";
  const currencyLabel = opsData?.org_currency ?? "CAD";
  const topPerformers = opsData?.top_performers ?? null;
  const qualityToday = opsData?.quality_today ?? null;
  const monthLabel = topPerformers ? formatMonthLabel(topPerformers.month_start, timezoneLabel) : "";
  const asOfLabel = opsData
    ? `As of ${formatDateTime(opsData.as_of, opsData.org_timezone)} (${opsData.org_timezone})`
    : "Awaiting ops data.";
  const activityVisibleItems = activityExpanded
    ? activityItems
    : activityItems.slice(0, ACTIVITY_DEFAULT_LIMIT);
  const visibleAlerts = useMemo(
    () => opsData?.critical_alerts.filter((alert) => !dismissedAlerts.has(alert.type)) ?? [],
    [dismissedAlerts, opsData?.critical_alerts]
  );

  const scheduleDate = formatDateForQuery(new Date(), timezoneLabel);
  const quickActions = [
    {
      key: "create-booking",
      label: "Create booking",
      description: "Open schedule with today selected.",
      permission: "bookings.edit",
      featureKey: "module.schedule",
      href: `/admin/schedule?date=${scheduleDate}`,
      disabled: false,
    },
    {
      key: "new-invoice",
      label: "New invoice",
      description: "Go to invoices to start a draft.",
      permission: "invoices.edit",
      featureKey: "module.invoices",
      href: "/admin/invoices",
      disabled: false,
    },
    {
      key: "call-client",
      label: "Call client",
      description: "Open schedule to find client details.",
      permission: "bookings.view",
      featureKey: "module.schedule",
      href: `/admin/schedule?date=${scheduleDate}`,
      disabled: false,
    },
    {
      key: "sms-workers",
      label: "SMS workers",
      description: "Messaging center not enabled yet.",
      permission: "core.view",
      featureKey: "module.notifications_center",
      href: "/admin/notifications",
      disabled: true,
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

      {opsData ? (
        <>
          <div className="hero-metrics-grid">
            <section className="admin-card admin-section">
              <div className="muted">Bookings today</div>
              <div className="hero-metric-value">{opsData.hero_metrics.bookings_today}</div>
              <div className="muted">{timezoneLabel} schedule</div>
            </section>
            <section className="admin-card admin-section">
              <div className="muted">Revenue today</div>
              <div className="hero-metric-value">
                {formatCurrency(opsData.hero_metrics.revenue_today_cents, currencyLabel)}
              </div>
              <div className="muted">{timezoneLabel} totals</div>
            </section>
            <section className="admin-card admin-section">
              <div className="muted">Workers available</div>
              <div className="hero-metric-value">
                {opsData.hero_metrics.workers_available} / {opsData.hero_metrics.workers_total}
              </div>
              <div className="muted">Currently free</div>
            </section>
            <section className="admin-card admin-section">
              <div className="muted">Average rating</div>
              <div className="hero-metric-value">
                {opsData.hero_metrics.worker_rating_avg ? opsData.hero_metrics.worker_rating_avg.toFixed(1) : "—"}
              </div>
              <div className="muted">Worker reviews</div>
            </section>
          </div>

          <section className="admin-card admin-section revenue-chart">
            <div className="section-heading">
              <h2>Revenue (Mon–Sun)</h2>
              <p className="muted">
                Week of {opsData.revenue_week.week_start} · Total{" "}
                {formatCurrency(opsData.revenue_week.total_revenue_cents, opsData.revenue_week.currency)}
              </p>
            </div>
            <div className="revenue-chart-bars">
              {(() => {
                const maxRevenue = Math.max(
                  ...opsData.revenue_week.days.map((day) => day.revenue_cents),
                  1
                );
                return opsData.revenue_week.days.map((day) => {
                  const heightPercent = Math.max((day.revenue_cents / maxRevenue) * 100, 2);
                  return (
                    <div key={day.date} className="revenue-chart-bar">
                      <div className="revenue-bar" style={{ height: `${heightPercent}%` }} />
                      <div className="revenue-bar-label">{formatWeekday(day.date, timezoneLabel)}</div>
                      <div className="muted revenue-bar-value">
                        {formatCurrency(day.revenue_cents, opsData.revenue_week.currency)}
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
            {opsData.revenue_week.goal ? (
              <div className="muted">
                Goal: {formatCurrency(opsData.revenue_week.goal.goal_cents, opsData.revenue_week.currency)} · Remaining{" "}
                {formatCurrency(opsData.revenue_week.goal.remaining_cents, opsData.revenue_week.currency)}
              </div>
            ) : null}
          </section>
        </>
      ) : (
        <div className="admin-card admin-section">
          <p className="muted">Hero metrics and revenue trends will load after ops data.</p>
        </div>
      )}

      <div className="ops-dashboard-layout">
        <div className="ops-dashboard-main">
          <div className="admin-grid">
            {qualityVisible ? (
              <section className="admin-card admin-section">
                <div className="section-heading">
                  <h2>Quality today</h2>
                  <p className="muted">Reviews and critical issues in {timezoneLabel}.</p>
                </div>
                {qualityToday ? (
                  <>
                    <div className="admin-actions" style={{ justifyContent: "space-between", gap: "16px" }}>
                      <div>
                        <div className="muted">Avg rating</div>
                        <div className="hero-metric-value">
                          {qualityToday.avg_rating ? qualityToday.avg_rating.toFixed(1) : "—"}
                        </div>
                      </div>
                      <div>
                        <div className="muted">Reviews</div>
                        <div className="hero-metric-value">{qualityToday.reviews_count}</div>
                      </div>
                      <div>
                        <div className="muted">Open critical issues</div>
                        <div className="hero-metric-value">{qualityToday.open_critical_issues}</div>
                      </div>
                    </div>
                    <div className="admin-actions" style={{ marginTop: "12px" }}>
                      <a className="btn btn-secondary" href="/admin/quality/issues?severity=critical">
                        Review critical issues
                      </a>
                    </div>
                  </>
                ) : (
                  <p className="muted">Quality metrics are not available for this account.</p>
                )}
              </section>
            ) : null}

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
                opsData.upcoming_events.length > 0 ? (
                  <div className="admin-actions" style={{ flexDirection: "column", alignItems: "stretch", gap: "12px" }}>
                    {opsData.upcoming_events.map((event, index) => (
                      <div key={`${event.title}-${event.starts_at}-${index}`} className="alert alert-info">
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "12px" }}>
                          <div>
                            <strong>{event.title}</strong>
                            <div className="muted">
                              {formatDateTime(event.starts_at, opsData.org_timezone)}
                            </div>
                          </div>
                          {event.entity_ref ? <span className="muted">{String(event.entity_ref.kind ?? "")}</span> : null}
                        </div>
                        {event.actions.length > 0 ? (
                          <div className="admin-actions" style={{ marginTop: "8px", flexWrap: "wrap" }}>
                            {event.actions.map((action) => (
                              <a key={action.href} className="btn btn-secondary" href={action.href}>
                                {action.label}
                              </a>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No critical events in the next 24 hours.</p>
                )
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
                <h2>Top performers (month)</h2>
                {topPerformers ? (
                  <p className="muted">
                    {monthLabel} · Total {formatCurrency(topPerformers.total_revenue_cents, currencyLabel)}
                  </p>
                ) : (
                  <p className="muted">Top performers will appear after ops data.</p>
                )}
              </div>
              {topPerformers ? (
                <div
                  className="admin-grid"
                  style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}
                >
                  <div>
                    <strong>Workers</strong>
                    {topPerformers.workers.length ? (
                      <ol>
                        {topPerformers.workers.map((worker) => (
                          <li key={worker.worker_id} style={{ marginTop: "8px" }}>
                            <div>{worker.name ?? `Worker ${worker.worker_id}`}</div>
                            <div className="muted">
                              {worker.team_name ? `${worker.team_name} · ` : ""}
                              {worker.bookings_count} bookings ·{" "}
                              {formatCurrency(worker.revenue_cents, currencyLabel)}
                            </div>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="muted">No worker bookings this month.</p>
                    )}
                  </div>
                  <div>
                    <strong>Clients</strong>
                    {topPerformers.clients.length ? (
                      <ol>
                        {topPerformers.clients.map((client) => (
                          <li key={client.client_id} style={{ marginTop: "8px" }}>
                            <div>{client.name || client.email || client.client_id}</div>
                            <div className="muted">
                              {client.bookings_count} bookings ·{" "}
                              {formatCurrency(client.revenue_cents, currencyLabel)}
                            </div>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="muted">No client spend this month.</p>
                    )}
                  </div>
                  <div>
                    <strong>Teams</strong>
                    {topPerformers.teams.length ? (
                      <ol>
                        {topPerformers.teams.map((team) => (
                          <li key={team.team_id} style={{ marginTop: "8px" }}>
                            <div>{team.name}</div>
                            <div className="muted">
                              {team.bookings_count} bookings ·{" "}
                              {formatCurrency(team.revenue_cents, currencyLabel)}
                            </div>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="muted">No team revenue this month.</p>
                    )}
                  </div>
                  <div>
                    <strong>Services</strong>
                    {topPerformers.services.length ? (
                      <ol>
                        {topPerformers.services.map((service) => (
                          <li key={service.label} style={{ marginTop: "8px" }}>
                            <div>{service.label}</div>
                            <div className="muted">
                              {service.bookings_count} bookings ·{" "}
                              {formatCurrency(service.revenue_cents, currencyLabel)} ·{" "}
                              {formatPercent(service.share_of_revenue)} share
                            </div>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="muted">No service revenue this month.</p>
                    )}
                  </div>
                </div>
              ) : null}
            </section>

            <section className="admin-card admin-section">
              <div className="section-heading">
                <h2>Quick Actions</h2>
                <p className="muted">Shortcuts are disabled without permission.</p>
              </div>
              <div className="admin-actions" style={{ flexDirection: "column", alignItems: "stretch" }}>
                {quickActions.map((action) => {
                  const featureAllowed = visibilityReady
                    ? isVisible(action.featureKey, permissionKeys, featureOverrides, hiddenKeys)
                    : true;
                  const permissionAllowed = permissionKeys.includes(action.permission);
                  const allowed = featureAllowed && permissionAllowed && !action.disabled;
                  const disabledReason = action.disabled
                    ? "Not implemented"
                    : !featureAllowed
                      ? "Feature disabled"
                      : "Permission required";
                  return allowed ? (
                    <a
                      key={action.key}
                      className="btn btn-secondary"
                      href={action.href}
                      title="Open"
                    >
                      {action.label} · <span className="muted">{action.description}</span>
                    </a>
                  ) : (
                    <button
                      key={action.key}
                      className="btn btn-secondary"
                      type="button"
                      disabled
                      title={disabledReason}
                    >
                      {action.label} · <span className="muted">{action.description}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          </div>
        </div>
        <aside className="ops-dashboard-activity">
          <section className="admin-card admin-section activity-feed">
            <div className="section-heading activity-feed-header">
              <div>
                <h2>Live activity</h2>
                <p className="muted">Auto-refreshes every 45s.</p>
              </div>
              <button
                className="btn btn-ghost"
                type="button"
                onClick={() => setActivityExpanded((prev) => !prev)}
              >
                {activityExpanded ? "Show less" : "Show all"}
              </button>
            </div>
            {activityError ? <p className="alert alert-warning">{activityError}</p> : null}
            {activityLoading ? <p className="muted">Loading activity…</p> : null}
            {activityVisibleItems.length === 0 && !activityLoading ? (
              <p className="muted">No recent activity yet.</p>
            ) : (
              <div className="activity-feed-list">
                {activityVisibleItems.map((item) => (
                  <div key={item.event_id} className="activity-feed-item">
                    <div className="activity-feed-item-heading">
                      <strong>{item.title}</strong>
                      <span className="muted">{formatDateTime(item.timestamp, timezoneLabel)}</span>
                    </div>
                    {item.description ? <div className="muted">{item.description}</div> : null}
                    {item.action ? (
                      <div className="admin-actions">
                        <a className="btn btn-ghost" href={item.action.href}>
                          {item.action.label}
                        </a>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
