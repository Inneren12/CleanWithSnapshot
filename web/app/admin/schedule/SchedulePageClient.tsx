"use client";

import { type DragEvent, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import AdminNav from "../components/AdminNav";
import {
  type AdminProfile,
  type FeatureConfigResponse,
  type UiPrefsResponse,
  isVisible,
} from "../lib/featureVisibility";
import { DEFAULT_ORG_TIMEZONE, type OrgSettingsResponse } from "../lib/orgSettings";

const STORAGE_USERNAME_KEY = "admin_basic_username";
const STORAGE_PASSWORD_KEY = "admin_basic_password";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const START_HOUR = 8;
const END_HOUR = 18;
const SLOT_MINUTES = 30;
const SLOT_HEIGHT = 28;

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const WEEKDAY_INDEX: Record<string, number> = {
  Mon: 0,
  Tue: 1,
  Wed: 2,
  Thu: 3,
  Fri: 4,
  Sat: 5,
  Sun: 6,
};

type ScheduleBooking = {
  booking_id: string;
  starts_at: string;
  ends_at: string;
  duration_minutes: number;
  status: string;
  worker_id: number | null;
  worker_name: string | null;
  team_id: number;
  team_name: string | null;
  client_label: string | null;
  address: string | null;
  service_label: string | null;
  price_cents: number | null;
};

type ScheduleResponse = {
  from_date: string;
  to_date: string;
  bookings: ScheduleBooking[];
};

type ToastMessage = {
  message: string;
  kind: "error" | "success";
};

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

function weekStartFromDay(day: string, timeZone: string) {
  const base = ymdToDate(day);
  const weekdayLabel = new Intl.DateTimeFormat("en-CA", { weekday: "short", timeZone }).format(base);
  const offset = WEEKDAY_INDEX[weekdayLabel] ?? 0;
  return addDaysYMD(day, -offset, timeZone);
}

function formatDayLabel(day: string, timeZone: string) {
  const formatted = new Intl.DateTimeFormat("en-CA", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone,
  }).format(ymdToDate(day));
  return formatted.replace(",", "");
}

function formatTimeLabel(hour: number) {
  return `${hour.toString().padStart(2, "0")}:00`;
}

function formatTimeRange(startsAt: string, endsAt: string, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  });
  return `${formatter.format(new Date(startsAt))}–${formatter.format(new Date(endsAt))}`;
}

function formatCurrencyFromCents(value: number | null) {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(value / 100);
}

function minutesFromTime(value: string, timeZone: string) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  });
  const parts = formatter.formatToParts(new Date(value));
  const lookup: Record<string, string> = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const hours = parseInt(lookup.hour || "0", 10);
  const minutes = parseInt(lookup.minute || "0", 10);
  return hours * 60 + minutes;
}

function localDayForBooking(value: string, timeZone: string) {
  return formatYMDInTz(new Date(value), timeZone);
}

function buildLocalDateTime(day: string, minutes: number) {
  const [year, month, dayValue] = day.split("-").map((value) => parseInt(value, 10));
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return new Date(year, month - 1, dayValue, hours, mins, 0);
}

