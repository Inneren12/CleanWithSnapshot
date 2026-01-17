"use client";

import Link from "next/link";
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

type NotificationItem = {
  id: string;
  created_at: string;
  priority: string;
  type: string;
  title: string;
  body: string;
  entity_type?: string | null;
  entity_id?: string | null;
  action_href?: string | null;
  action_kind?: string | null;
  is_read: boolean;
  read_at?: string | null;
};

type NotificationFeedResponse = {
  items: NotificationItem[];
  next_cursor?: string | null;
  limit: number;
};

const FILTER_OPTIONS = [
  { key: "all", label: "All" },
  { key: "urgent", label: "Urgent" },
  { key: "unread", label: "Unread" },
] as const;

const ACTION_LABELS: Record<string, string> = {
  booking: "Open booking",
  invoice: "Open invoice",
  lead: "Open lead",
  issue: "Open issue",
  quality_issue: "Open issue",
  open_booking: "Open booking",
  open_invoice: "Open invoice",
  open_lead: "Open lead",
  open_issue: "Open issue",
};

function resolveActionHref(event: NotificationItem) {
  if (event.action_href) return event.action_href;
  if (!event.entity_type || !event.entity_id) return null;
  switch (event.entity_type) {
    case "booking":
      return `/admin/schedule?booking_id=${event.entity_id}`;
    case "invoice":
      return `/admin/invoices/${event.entity_id}`;
    case "lead":
      return `/admin?lead_id=${event.entity_id}`;
    case "issue":
    case "quality_issue":
      return `/admin/quality/issues/${event.entity_id}`;
    default:
      return null;
  }
}

