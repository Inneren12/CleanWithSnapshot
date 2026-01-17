"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import AdminNav from "../../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../../lib/featureVisibility";
import { DEFAULT_ORG_TIMEZONE, type OrgSettingsResponse } from "../../lib/orgSettings";
import { formatDateKeyInTz } from "../../lib/timezone";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type TeamLeadSummary = {
  worker_id: number;
  name: string;
  role?: string | null;
  rating_avg?: number | null;
};

type TeamDetail = {
  team_id: number;
  name: string;
  created_at: string;
  archived_at?: string | null;
  lead?: TeamLeadSummary | null;
  lead_worker_id?: number | null;
  zones?: string[];
  specializations?: string[];
  calendar_color?: string | null;
  worker_count: number;
  monthly_bookings: number;
  monthly_revenue_cents: number;
  rating_avg?: number | null;
  rating_count: number;
};

type TeamMember = {
  worker_id: number;
  name: string;
  role?: string | null;
  phone: string;
  email?: string | null;
  rating_avg?: number | null;
  rating_count: number;
  is_active: boolean;
};

type TeamMembersResponse = {
  team_id: number;
  members: TeamMember[];
};

type TeamRecentBooking = {
  booking_id: string;
  starts_at: string;
  duration_minutes: number;
  status: string;
  lead_name?: string | null;
  lead_email?: string | null;
};

type TeamRecentBookingsResponse = {
  team_id: number;
  bookings: TeamRecentBooking[];
};

type TeamMetrics = {
  team_id: number;
  range_start: string;
  range_end: string;
  bookings_count: number;
  completed_count: number;
  cancelled_count: number;
  total_revenue_cents: number;
  average_rating?: number | null;
};

type ScheduleBooking = {
  booking_id: string;
  starts_at: string;
  ends_at: string;
  duration_minutes: number;
  status: string;
  worker_id?: number | null;
  worker_name?: string | null;
  team_id: number;
  team_name?: string | null;
  client_label?: string | null;
  address?: string | null;
  service_label?: string | null;
  price_cents?: number | null;
  notes?: string | null;
};

type ScheduleResponse = {
  from_date: string;
  to_date: string;
  bookings: ScheduleBooking[];
};

type TeamSettingsForm = {
  lead_worker_id: string;
  zones: string[];
  specializations: string[];
  calendar_color: string;
};

const ZONE_OPTIONS = [
  "Downtown",
  "Whyte/Old Strathcona",
  "West",
  "South/Millwoods",
  "North/Castle Downs",
  "St. Albert",
];

const SPECIALIZATION_OPTIONS = [
  "Residential",
  "Commercial",
  "Move-out",
  "Deep clean",
  "Post-construction",
];

function formatCurrency(cents: number) {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function formatRating(ratingAvg: number | null | undefined, ratingCount: number) {
  if (!ratingAvg || ratingCount <= 0) return "No ratings yet";
  return `${ratingAvg.toFixed(1)} (${ratingCount} reviews)`;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDateTimeInTz(value: string, timeZone: string) {
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(new Date(value));
}

function formatDateInput(date: Date) {
  return date.toISOString().slice(0, 10);
}

function parseDateInput(value: string) {
  return new Date(`${value}T00:00:00`);
}

function addDaysInput(value: string, offset: number) {
  const date = parseDateInput(value);
  date.setDate(date.getDate() + offset);
  return formatDateInput(date);
}

function weekStartFromInput(value: string) {
  const date = parseDateInput(value);
  const day = date.getDay();
  const diff = (day + 6) % 7;
  date.setDate(date.getDate() - diff);
  return formatDateInput(date);
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-CA", { dateStyle: "medium" }).format(new Date(value));
}

function formatDateInTz(value: string, timeZone: string) {
  return new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeZone }).format(new Date(value));
}

function statusBadge(status?: string) {
  const normalized = (status ?? "").toLowerCase();
  const className = `status-badge ${normalized}`;
  return <span className={className}>{status || "UNKNOWN"}</span>;
}