export default function SchedulePage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [profile, setProfile] = useState<AdminProfile | null>(null);
  const [featureConfig, setFeatureConfig] = useState<FeatureConfigResponse | null>(null);
  const [uiPrefs, setUiPrefs] = useState<UiPrefsResponse | null>(null);
  const [orgSettings, setOrgSettings] = useState<OrgSettingsResponse | null>(null);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const [draggingBookingId, setDraggingBookingId] = useState<string | null>(null);

  const orgTimezone = orgSettings?.timezone ?? DEFAULT_ORG_TIMEZONE;
  const defaultDate = useMemo(() => formatYMDInTz(new Date(), orgTimezone), [orgTimezone]);

  const [selectedDate, setSelectedDate] = useState<string>(searchParams.get("date") ?? defaultDate);
  const [teamFilter, setTeamFilter] = useState<string>(searchParams.get("team_id") ?? "");
  const [workerFilter, setWorkerFilter] = useState<string>(searchParams.get("worker_id") ?? "");
  const [statusFilter, setStatusFilter] = useState<string>(searchParams.get("status") ?? "");

  const isAuthenticated = Boolean(username && password);
  const permissionKeys = profile?.permissions ?? [];
  const canAssign =
    permissionKeys.includes("bookings.assign") || permissionKeys.includes("bookings.edit");

  const visibilityReady = Boolean(profile && featureConfig && uiPrefs);
  const featureOverrides = featureConfig?.overrides ?? {};
  const hiddenKeys = uiPrefs?.hidden_keys ?? [];

  const scheduleVisible = visibilityReady
    ? isVisible("module.schedule", permissionKeys, featureOverrides, hiddenKeys)
    : true;

  const navLinks = useMemo(() => {
    if (!visibilityReady || !profile) return [];
    const candidates = [
      { key: "dashboard", label: "Dashboard", href: "/admin", featureKey: "module.dashboard" },
      { key: "schedule", label: "Schedule", href: "/admin/schedule", featureKey: "module.schedule" },
      { key: "dispatcher", label: "Dispatcher", href: "/admin/dispatcher", featureKey: "module.schedule" },
      { key: "org-settings", label: "Org Settings", href: "/admin/settings/org", featureKey: "module.settings" },
      {
        key: "pricing",
        label: "Service Types & Pricing",
        href: "/admin/settings/pricing",
        featureKey: "module.settings",
      },
      {
        key: "policies",
        label: "Booking Policies",
        href: "/admin/settings/booking-policies",
        featureKey: "module.settings",
      },
      { key: "modules", label: "Modules & Visibility", href: "/admin/settings/modules", featureKey: "api.settings" },
      { key: "roles", label: "Roles & Permissions", href: "/admin/iam/roles", featureKey: "module.teams" },
    ];
    return candidates
      .filter((entry) => isVisible(entry.featureKey, permissionKeys, featureOverrides, hiddenKeys))
      .map(({ featureKey, ...link }) => link);
  }, [featureOverrides, hiddenKeys, permissionKeys, profile, visibilityReady]);

  const authHeaders = useMemo<Record<string, string>>(() => {
    if (!username || !password) return {} as Record<string, string>;
    const encoded = btoa(`${username}:${password}`);
    return { Authorization: `Basic ${encoded}` };
  }, [password, username]);

  const showToast = useCallback((message: string, kind: "error" | "success" = "error") => {
    setToast({ message, kind });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  useEffect(() => {
    const storedUsername = window.localStorage.getItem(STORAGE_USERNAME_KEY);
    const storedPassword = window.localStorage.getItem(STORAGE_PASSWORD_KEY);
    if (storedUsername) setUsername(storedUsername);
    if (storedPassword) setPassword(storedPassword);
  }, []);

  useEffect(() => {
    if (searchParams.get("date")) {
      setSelectedDate(searchParams.get("date") as string);
      return;
    }
    setSelectedDate(defaultDate);
  }, [defaultDate, searchParams]);

  useEffect(() => {
    setTeamFilter(searchParams.get("team_id") ?? "");
    setWorkerFilter(searchParams.get("worker_id") ?? "");
    setStatusFilter(searchParams.get("status") ?? "");
  }, [searchParams]);

  const updateQuery = useCallback(
    (updates: Record<string, string>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(updates).forEach(([key, value]) => {
        if (!value) {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      });
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams]
  );

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
    } else {
      setFeatureConfig(null);
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
    } else {
      setUiPrefs(null);
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
    } else {
      setOrgSettings(null);
    }
  }, [authHeaders, password, username]);

  useEffect(() => {
    if (!isAuthenticated) return;
    void loadProfile();
    void loadFeatureConfig();
    void loadUiPrefs();
    void loadOrgSettings();
  }, [isAuthenticated, loadFeatureConfig, loadOrgSettings, loadProfile, loadUiPrefs]);

  useEffect(() => {
    if (!isAuthenticated) return;
    if (!scheduleVisible) return;
    setLoading(true);
    setError(null);
    const weekStart = weekStartFromDay(selectedDate, orgTimezone);
    const weekEnd = addDaysYMD(weekStart, 6, orgTimezone);
    const params = new URLSearchParams({
      from: weekStart,
      to: weekEnd,
    });
    if (teamFilter) params.set("team_id", teamFilter);
    if (workerFilter) params.set("worker_id", workerFilter);
    if (statusFilter) params.set("status", statusFilter);

    fetch(`${API_BASE}/v1/admin/schedule?${params.toString()}`, {
      headers: authHeaders,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Failed to load schedule");
        }
        return response.json();
      })
      .then((payload: ScheduleResponse) => {
        setSchedule(payload);
      })
      .catch((fetchError) => {
        setSchedule(null);
        setError(fetchError instanceof Error ? fetchError.message : "Failed to load schedule");
      })
      .finally(() => setLoading(false));
  }, [authHeaders, isAuthenticated, orgTimezone, scheduleVisible, selectedDate, statusFilter, teamFilter, workerFilter]);

  const weekStart = useMemo(() => weekStartFromDay(selectedDate, orgTimezone), [selectedDate, orgTimezone]);
  const weekDays = useMemo(
    () => WEEKDAY_LABELS.map((_, index) => addDaysYMD(weekStart, index, orgTimezone)),
    [orgTimezone, weekStart]
  );

  const timeSlots = useMemo(() => {
    const slots: number[] = [];
    for (let hour = START_HOUR; hour <= END_HOUR; hour += 1) {
      slots.push(hour);
    }
    return slots;
  }, []);

  const dayMinutes = (END_HOUR - START_HOUR) * 60;
  const gridHeight = (dayMinutes / SLOT_MINUTES) * SLOT_HEIGHT;

  const bookingsByDay = useMemo(() => {
    const mapping = new Map<string, ScheduleBooking[]>();
    if (!schedule) return mapping;
    for (const day of weekDays) {
      mapping.set(day, []);
    }
    for (const booking of schedule.bookings) {
      const bookingDay = localDayForBooking(booking.starts_at, orgTimezone);
      if (!mapping.has(bookingDay)) continue;
      mapping.get(bookingDay)?.push(booking);
    }
    mapping.forEach((entries) =>
      entries.sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime())
    );
    return mapping;
  }, [orgTimezone, schedule, weekDays]);

  const workerOptions = useMemo(() => {
    const map = new Map<number, string>();
    schedule?.bookings.forEach((booking) => {
      if (booking.worker_id && booking.worker_name) {
        map.set(booking.worker_id, booking.worker_name);
      }
    });
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [schedule]);

  const teamOptions = useMemo(() => {
    const map = new Map<number, string>();
    schedule?.bookings.forEach((booking) => {
      if (booking.team_id) {
        map.set(booking.team_id, booking.team_name ?? `Team ${booking.team_id}`);
      }
    });
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [schedule]);

  const statusOptions = useMemo(() => {
    const set = new Set<string>();
    schedule?.bookings.forEach((booking) => {
      if (booking.status) set.add(booking.status);
    });
    return Array.from(set.values()).sort();
  }, [schedule]);

  const handleDrop = useCallback(
    async (event: DragEvent<HTMLDivElement>, day: string) => {
      event.preventDefault();
      if (!schedule || !canAssign) return;
      const bookingId = event.dataTransfer.getData("text/plain");
      if (!bookingId) return;
      const booking = schedule.bookings.find((item) => item.booking_id === bookingId);
      if (!booking) return;

      const rect = event.currentTarget.getBoundingClientRect();
      const offsetY = Math.max(0, event.clientY - rect.top);
      const rawMinutes = Math.round(offsetY / SLOT_HEIGHT) * SLOT_MINUTES;
      const minutesFromStart = Math.min(Math.max(rawMinutes, 0), dayMinutes);
      const minutes = START_HOUR * 60 + minutesFromStart;
      const newStart = buildLocalDateTime(day, minutes);
      const newEnd = new Date(newStart.getTime() + booking.duration_minutes * 60000);

      const previous = booking;
      const optimistic: ScheduleBooking = {
        ...booking,
        starts_at: newStart.toISOString(),
        ends_at: newEnd.toISOString(),
      };

      setSchedule((current) => {
        if (!current) return current;
        return {
          ...current,
          bookings: current.bookings.map((item) =>
            item.booking_id === bookingId ? optimistic : item
          ),
        };
      });

      try {
        const response = await fetch(`${API_BASE}/v1/admin/bookings/${bookingId}`, {
          method: "PATCH",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            starts_at: newStart.toISOString(),
            ends_at: newEnd.toISOString(),
          }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          const message =
            payload?.detail?.message || payload?.detail || response.statusText || "Update failed";
          throw new Error(message);
        }
        const updated = (await response.json()) as ScheduleBooking;
        setSchedule((current) => {
          if (!current) return current;
          return {
            ...current,
            bookings: current.bookings.map((item) =>
              item.booking_id === bookingId ? updated : item
            ),
          };
        });
        showToast("Booking updated", "success");
      } catch (fetchError) {
        setSchedule((current) => {
          if (!current) return current;
          return {
            ...current,
            bookings: current.bookings.map((item) =>
              item.booking_id === bookingId ? previous : item
            ),
          };
        });
        showToast(fetchError instanceof Error ? fetchError.message : "Update failed");
      }
    },
    [authHeaders, canAssign, dayMinutes, schedule, showToast]
  );

  if (visibilityReady && !scheduleVisible) {
    return (
      <div className="schedule-page">
        <AdminNav links={navLinks} activeKey="schedule" />
        <section className="card">
          <div className="card-body">
            <h1>Schedule</h1>
            <p className="muted">Schedule module access is disabled for your role.</p>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="schedule-page">
      <AdminNav links={navLinks} activeKey="schedule" />
      <header className="schedule-header">
        <div>
          <h1>Week Schedule</h1>
          <p className="muted">Dispatcher week view in {orgTimezone}.</p>
        </div>
        {toast ? (
          <div className={`schedule-toast ${toast.kind}`}>{toast.message}</div>
        ) : null}
      </header>

      <section className="card">
        <div className="card-body">
          <div className="schedule-auth">
            <div className="schedule-auth-fields">
              <input
                className="input"
                type="text"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="admin"
              />
              <input
                className="input"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="password"
              />
            </div>
            <div className="schedule-auth-actions">
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => {
                  if (username && password) {
                    window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
                    window.localStorage.setItem(STORAGE_PASSWORD_KEY, password);
                    void loadProfile();
                    void loadFeatureConfig();
                    void loadUiPrefs();
                    void loadOrgSettings();
                  }
                }}
              >
                Save Credentials
              </button>
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => {
                  setUsername("");
                  setPassword("");
                  window.localStorage.removeItem(STORAGE_USERNAME_KEY);
                  window.localStorage.removeItem(STORAGE_PASSWORD_KEY);
                  setProfile(null);
                  setSchedule(null);
                }}
              >
                Clear
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-body">
          <div className="schedule-controls">
            <div className="schedule-week-controls">
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => updateQuery({ date: addDaysYMD(selectedDate, -7, orgTimezone) })}
              >
                Previous
              </button>
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => updateQuery({ date: defaultDate })}
              >
                Today
              </button>
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => updateQuery({ date: addDaysYMD(selectedDate, 7, orgTimezone) })}
              >
                Next
              </button>
              <input
                className="input"
                type="date"
                value={selectedDate}
                onChange={(event) => updateQuery({ date: event.target.value })}
              />
            </div>
            <div className="schedule-filters">
              <label className="stack">
                <span className="muted">Team</span>
                <select
                  className="input"
                  value={teamFilter}
                  onChange={(event) => updateQuery({ team_id: event.target.value })}
                >
                  <option value="">All teams</option>
                  {teamOptions.map((team) => (
                    <option key={team.id} value={team.id}>
                      {team.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="stack">
                <span className="muted">Worker</span>
                <select
                  className="input"
                  value={workerFilter}
                  onChange={(event) => updateQuery({ worker_id: event.target.value })}
                >
                  <option value="">All workers</option>
                  {workerOptions.map((worker) => (
                    <option key={worker.id} value={worker.id}>
                      {worker.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="stack">
                <span className="muted">Status</span>
                <select
                  className="input"
                  value={statusFilter}
                  onChange={(event) => updateQuery({ status: event.target.value })}
                >
                  <option value="">All statuses</option>
                  {statusOptions.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {!canAssign ? (
            <p className="muted schedule-readonly">Read-only role: drag & drop disabled.</p>
          ) : null}
          {error ? <p className="muted schedule-error">{error}</p> : null}
          {loading ? <p className="muted">Loading schedule…</p> : null}
        </div>
      </section>

      <section className="schedule-grid">
        <div className="schedule-time-column">
          <div className="schedule-day-header">Time</div>
          <div className="schedule-time-body" style={{ height: gridHeight }}>
            {timeSlots.map((hour, index) => (
              <div
                key={hour}
                className="schedule-time-slot"
                style={{ height: SLOT_HEIGHT * (index === timeSlots.length - 1 ? 1 : 2) }}
              >
                {formatTimeLabel(hour)}
              </div>
            ))}
          </div>
        </div>

        {weekDays.map((day) => {
          const bookings = bookingsByDay.get(day) ?? [];
          return (
            <div
              key={day}
              className="schedule-day-column"
              onDragOver={(event) => {
                if (!canAssign) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
              }}
              onDrop={(event) => handleDrop(event, day)}
            >
              <div className="schedule-day-header">{formatDayLabel(day, orgTimezone)}</div>
              <div className="schedule-day-body" style={{ height: gridHeight }}>
                {bookings.map((booking) => {
                  const bookingStartMinutes = minutesFromTime(booking.starts_at, orgTimezone);
                  const bookingEndMinutes = minutesFromTime(booking.ends_at, orgTimezone);
                  const top =
                    ((bookingStartMinutes - START_HOUR * 60) / SLOT_MINUTES) * SLOT_HEIGHT;
                  const height =
                    ((bookingEndMinutes - bookingStartMinutes) / SLOT_MINUTES) * SLOT_HEIGHT;
                  const clampedTop = Math.max(0, top);
                  const clampedHeight = Math.max(SLOT_HEIGHT, Math.min(height, gridHeight - clampedTop));
                  return (
                    <div
                      key={booking.booking_id}
                      className={`schedule-booking${
                        draggingBookingId === booking.booking_id ? " dragging" : ""
                      }`}
                      style={{
                        top: clampedTop,
                        height: clampedHeight,
                      }}
                      draggable={canAssign}
                      onDragStart={(event) => {
                        if (!canAssign) return;
                        setDraggingBookingId(booking.booking_id);
                        event.dataTransfer.setData("text/plain", booking.booking_id);
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      onDragEnd={() => setDraggingBookingId(null)}
                    >
                      <div className="schedule-booking-title">
                        {booking.client_label ?? "Booking"}
                      </div>
                      <div className="schedule-booking-subtitle">
                        {booking.service_label ?? booking.status}
                      </div>
                      <div className="schedule-booking-meta">
                        {formatTimeRange(booking.starts_at, booking.ends_at, orgTimezone)}
                      </div>
                      <div className="schedule-booking-meta">
                        {booking.worker_name ? `Worker: ${booking.worker_name}` : "Unassigned"}
                      </div>
                      <div className="schedule-booking-meta">
                        {formatCurrencyFromCents(booking.price_cents)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}