function resolveActionLabel(event: NotificationItem) {
  if (event.action_kind && ACTION_LABELS[event.action_kind]) {
    return ACTION_LABELS[event.action_kind];
  }
  if (event.entity_type && ACTION_LABELS[event.entity_type]) {
    return ACTION_LABELS[event.entity_type];
  }
  return "Open";
}

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function dateInputToIso(value: string, boundary: "start" | "end") {
  if (!value) return null;
  const suffix = boundary === "end" ? "T23:59:59" : "T00:00:00";
  const date = new Date(`${value}${suffix}`);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

export default function NotificationsPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [filterKey, setFilterKey] = useState<(typeof FILTER_OPTIONS)[number]["key"]>("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const storedUsername = localStorage.getItem(STORAGE_USERNAME_KEY) || "";
    const storedPassword = localStorage.getItem(STORAGE_PASSWORD_KEY) || "";
    setUsername(storedUsername);
    setPassword(storedPassword);
  }, []);

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
    ? isVisible("module.notifications_center", permissionKeys, featureOverrides, hiddenKeys)
    : true;

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
      { key: "invoices", label: "Invoices", href: "/admin/invoices", featureKey: "module.invoices" },
      { key: "quality", label: "Quality", href: "/admin/quality", featureKey: "module.quality" },
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
    const response = await fetch(`${API_BASE}/v1/admin/settings/features`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as FeatureConfigResponse;
      setFeatureConfig(data);
    }
  }, [authHeaders, password, username]);

  const loadUiPrefs = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/users/me/ui_prefs`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as UiPrefsResponse;
      setUiPrefs(data);
    }
  }, [authHeaders, password, username]);

  const fetchNotifications = useCallback(
    async ({ cursor, append }: { cursor?: string | null; append?: boolean }) => {
      if (!username || !password) return;
      setLoading(true);
      setErrorMessage(null);
      const params = new URLSearchParams();
      params.set("filter", filterKey);
      params.set("limit", "25");
      const fromIso = dateInputToIso(dateFrom, "start");
      const toIso = dateInputToIso(dateTo, "end");
      if (fromIso) params.set("from", fromIso);
      if (toIso) params.set("to", toIso);
      if (cursor) params.set("cursor", cursor);

      const response = await fetch(`${API_BASE}/v1/admin/notifications?${params.toString()}`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (!response.ok) {
        setLoading(false);
        setErrorMessage("Failed to load notifications.");
        return;
      }
      const data = (await response.json()) as NotificationFeedResponse;
      setNotifications((previous) => (append ? [...previous, ...data.items] : data.items));
      setNextCursor(data.next_cursor ?? null);
      setLoading(false);
    },
    [authHeaders, dateFrom, dateTo, filterKey, password, username]
  );

  const markNotificationRead = useCallback(
    async (eventId: string) => {
      if (!username || !password) return;
      const response = await fetch(`${API_BASE}/v1/admin/notifications/${eventId}/read`, {
        method: "POST",
        headers: authHeaders,
      });
      if (!response.ok) {
        setErrorMessage("Failed to mark notification as read.");
        return;
      }
      setNotifications((previous) =>
        previous.map((item) =>
          item.id === eventId
            ? {
                ...item,
                is_read: true,
                read_at: new Date().toISOString(),
              }
            : item
        )
      );
    },
    [authHeaders, password, username]
  );

  const markAllRead = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/notifications/read_all`, {
      method: "POST",
      headers: authHeaders,
    });
    if (!response.ok) {
      setErrorMessage("Failed to mark all notifications as read.");
      return;
    }
    setNotifications((previous) =>
      previous.map((item) => ({
        ...item,
        is_read: true,
        read_at: item.read_at ?? new Date().toISOString(),
      }))
    );
    setStatusMessage("All notifications marked as read.");
  }, [authHeaders, password, username]);

  useEffect(() => {
    if (!username || !password) return;
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
  }, [loadFeatureConfig, loadProfile, loadUiPrefs, password, username]);

  useEffect(() => {
    if (!username || !password) return;
    void fetchNotifications({ append: false });
  }, [fetchNotifications, filterKey, password, username]);

  const unreadCount = notifications.filter((item) => !item.is_read).length;
  const urgentCount = notifications.filter((item) => ["CRITICAL", "HIGH"].includes(item.priority)).length;

  if (visibilityReady && !pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="notifications" />
        <div className="admin-card admin-section">
          <h1>Notifications</h1>
          <p className="alert alert-warning">Disabled by org settings.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="notifications" />
      <div className="admin-section">
        <h1>Notifications Center</h1>
        <p className="muted">Track urgent alerts and keep a shared operational inbox up to date.</p>
      </div>

      {statusMessage ? <p className="alert alert-success">{statusMessage}</p> : null}
      {errorMessage ? <p className="alert alert-warning">{errorMessage}</p> : null}

      <section className="admin-card admin-section">
        <h2>Credentials</h2>
        <div className="admin-actions">
          <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              localStorage.setItem(STORAGE_USERNAME_KEY, username);
              localStorage.setItem(STORAGE_PASSWORD_KEY, password);
              setStatusMessage("Credentials saved.");
            }}
          >
            Save
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            onClick={() => {
              localStorage.removeItem(STORAGE_USERNAME_KEY);
              localStorage.removeItem(STORAGE_PASSWORD_KEY);
              setUsername("");
              setPassword("");
              setStatusMessage("Credentials cleared.");
            }}
          >
            Clear
          </button>
        </div>
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading">
          <h2>Inbox summary</h2>
          <div className="admin-actions">
            <button className="btn btn-ghost" type="button" onClick={() => fetchNotifications({ append: false })}>
              Refresh
            </button>
            <button className="btn btn-secondary" type="button" onClick={() => void markAllRead()}>
              Mark all read
            </button>
          </div>
        </div>
        <div className="kpi-grid">
          <div className="kpi-card">
            <span className="kpi-label">Showing</span>
            <strong>{notifications.length}</strong>
          </div>
          <div className="kpi-card">
            <span className="kpi-label">Unread</span>
            <strong>{unreadCount}</strong>
          </div>
          <div className="kpi-card">
            <span className="kpi-label">Urgent</span>
            <strong>{urgentCount}</strong>
          </div>
        </div>
      </section>

      <section className="admin-card admin-section">
        <div className="section-heading">
          <h2>Filters</h2>
          <div className="admin-actions">
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => fetchNotifications({ append: false })}
              disabled={loading}
            >
              Apply filters
            </button>
          </div>
        </div>
        <div className="chip-group">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option.key}
              className={`chip ${filterKey === option.key ? "chip-selected" : ""}`}
              type="button"
              onClick={() => setFilterKey(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="kpi-date-range">
          <label>
            <span className="label">From</span>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label>
            <span className="label">To</span>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
        </div>
      </section>

      <section className="admin-section">
        {loading ? <p className="muted">Loading notifications…</p> : null}
        {notifications.length === 0 && !loading ? (
          <div className="admin-card">
            <p className="muted">No notifications found for the selected filters.</p>
          </div>
        ) : null}
        {notifications.map((event) => {
          const actionHref = resolveActionHref(event);
          const actionLabel = resolveActionLabel(event);
          const priorityClass =
            event.priority === "CRITICAL" || event.priority === "HIGH" ? "pill pill-warning" : "pill";
          const readClass = event.is_read ? "pill" : "pill pill-warning";
          return (
            <div key={event.id} className="admin-card">
              <div className="section-heading">
                <h3>{event.title}</h3>
                <p className="muted">{event.body}</p>
                <div className="pill-row">
                  <span className={priorityClass}>{event.priority}</span>
                  <span className={readClass}>{event.is_read ? "Read" : "Unread"}</span>
                </div>
              </div>
              <div className="admin-grid">
                <div>
                  <span className="label">Created</span>
                  <div>{formatTimestamp(event.created_at)}</div>
                </div>
                <div>
                  <span className="label">Type</span>
                  <div>{event.type}</div>
                </div>
                {event.entity_type ? (
                  <div>
                    <span className="label">Entity</span>
                    <div>
                      {event.entity_type}
                      {event.entity_id ? ` · ${event.entity_id}` : ""}
                    </div>
                  </div>
                ) : null}
              </div>
              <div className="admin-actions">
                {actionHref ? (
                  <Link className="btn btn-secondary" href={actionHref}>
                    {actionLabel}
                  </Link>
                ) : null}
                {!event.is_read ? (
                  <button className="btn btn-ghost" type="button" onClick={() => void markNotificationRead(event.id)}>
                    Mark read
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
        {nextCursor ? (
          <div className="admin-card">
            <button
              className="btn btn-secondary"
              type="button"
              onClick={() => fetchNotifications({ append: true, cursor: nextCursor })}
              disabled={loading}
            >
              Load more
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}