export default function TeamDetailPage() {
  const params = useParams();
  const teamIdParam = params?.team_id;
  const teamId = Number(Array.isArray(teamIdParam) ? teamIdParam[0] : teamIdParam);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [orgSettings, setOrgSettings] = useState<OrgSettingsResponse | null>(null);
  const [team, setTeam] = useState<TeamDetail | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [recentBookings, setRecentBookings] = useState<TeamRecentBooking[]>([]);
  const [metrics, setMetrics] = useState<TeamMetrics | null>(null);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [scheduleMessage, setScheduleMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "members" | "bookings" | "schedule" | "settings">(
    "overview",
  );
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [settingsForm, setSettingsForm] = useState<TeamSettingsForm | null>(null);
  const [settingsMessage, setSettingsMessage] = useState<string | null>(null);

  const today = useMemo(() => new Date(), []);
  const defaultFrom = useMemo(() => {
    const start = new Date();
    start.setDate(start.getDate() - 29);
    return start;
  }, []);
  const [fromDate, setFromDate] = useState(formatDateInput(defaultFrom));
  const [toDate, setToDate] = useState(formatDateInput(today));
  const [scheduleAnchorDate, setScheduleAnchorDate] = useState(formatDateInput(today));

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [username, password]);

  const scheduleWeekStart = useMemo(
    () => weekStartFromInput(scheduleAnchorDate),
    [scheduleAnchorDate],
  );
  const scheduleWeekEnd = useMemo(
    () => addDaysInput(scheduleWeekStart, 6),
    [scheduleWeekStart],
  );
  const scheduleDays = useMemo(
    () => Array.from({ length: 7 }, (_, index) => addDaysInput(scheduleWeekStart, index)),
    [scheduleWeekStart],
  );

  const permissionKeys = profile?.permissions ?? [];
  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];
  const orgTimezone = orgSettings?.timezone ?? DEFAULT_ORG_TIMEZONE;
  const pageVisible = visibilityReady
    ? isVisible("module.teams", permissionKeys, featureOverrides, hiddenKeys)
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

  const scheduleByDay = useMemo(() => {
    const map: Record<string, ScheduleBooking[]> = {};
    if (!schedule?.bookings) return map;
    schedule.bookings.forEach((booking) => {
      const key = formatDateKeyInTz(booking.starts_at, orgTimezone);
      if (!map[key]) map[key] = [];
      map[key].push(booking);
    });
    Object.values(map).forEach((items) => items.sort((a, b) => a.starts_at.localeCompare(b.starts_at)));
    return map;
  }, [orgTimezone, schedule]);

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

  const loadOrgSettings = useCallback(async () => {
    if (!username || !password) return;
    const response = await fetch(`${API_BASE}/v1/admin/settings/org`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as OrgSettingsResponse;
      setOrgSettings(data);
    }
  }, [authHeaders, password, username]);

  const loadTeam = useCallback(async () => {
    if (!username || !password || Number.isNaN(teamId)) return;
    setErrorMessage(null);
    const response = await fetch(`${API_BASE}/v1/admin/teams/${teamId}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as TeamDetail;
      setTeam(data);
    } else {
      setErrorMessage("Unable to load team details.");
    }
  }, [authHeaders, password, teamId, username]);

  const loadMembers = useCallback(async () => {
    if (!username || !password || Number.isNaN(teamId)) return;
    const response = await fetch(`${API_BASE}/v1/admin/teams/${teamId}/members`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as TeamMembersResponse;
      setMembers(data.members ?? []);
    }
  }, [authHeaders, password, teamId, username]);

  const loadRecentBookings = useCallback(async () => {
    if (!username || !password || Number.isNaN(teamId)) return;
    const response = await fetch(`${API_BASE}/v1/admin/teams/${teamId}/recent_bookings?limit=8`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as TeamRecentBookingsResponse;
      setRecentBookings(data.bookings ?? []);
    }
  }, [authHeaders, password, teamId, username]);

  const loadMetrics = useCallback(async () => {
    if (!username || !password || Number.isNaN(teamId)) return;
    const fromIso = new Date(`${fromDate}T00:00:00Z`).toISOString();
    const toIso = new Date(`${toDate}T23:59:59Z`).toISOString();
    const response = await fetch(`${API_BASE}/v1/admin/teams/${teamId}/metrics?from=${fromIso}&to=${toIso}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as TeamMetrics;
      setMetrics(data);
    }
  }, [authHeaders, fromDate, password, teamId, toDate, username]);

  const loadSchedule = useCallback(async () => {
    if (!username || !password || Number.isNaN(teamId)) return;
    setScheduleMessage(null);
    const params = new URLSearchParams({
      from: scheduleWeekStart,
      to: scheduleWeekEnd,
      team_id: `${teamId}`,
    });
    const response = await fetch(`${API_BASE}/v1/admin/schedule?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    });
    if (response.ok) {
      const data = (await response.json()) as ScheduleResponse;
      setSchedule(data);
    } else {
      setSchedule(null);
      setScheduleMessage("Unable to load the team schedule for this week.");
    }
  }, [authHeaders, password, scheduleWeekEnd, scheduleWeekStart, teamId, username]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadOrgSettings();
    void loadTeam();
    void loadMembers();
    void loadRecentBookings();
    void loadMetrics();
  }, [
    loadFeatureConfig,
    loadMembers,
    loadMetrics,
    loadOrgSettings,
    loadProfile,
    loadRecentBookings,
    loadTeam,
    loadUiPrefs,
  ]);

  useEffect(() => {
    void loadSchedule();
  }, [loadSchedule]);

  useEffect(() => {
    if (!team) return;
    setSettingsForm({
      lead_worker_id: team.lead_worker_id ? `${team.lead_worker_id}` : "",
      zones: team.zones ?? [],
      specializations: team.specializations ?? [],
      calendar_color: team.calendar_color ?? "",
    });
  }, [team]);

  const handleSaveCredentials = () => {
    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
    setStatusMessage("Saved credentials locally.");
    setTimeout(() => setStatusMessage(null), 2000);
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadTeam();
    void loadMembers();
    void loadRecentBookings();
    void loadMetrics();
    void loadSchedule();
  };

  const handleClearCredentials = () => {
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
    setUsername("");
    setPassword("");
    setStatusMessage("Cleared saved credentials.");
    setTimeout(() => setStatusMessage(null), 2000);
  };

  const toggleSelection = (values: string[], value: string) => {
    if (values.includes(value)) {
      return values.filter((item) => item !== value);
    }
    return [...values, value];
  };

  const handleSettingsSave = async () => {
    if (!settingsForm || !username || !password || Number.isNaN(teamId)) return;
    setSettingsMessage(null);
    const payload = {
      lead_worker_id: settingsForm.lead_worker_id ? Number(settingsForm.lead_worker_id) : null,
      zones: settingsForm.zones,
      specializations: settingsForm.specializations,
      calendar_color: settingsForm.calendar_color || null,
    };
    const response = await fetch(`${API_BASE}/v1/admin/teams/${teamId}`, {
      method: "PATCH",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      const data = (await response.json()) as TeamDetail;
      setTeam(data);
      setSettingsMessage("Team settings updated.");
    } else {
      setSettingsMessage("Unable to save team settings.");
    }
    setTimeout(() => setSettingsMessage(null), 3000);
  };

  if (!pageVisible) {
    return (
      <div className="admin-page">
        <AdminNav links={navLinks} activeKey="teams" />
        <div className="admin-card">
          <h1>Teams</h1>
          <p className="muted">You do not have access to view the Teams module.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminNav links={navLinks} activeKey="teams" />
      <header>
        <div className="admin-actions">
          <Link className="btn btn-ghost" href="/admin/teams">
            ← Back to teams
          </Link>
        </div>
        <h1>{team?.name ?? "Team"}</h1>
        <p className="muted">Overview, members, and recent bookings.</p>
      </header>

      <section className="admin-card">
        <h2>Credentials</h2>
        <div className="form-group">
          <label htmlFor="team-username">Username</label>
          <input
            id="team-username"
            className="input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="admin"
          />
        </div>
        <div className="form-group">
          <label htmlFor="team-password">Password</label>
          <input
            id="team-password"
            className="input"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="••••••••"
          />
        </div>
        <div className="admin-actions">
          <button className="btn btn-primary" type="button" onClick={handleSaveCredentials}>
            Save credentials
          </button>
          <button className="btn btn-ghost" type="button" onClick={handleClearCredentials}>
            Clear saved
          </button>
        </div>
        {statusMessage ? <p className="muted">{statusMessage}</p> : null}
      </section>

      {errorMessage ? (
        <div className="admin-card">
          <p className="muted">{errorMessage}</p>
        </div>
      ) : null}

      <section className="admin-actions">
        <button
          className={activeTab === "overview" ? "btn btn-primary" : "btn btn-secondary"}
          type="button"
          onClick={() => setActiveTab("overview")}
        >
          Overview
        </button>
        <button
          className={activeTab === "members" ? "btn btn-primary" : "btn btn-secondary"}
          type="button"
          onClick={() => setActiveTab("members")}
        >
          Members
        </button>
        <button
          className={activeTab === "bookings" ? "btn btn-primary" : "btn btn-secondary"}
          type="button"
          onClick={() => setActiveTab("bookings")}
        >
          Recent bookings
        </button>
        <button
          className={activeTab === "schedule" ? "btn btn-primary" : "btn btn-secondary"}
          type="button"
          onClick={() => setActiveTab("schedule")}
        >
          Weekly schedule
        </button>
        <button
          className={activeTab === "settings" ? "btn btn-primary" : "btn btn-secondary"}
          type="button"
          onClick={() => setActiveTab("settings")}
        >
          Settings
        </button>
      </section>

      {activeTab === "overview" ? (
        <section className="admin-section">
          <div className="admin-grid">
            <article className="admin-card">
              <h3>Team snapshot</h3>
              <p className="muted">
                Lead: {team?.lead ? `${team.lead.name}${team.lead.role ? ` • ${team.lead.role}` : ""}` : "Unassigned"}
              </p>
              <p className="muted">Workers: {team?.worker_count ?? 0}</p>
              <p className="muted">Monthly bookings: {team?.monthly_bookings ?? 0}</p>
              <p className="muted">
                Monthly revenue: {team ? formatCurrency(team.monthly_revenue_cents) : "—"}
              </p>
              <p className="muted">
                Rating: {team ? formatRating(team.rating_avg, team.rating_count) : "—"}
              </p>
            </article>
            <article className="admin-card">
              <h3>Performance range</h3>
              <div className="form-group">
                <label htmlFor="team-from">From</label>
                <input
                  id="team-from"
                  className="input"
                  type="date"
                  value={fromDate}
                  onChange={(event) => setFromDate(event.target.value)}
                />
              </div>
              <div className="form-group">
                <label htmlFor="team-to">To</label>
                <input
                  id="team-to"
                  className="input"
                  type="date"
                  value={toDate}
                  onChange={(event) => setToDate(event.target.value)}
                />
              </div>
              <div className="admin-actions">
                <button className="btn btn-secondary" type="button" onClick={() => void loadMetrics()}>
                  Refresh metrics
                </button>
              </div>
              <p className="muted">
                Range: {metrics ? `${formatDateTime(metrics.range_start)} → ${formatDateTime(metrics.range_end)}` : "—"}
              </p>
            </article>
          </div>

          <div className="admin-grid">
            <article className="admin-card">
              <h4>Total bookings</h4>
              <p className="muted">{metrics?.bookings_count ?? 0}</p>
            </article>
            <article className="admin-card">
              <h4>Completed</h4>
              <p className="muted">{metrics?.completed_count ?? 0}</p>
            </article>
            <article className="admin-card">
              <h4>Cancelled</h4>
              <p className="muted">{metrics?.cancelled_count ?? 0}</p>
            </article>
            <article className="admin-card">
              <h4>Revenue</h4>
              <p className="muted">{metrics ? formatCurrency(metrics.total_revenue_cents) : "—"}</p>
            </article>
            <article className="admin-card">
              <h4>Average rating</h4>
              <p className="muted">{metrics?.average_rating ? metrics.average_rating.toFixed(1) : "—"}</p>
            </article>
          </div>
        </section>
      ) : null}

      {activeTab === "members" ? (
        <section className="admin-card">
          <h3>Team members</h3>
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Role</th>
                  <th>Contact</th>
                  <th>Rating</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.worker_id}>
                    <td>{member.name}</td>
                    <td>{member.role ?? "—"}</td>
                    <td>
                      <div>{member.phone}</div>
                      <div className="muted">{member.email ?? "—"}</div>
                    </td>
                    <td>{formatRating(member.rating_avg, member.rating_count)}</td>
                    <td>{member.is_active ? "Active" : "Inactive"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {members.length === 0 ? <p className="muted">No team members found.</p> : null}
        </section>
      ) : null}

      {activeTab === "bookings" ? (
        <section className="admin-card">
          <h3>Recent bookings</h3>
          <div className="table-responsive">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Booking</th>
                  <th>Start</th>
                  <th>Status</th>
                  <th>Lead</th>
                  <th>Duration</th>
                </tr>
              </thead>
              <tbody>
                {recentBookings.map((booking) => (
                  <tr key={booking.booking_id}>
                    <td>{booking.booking_id}</td>
                    <td>{formatDateTime(booking.starts_at)}</td>
                    <td>{statusBadge(booking.status)}</td>
                    <td>
                      <div>{booking.lead_name ?? "—"}</div>
                      <div className="muted">{booking.lead_email ?? "—"}</div>
                    </td>
                    <td>{booking.duration_minutes} min</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {recentBookings.length === 0 ? <p className="muted">No bookings found.</p> : null}
        </section>
      ) : null}

      {activeTab === "schedule" ? (
        <section className="admin-card">
          <div className="admin-actions" style={{ justifyContent: "space-between" }}>
            <div>
              <h3>Weekly schedule</h3>
              <p className="muted">
                {formatDateInTz(scheduleWeekStart, orgTimezone)} →{" "}
                {formatDateInTz(scheduleWeekEnd, orgTimezone)}
              </p>
            </div>
            <div className="admin-actions">
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => setScheduleAnchorDate(addDaysInput(scheduleWeekStart, -7))}
              >
                Previous week
              </button>
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => setScheduleAnchorDate(addDaysInput(scheduleWeekStart, 7))}
              >
                Next week
              </button>
            </div>
          </div>
          {scheduleMessage ? <p className="muted">{scheduleMessage}</p> : null}
          <div className="admin-grid">
            {scheduleDays.map((day) => {
              const dayBookings = scheduleByDay[day] ?? [];
              return (
                <article className="admin-card" key={day}>
                  <h4>{formatDateInTz(day, orgTimezone)}</h4>
                  {dayBookings.length === 0 ? (
                    <p className="muted">No bookings.</p>
                  ) : (
                    <ul className="list">
                      {dayBookings.map((booking) => (
                        <li key={booking.booking_id}>
                          <div>
                            <strong>{formatDateTimeInTz(booking.starts_at, orgTimezone)}</strong>
                          </div>
                          <div className="muted">
                            {booking.client_label ?? "Client TBD"} • {booking.service_label ?? "Service TBD"}
                          </div>
                          <div className="muted">
                            {booking.worker_name ?? "Unassigned"} • {booking.duration_minutes} min
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      {activeTab === "settings" ? (
        <section className="admin-card">
          <h3>Team settings</h3>
          {!settingsForm ? (
            <p className="muted">Loading settings…</p>
          ) : (
            <>
              <div className="form-group">
                <label htmlFor="team-lead">Team lead</label>
                <select
                  id="team-lead"
                  className="input"
                  value={settingsForm.lead_worker_id}
                  onChange={(event) =>
                    setSettingsForm((prev) =>
                      prev ? { ...prev, lead_worker_id: event.target.value } : prev,
                    )
                  }
                >
                  <option value="">Unassigned</option>
                  {members.map((member) => (
                    <option key={member.worker_id} value={`${member.worker_id}`}>
                      {member.name} {member.role ? `• ${member.role}` : ""}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Zones coverage</label>
                <div className="checkbox-grid">
                  {ZONE_OPTIONS.map((zone) => (
                    <label key={zone} className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={settingsForm.zones.includes(zone)}
                        onChange={() =>
                          setSettingsForm((prev) =>
                            prev ? { ...prev, zones: toggleSelection(prev.zones, zone) } : prev,
                          )
                        }
                      />
                      <span>{zone}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="form-group">
                <label>Specializations</label>
                <div className="checkbox-grid">
                  {SPECIALIZATION_OPTIONS.map((specialization) => (
                    <label key={specialization} className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={settingsForm.specializations.includes(specialization)}
                        onChange={() =>
                          setSettingsForm((prev) =>
                            prev
                              ? {
                                  ...prev,
                                  specializations: toggleSelection(prev.specializations, specialization),
                                }
                              : prev,
                          )
                        }
                      />
                      <span>{specialization}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="team-color">Calendar color</label>
                <input
                  id="team-color"
                  className="input"
                  type="color"
                  value={settingsForm.calendar_color || "#2563eb"}
                  onChange={(event) =>
                    setSettingsForm((prev) =>
                      prev ? { ...prev, calendar_color: event.target.value } : prev,
                    )
                  }
                />
              </div>

              <div className="admin-actions">
                <button className="btn btn-primary" type="button" onClick={() => void handleSettingsSave()}>
                  Save settings
                </button>
              </div>
              {settingsMessage ? <p className="muted">{settingsMessage}</p> : null}
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}
